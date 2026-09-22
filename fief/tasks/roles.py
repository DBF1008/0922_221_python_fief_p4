import uuid

import dramatiq

from fief.models import Role
from fief.repositories import (
    RoleRepository,
    UserPermissionRepository,
    UserRoleRepository,
)
from fief.tasks.base import ObjectDoesNotExistTaskError, TaskBase


class OnRoleUpdated(TaskBase):
    __name__ = "on_role_updated"
    user_batch_size = 100
    max_user_permissions_per_batch = 5_000
    insert_batch_size = 500

    async def run(
        self,
        role_id: str,
        added_permissions: list[str],
        deleted_permissions: list[str],
        *,
        after_user_role_id: str | None = None,
        continuation: bool = False,
        desired_permissions: list[str] | None = None,
        role_updated_at: str | None = None,
    ):
        async with self.get_main_session() as session:
            role_repository = RoleRepository(session)
            user_role_repository = UserRoleRepository(session)
            user_permission_repository = UserPermissionRepository(session)

            role = await role_repository.get_by_id(uuid.UUID(role_id))

            if role is None:
                raise ObjectDoesNotExistTaskError(Role, role_id)

            if role_updated_at is not None and str(role.updated_at) != role_updated_at:
                return

            if continuation:
                permission_ids = [
                    uuid.UUID(permission_id)
                    for permission_id in (desired_permissions or [])
                ]
                current_role_updated_at = role_updated_at
            else:
                if not added_permissions and not deleted_permissions:
                    return
                permission_id_set = {permission.id for permission in role.permissions}
                permission_id_set.update(
                    uuid.UUID(permission_id) for permission_id in added_permissions
                )
                permission_id_set.difference_update(
                    uuid.UUID(permission_id) for permission_id in deleted_permissions
                )
                permission_ids = list(permission_id_set)
                role_updated_at = str(role.updated_at)
                current_role_updated_at = role_updated_at

            permission_count = max(1, len(permission_ids))
            batch_size = min(
                self.user_batch_size,
                max(1, self.max_user_permissions_per_batch // permission_count),
            )
            cursor = (
                uuid.UUID(after_user_role_id)
                if after_user_role_id is not None
                else None
            )
            user_roles = await user_role_repository.get_role_users_batch(
                role.id,
                limit=batch_size + 1,
                after_id=cursor,
            )
            has_more = len(user_roles) > batch_size
            user_roles = user_roles[:batch_size]

            if user_roles:
                await user_permission_repository.reconcile_role_permissions_for_users(
                    role.id,
                    permission_ids,
                    [user_role[1] for user_role in user_roles],
                    insert_batch_size=self.insert_batch_size,
                )

            if has_more:
                next_user_role_id = user_roles[-1][0]
                self.send_task(
                    on_role_updated,
                    role_id,
                    [],
                    [],
                    after_user_role_id=str(next_user_role_id),
                    continuation=True,
                    desired_permissions=[
                        str(permission_id) for permission_id in permission_ids
                    ],
                    role_updated_at=current_role_updated_at,
                )


on_role_updated = dramatiq.actor(OnRoleUpdated())
