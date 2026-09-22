import uuid

import pytest
from sqlalchemy import func, select

from fief.db import AsyncSession
from fief.models import Role, User, UserPermission, UserRole
from fief.repositories import UserPermissionRepository
from fief.tasks.base import TaskError
from fief.tasks.roles import OnRoleUpdated
from tests.data import TestData


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

    async def test_chunked_reconciliation_without_permissions(
        self,
        main_session_manager,
        test_data: TestData,
        main_session: AsyncSession,
    ):
        tenant = test_data["tenants"]["default"]
        read_permission = test_data["permissions"]["castles:read"]
        delete_permission = test_data["permissions"]["castles:delete"]
        role = Role(name=f"Empty Role {uuid.uuid4()}", permissions=[])
        users = [
            User(
                email=f"empty-role-{uuid.uuid4()}@example.com",
                email_lower=f"empty-role-{uuid.uuid4()}@example.com",
                hashed_password="not-secret",
                tenant_id=tenant.id,
            )
            for _ in range(5)
        ]
        user = User(
            email=f"empty-role-{uuid.uuid4()}@example.com",
            email_lower=f"empty-role-{uuid.uuid4()}@example.com",
            hashed_password="not-secret",
            tenant_id=tenant.id,
        )
        main_session.add_all([role, user, *users])
        await main_session.flush()
        main_session.add_all(
            [UserRole(user_id=role_user.id, role_id=role.id) for role_user in users]
        )
        main_session.add_all(
            [
                UserPermission(
                    user_id=role_user.id,
                    permission_id=read_permission.id,
                    from_role_id=role.id,
                )
                for role_user in users
            ]
        )
        main_session.add(
            UserPermission(
                user_id=user.id,
                permission_id=delete_permission.id,
            )
        )
        await main_session.flush()

        sent_tasks: list[tuple[tuple, dict]] = []

        def send_task(task, *args, **kwargs):
            sent_tasks.append((args, kwargs))

        task = OnRoleUpdated(main_session_manager, send_task=send_task)
        task.user_batch_size = 2
        await task.run(str(role.id), [], [str(read_permission.id)])

        index = 0
        while index < len(sent_tasks):
            args, kwargs = sent_tasks[index]
            await task.run(*args, **kwargs)
            index += 1

        assert len(sent_tasks) == 2
        role_permission_ids = await main_session.scalars(
            select(UserPermission.permission_id).where(
                UserPermission.user_id.in_([role_user.id for role_user in users]),
                UserPermission.from_role_id == role.id,
            )
        )
        assert role_permission_ids.all() == []

        direct_permission_ids = await main_session.scalars(
            select(UserPermission.permission_id).where(
                UserPermission.user_id == user.id,
                UserPermission.from_role_id.is_(None),
            )
        )
        assert direct_permission_ids.all() == [delete_permission.id]

    async def test_chunked_reconciliation_with_mixed_permissions(
        self,
        main_session_manager,
        test_data: TestData,
        main_session: AsyncSession,
    ):
        tenant = test_data["tenants"]["default"]
        read_permission = test_data["permissions"]["castles:read"]
        create_permission = test_data["permissions"]["castles:create"]
        update_permission = test_data["permissions"]["castles:update"]
        delete_permission = test_data["permissions"]["castles:delete"]

        role = Role(
            name=f"Batch Role {uuid.uuid4()}",
            permissions=[read_permission, delete_permission],
        )
        main_session.add(role)
        users = [
            User(
                email=f"batch-{uuid.uuid4()}@example.com",
                email_lower=f"batch-{index}@example.com",
                hashed_password="not-secret",
                tenant_id=tenant.id,
            )
            for index in range(25)
        ]
        main_session.add_all(users)
        await main_session.flush()

        main_session.add_all(
            [UserRole(user_id=user.id, role_id=role.id) for user in users]
        )
        main_session.add_all(
            [
                UserPermission(
                    user_id=users[0].id,
                    permission_id=delete_permission.id,
                    from_role_id=role.id,
                ),
                UserPermission(
                    user_id=users[0].id,
                    permission_id=delete_permission.id,
                ),
            ]
        )
        await main_session.flush()

        sent_tasks: list[tuple[tuple, dict]] = []

        def send_task(task, *args, **kwargs):
            sent_tasks.append((args, kwargs))

        task = OnRoleUpdated(main_session_manager, send_task=send_task)
        task.user_batch_size = 4
        task.insert_batch_size = 4
        write_statements = []
        original_execute_statement = UserPermissionRepository._execute_statement

        async def count_execute_statement(self, statement):
            write_statements.append(statement)
            return await original_execute_statement(self, statement)

        UserPermissionRepository._execute_statement = count_execute_statement
        run_arguments = (
            str(role.id),
            [str(create_permission.id), str(update_permission.id)],
            [str(delete_permission.id)],
        )

        try:
            await task.run(*run_arguments)

            index = 0
            while index < len(sent_tasks):
                args, kwargs = sent_tasks[index]
                await task.run(*args, **kwargs)
                index += 1
        finally:
            UserPermissionRepository._execute_statement = original_execute_statement

        assert len(sent_tasks) == 6
        assert len(write_statements) == 19

        grouped_result = await main_session.execute(
            select(
                UserPermission.user_id,
                UserPermission.permission_id,
                func.count(),
            )
            .where(UserPermission.from_role_id == role.id)
            .group_by(UserPermission.user_id, UserPermission.permission_id)
        )
        assert len(grouped_result.all()) == 75

        for user in users:
            permission_ids = await main_session.scalars(
                select(UserPermission.permission_id).where(
                    UserPermission.user_id == user.id,
                    UserPermission.from_role_id == role.id,
                )
            )
            assert set(permission_ids) == {
                read_permission.id,
                create_permission.id,
                update_permission.id,
            }

        direct_permission_ids = await main_session.scalars(
            select(UserPermission.permission_id).where(
                UserPermission.user_id == users[0].id,
                UserPermission.from_role_id.is_(None),
                UserPermission.permission_id == delete_permission.id,
            )
        )
        assert direct_permission_ids.all() == [delete_permission.id]

        async def assert_no_execute_statement(self, statement):
            pytest.fail("Repeated role update should not execute writes")

        UserPermissionRepository._execute_statement = assert_no_execute_statement
        try:
            await task.run(*run_arguments)
        finally:
            UserPermissionRepository._execute_statement = original_execute_statement

    async def test_stale_continuation_does_not_roll_back_permissions(
        self,
        main_session_manager,
        test_data: TestData,
        main_session: AsyncSession,
    ):
        read_permission = test_data["permissions"]["castles:read"]
        create_permission = test_data["permissions"]["castles:create"]
        role = Role(
            name=f"Stale Role {uuid.uuid4()}",
            permissions=[read_permission],
        )
        main_session.add(role)
        await main_session.flush()

        sent_tasks: list[tuple[tuple, dict]] = []

        def send_task(task, *args, **kwargs):
            sent_tasks.append((args, kwargs))

        task = OnRoleUpdated(main_session_manager, send_task=send_task)
        original_execute_statement = UserPermissionRepository._execute_statement

        async def assert_no_execute_statement(self, statement):
            pytest.fail("Stale continuation should not write permissions")

        UserPermissionRepository._execute_statement = assert_no_execute_statement
        try:
            await task.run(
                str(role.id),
                [],
                [],
                continuation=True,
                desired_permissions=[
                    str(read_permission.id),
                    str(create_permission.id),
                ],
                role_updated_at="2000-01-01T00:00:00+00:00",
            )
        finally:
            UserPermissionRepository._execute_statement = original_execute_statement

        assert sent_tasks == []
