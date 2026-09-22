from collections.abc import Sequence

from pydantic import UUID4
from sqlalchemy import delete, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import Insert, Select

from fief.models import UserPermission
from fief.repositories.base import BaseRepository, UUIDRepositoryMixin


class UnsupportedDialectError(RuntimeError):
    def __init__(self, dialect_name: str) -> None:
        super().__init__(
            f"Unsupported database dialect for conflict-free insert: {dialect_name}"
        )


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

    async def delete_by_permissions_and_role(
        self, permissions: Sequence[UUID4], from_role: UUID4
    ) -> None:
        statement = delete(UserPermission).where(
            UserPermission.permission_id.in_(permissions),
            UserPermission.from_role_id == from_role,
        )
        await self._execute_statement(statement)

    async def create_many_ignore_conflicts(
        self, user_permissions: Sequence[UserPermission]
    ) -> None:
        if len(user_permissions) == 0:
            return

        values = [
            {
                "user_id": user_permission.user_id,
                "permission_id": user_permission.permission_id,
                "from_role_id": user_permission.from_role_id,
            }
            for user_permission in user_permissions
        ]
        statement = self._get_insert_ignore_conflicts_statement()
        await self.session.execute(statement, values)
        await self.session.commit()

    def _get_insert_ignore_conflicts_statement(self) -> Insert:
        dialect_name = self.session.get_bind().dialect.name
        if dialect_name == "postgresql":
            return postgresql_insert(UserPermission).on_conflict_do_nothing()
        elif dialect_name == "mysql":
            return mysql_insert(UserPermission).prefix_with("IGNORE")
        elif dialect_name == "sqlite":
            return sqlite_insert(UserPermission).on_conflict_do_nothing()
        raise UnsupportedDialectError(dialect_name)

    async def delete_by_role(self, from_role: UUID4) -> None:
        statement = delete(UserPermission).where(
            UserPermission.from_role_id == from_role
        )
        await self._execute_statement(statement)
