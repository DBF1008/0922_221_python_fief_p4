import uuid
from collections.abc import Sequence

from pydantic import UUID4
from sqlalchemy import delete, insert, select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import Select

from fief.models import UserPermission
from fief.repositories.base import BaseRepository, UUIDRepositoryMixin


class UserPermissionRepository(
    BaseRepository[UserPermission], UUIDRepositoryMixin[UserPermission]
):
    model = UserPermission

    def get_by_user_statement(
        self, user: UUID4, *, direct_only: bool = False
    ) -> Select:
        statement = (
            select(UserPermission)
            .where(UserPermission.user_id == user)
            .options(
                joinedload(UserPermission.permission),
                joinedload(UserPermission.from_role),
            )
        )

        if direct_only:
            statement = statement.where(UserPermission.from_role == None)

        return statement

    async def get_by_permission_and_user(
        self, user: UUID4, permission: UUID4, *, direct_only: bool = False
    ) -> UserPermission | None:
        statement = (
            select(UserPermission)
            .where(
                UserPermission.user_id == user,
                UserPermission.permission_id == permission,
            )
            .options(
                joinedload(UserPermission.permission),
                joinedload(UserPermission.from_role),
            )
        )

        if direct_only:
            statement = statement.where(UserPermission.from_role == None)

        return await self.get_one_or_none(statement)

    async def delete_by_user_and_role(self, user: UUID4, from_role: UUID4) -> None:
        statement = delete(UserPermission).where(
            UserPermission.user_id == user, UserPermission.from_role_id == from_role
        )
        await self._execute_statement(statement)

    async def delete_by_permission_and_role(
        self, permission: UUID4, from_role: UUID4
    ) -> None:
        statement = delete(UserPermission).where(
            UserPermission.permission_id == permission,
            UserPermission.from_role_id == from_role,
        )
        await self._execute_statement(statement)

    async def delete_by_role(self, from_role: UUID4) -> None:
        statement = delete(UserPermission).where(
            UserPermission.from_role_id == from_role
        )
        await self._execute_statement(statement)

    async def reconcile_role_permissions_for_users(
        self,
        role: UUID4,
        permission_ids: Sequence[UUID4],
        user_ids: Sequence[UUID4],
        *,
        insert_batch_size: int = 1_000,
    ) -> None:
        if not user_ids:
            return

        result = await self._execute_query(
            select(UserPermission.user_id, UserPermission.permission_id).where(
                UserPermission.from_role_id == role,
                UserPermission.user_id.in_(user_ids),
            )
        )
        existing_permissions = {
            (row.user_id, row.permission_id) for row in result.all()
        }
        desired_permissions = {
            (user_id, permission_id)
            for user_id in user_ids
            for permission_id in permission_ids
        }
        stale_permissions = existing_permissions - desired_permissions

        if stale_permissions:
            delete_statement = delete(UserPermission).where(
                UserPermission.from_role_id == role,
                UserPermission.user_id.in_(user_ids),
            )

            if not permission_ids:
                await self._execute_statement(delete_statement)
            else:
                delete_statement = delete_statement.where(
                    UserPermission.permission_id.not_in(permission_ids)
                )
                await self._execute_statement(delete_statement)

        missing_permissions = desired_permissions - existing_permissions

        missing_permission_list = list(missing_permissions)
        if missing_permission_list:
            for start in range(0, len(missing_permission_list), insert_batch_size):
                batch = missing_permission_list[start : start + insert_batch_size]
                values = [
                    {
                        "id": uuid.uuid4(),
                        "user_id": user_id,
                        "permission_id": permission_id,
                        "from_role_id": role,
                    }
                    for user_id, permission_id in batch
                ]
                insert_statement = insert(UserPermission).values(values)

                if (
                    self.session.bind is not None
                    and self.session.bind.dialect.name == "mysql"
                ):
                    insert_statement = insert_statement.prefix_with("IGNORE")
                else:
                    insert_statement = insert_statement.on_conflict_do_nothing(
                        index_elements=[
                            UserPermission.user_id,
                            UserPermission.permission_id,
                            UserPermission.from_role_id,
                        ]
                    )

                await self._execute_statement(insert_statement)
