import uuid
from collections.abc import Iterator

import dramatiq

from fief.models import Role, UserPermission
from fief.repositories import (
    RoleRepository,
    UserPermissionRepository,
    UserRoleRepository,
)
from fief.tasks.base import ObjectDoesNotExistTaskError, TaskBase


class OnRoleUpdated(TaskBase):
    __name__ = "on_role_updated"

    user_chunk_size = 1000
    permission_chunk_size = 100

    async def run(
        self, role_id: str, added_permissions: list[str], deleted_permissions: list[str]
    ):
        role_uuid = uuid.UUID(role_id)

        async with self.get_main_session() as session:
            role_repository = RoleRepository(session)
            role = await role_repository.get_by_id(role_uuid)
            if role is None:
                raise ObjectDoesNotExistTaskError(Role, role_id)

        added_permission_ids = sorted({uuid.UUID(p) for p in added_permissions})
        deleted_permission_ids = sorted({uuid.UUID(p) for p in deleted_permissions})

        if added_permission_ids:
            await self._add_permissions(role_uuid, added_permission_ids)
        if deleted_permission_ids:
            await self._delete_permissions(role_uuid, deleted_permission_ids)

    async def _add_permissions(
        self, role_id: uuid.UUID, permission_ids: list[uuid.UUID]
    ) -> None:
        # Process users chunk by chunk, committing each chunk separately,
        # so a failure midway can be safely resumed by re-running the task.
        # Inserts ignore conflicts on the (user_id, permission_id, from_role_id)
        # unique constraint, making the whole operation idempotent.
        offset = 0
        while True:
            async with self.get_main_session() as session:
                user_role_repository = UserRoleRepository(session)
                user_ids = await user_role_repository.get_user_ids_by_role(
                    role_id, limit=self.user_chunk_size, offset=offset
                )
                if not user_ids:
                    break

                user_permission_repository = UserPermissionRepository(session)
                for permission_ids_chunk in self._chunks(
                    permission_ids, self.permission_chunk_size
                ):
                    user_permissions = [
                        UserPermission(
                            user_id=user_id,
                            permission_id=permission_id,
                            from_role_id=role_id,
                        )
                        for user_id in user_ids
                        for permission_id in permission_ids_chunk
                    ]
                    await user_permission_repository.create_many_ignore_conflicts(
                        user_permissions
                    )

            offset += self.user_chunk_size

    async def _delete_permissions(
        self, role_id: uuid.UUID, permission_ids: list[uuid.UUID]
    ) -> None:
        for permission_ids_chunk in self._chunks(
            permission_ids, self.permission_chunk_size
        ):
            async with self.get_main_session() as session:
                user_permission_repository = UserPermissionRepository(session)
                await user_permission_repository.delete_by_permissions_and_role(
                    permission_ids_chunk, role_id
                )

    @staticmethod
    def _chunks(items: list[uuid.UUID], size: int) -> Iterator[list[uuid.UUID]]:
        for i in range(0, len(items), size):
            yield items[i : i + size]


on_role_updated = dramatiq.actor(OnRoleUpdated())
