import uuid

import pytest
from sqlalchemy import func, select

from fief.db import AsyncSession
from fief.models import Role, Tenant, User, UserPermission, UserRole
from fief.repositories import UserPermissionRepository
from fief.tasks.base import TaskError
from fief.tasks.roles import OnRoleUpdated
from tests.data import TestData


async def create_users_with_role(
    session: AsyncSession, tenant: Tenant, role: Role, count: int
) -> list[User]:
    users = [
        User(
            email=f"user{i}@bretagne.duchy",
            hashed_password="herminetincture",
            tenant_id=tenant.id,
        )
        for i in range(count)
    ]
    session.add_all(users)
    await session.flush()
    session.add_all([UserRole(user_id=user.id, role_id=role.id) for user in users])
    await session.commit()
    return users


async def count_user_permissions(
    session: AsyncSession, role: Role, permission_id: uuid.UUID
) -> int:
    statement = (
        select(func.count())
        .select_from(UserPermission)
        .where(
            UserPermission.permission_id == permission_id,
            UserPermission.from_role_id == role.id,
        )
    )
    result = await session.execute(statement)
    return result.scalar_one()


@pytest.mark.asyncio
class TestTasksOnRoleUpdated:
    async def test_not_existing_role(
        self,
        main_session_manager,
        not_existing_uuid: uuid.UUID,
    ):
        on_user_role_updated = OnRoleUpdated(main_session_manager)

        with pytest.raises(TaskError):
            await on_user_role_updated.run(str(not_existing_uuid), [], [])

    async def test_role_created_added_permission(
        self,
        main_session_manager,
        test_data: TestData,
        main_session: AsyncSession,
    ):
        on_user_role_updated = OnRoleUpdated(main_session_manager)

        role = test_data["roles"]["castles_visitor"]
        permission = test_data["permissions"]["castles:create"]
        await on_user_role_updated.run(str(role.id), [str(permission.id)], [])

        user = test_data["users"]["regular"]
        user_permission_repository = UserPermissionRepository(main_session)
        user_permissions = await user_permission_repository.list(
            user_permission_repository.get_by_user_statement(user.id)
        )
        assert len(user_permissions) == 3
        assert permission.id in [
            user_permission.permission_id for user_permission in user_permissions
        ]

    async def test_role_created_deleted_permission(
        self,
        main_session_manager,
        test_data: TestData,
        main_session: AsyncSession,
    ):
        on_user_role_updated = OnRoleUpdated(main_session_manager)

        role = test_data["roles"]["castles_visitor"]
        permission = test_data["permissions"]["castles:read"]
        await on_user_role_updated.run(str(role.id), [], [str(permission.id)])

        user = test_data["users"]["regular"]
        user_permission_repository = UserPermissionRepository(main_session)
        user_permissions = await user_permission_repository.list(
            user_permission_repository.get_by_user_statement(user.id)
        )
        assert len(user_permissions) == 1
        assert permission.id not in [
            user_permission.permission_id for user_permission in user_permissions
        ]

    async def test_added_permissions_large_batch_of_users(
        self,
        main_session_manager,
        test_data: TestData,
        main_session: AsyncSession,
    ):
        on_role_updated = OnRoleUpdated(main_session_manager)
        on_role_updated.user_chunk_size = 50
        on_role_updated.permission_chunk_size = 1

        role = test_data["roles"]["castles_visitor"]
        tenant = test_data["tenants"]["default"]
        users = await create_users_with_role(main_session, tenant, role, 250)

        added_permissions = [
            test_data["permissions"]["castles:create"],
            test_data["permissions"]["castles:update"],
        ]
        await on_role_updated.run(
            str(role.id), [str(permission.id) for permission in added_permissions], []
        )

        # "regular" user also has this role
        expected_count = len(users) + 1
        for permission in added_permissions:
            assert (
                await count_user_permissions(main_session, role, permission.id)
                == expected_count
            )

        user_permission_repository = UserPermissionRepository(main_session)
        for user in users[:10]:
            user_permissions = await user_permission_repository.list(
                user_permission_repository.get_by_user_statement(user.id)
            )
            permission_ids = {
                user_permission.permission_id for user_permission in user_permissions
            }
            for permission in added_permissions:
                assert permission.id in permission_ids

    async def test_repeated_execution_is_idempotent(
        self,
        main_session_manager,
        test_data: TestData,
        main_session: AsyncSession,
    ):
        on_role_updated = OnRoleUpdated(main_session_manager)
        on_role_updated.user_chunk_size = 10

        role = test_data["roles"]["castles_visitor"]
        tenant = test_data["tenants"]["default"]
        users = await create_users_with_role(main_session, tenant, role, 25)

        added_permission = test_data["permissions"]["castles:create"]
        deleted_permission = test_data["permissions"]["castles:read"]

        for _ in range(3):
            await on_role_updated.run(
                str(role.id),
                [str(added_permission.id)],
                [str(deleted_permission.id)],
            )

        # No duplicate UserPermission rows after repeated runs
        assert (
            await count_user_permissions(main_session, role, added_permission.id)
            == len(users) + 1
        )
        assert (
            await count_user_permissions(main_session, role, deleted_permission.id) == 0
        )

        user = test_data["users"]["regular"]
        user_permission_repository = UserPermissionRepository(main_session)
        user_permissions = await user_permission_repository.list(
            user_permission_repository.get_by_user_statement(user.id)
        )
        assert len(user_permissions) == 2
        assert {
            user_permission.permission_id for user_permission in user_permissions
        } == {
            added_permission.id,
            test_data["permissions"]["castles:delete"].id,
        }

    async def test_mixed_added_and_deleted_permissions(
        self,
        main_session_manager,
        test_data: TestData,
        main_session: AsyncSession,
    ):
        on_role_updated = OnRoleUpdated(main_session_manager)
        on_role_updated.user_chunk_size = 5
        on_role_updated.permission_chunk_size = 1

        role = test_data["roles"]["castles_visitor"]
        tenant = test_data["tenants"]["default"]
        users = await create_users_with_role(main_session, tenant, role, 12)

        added_permissions = [
            test_data["permissions"]["castles:create"],
            test_data["permissions"]["castles:update"],
        ]
        deleted_permission = test_data["permissions"]["castles:read"]

        await on_role_updated.run(
            str(role.id),
            [str(permission.id) for permission in added_permissions],
            [str(deleted_permission.id)],
        )

        expected_count = len(users) + 1
        for permission in added_permissions:
            assert (
                await count_user_permissions(main_session, role, permission.id)
                == expected_count
            )
        assert (
            await count_user_permissions(main_session, role, deleted_permission.id) == 0
        )

        # Directly-granted permissions are left untouched
        user = test_data["users"]["regular"]
        user_permission_repository = UserPermissionRepository(main_session)
        user_permissions = await user_permission_repository.list(
            user_permission_repository.get_by_user_statement(user.id)
        )
        assert test_data["permissions"]["castles:delete"].id in {
            user_permission.permission_id for user_permission in user_permissions
        }
