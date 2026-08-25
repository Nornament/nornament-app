from django.contrib.auth.models import AbstractUser, Group
from django.db import models

from .capabilities import ALL


class Capability(models.Model):
    """Permission holder only — it owns no rows and creates no table.

    Django needs a model to hang custom permissions off. This one exists for
    that and nothing else, which keeps the capability names out of any table's
    own permission list where they would read as "cost of a Piece".
    """

    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ("view_sale", "Can see sale prices"),
            ("view_cost", "Can see cost prices"),
            ("view_vendor", "Can see vendors"),
            ("manage_materials", "Can see the material breakup"),
            ("view_margin", "Can see margins"),
            ("adjust_stock", "Can adjust stock"),
            ("melt", "Can melt a piece"),
            ("edit_bom", "Can edit a bill of materials"),
        ]


class User(AbstractUser):
    """The Supabase ``app.app_user`` row and its GoTrue login, as one user.

    ``legacy_auth_uid`` is the GoTrue ``auth.users.id``; ``legacy_user_id`` is
    ``app.app_user.user_id``. Both are kept so the ETL is re-runnable and so an
    imported row can always be traced back.
    """

    full_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    must_change_password = models.BooleanField(
        default=True,
        help_text="Forces a password change on the next request. Set for imported logins that came in with no usable hash.",
    )
    legacy_auth_uid = models.UUIDField(null=True, blank=True, unique=True)
    legacy_user_id = models.IntegerField(null=True, blank=True, unique=True)
    home_location = models.ForeignKey(
        "stock.Location",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="home_users",
        help_text="Empty means every location is visible — the rule app.visible_locations() applied.",
    )
    locations = models.ManyToManyField(
        "stock.Location", blank=True, related_name="users", help_text="Extra locations this user may see."
    )

    class Meta(AbstractUser.Meta):
        swappable = "AUTH_USER_MODEL"

    def __str__(self):
        return self.full_name or self.username

    # ── location scoping ─────────────────────────────────────────────────
    def visible_location_ids(self):
        """``app.visible_locations()``: no home location means all of them."""
        from stock.models import Location

        if self.is_superuser or self.home_location_id is None:
            return list(Location.objects.values_list("pk", flat=True))
        ids = {self.home_location_id}
        ids.update(self.locations.values_list("pk", flat=True))
        return sorted(ids)

    def can_see_location(self, location_id):
        if location_id is None:
            return True
        return location_id in set(self.visible_location_ids())

    # ── capabilities ─────────────────────────────────────────────────────
    @property
    def capabilities(self):
        return {perm.split(".", 1)[1]: self.has_perm(perm) for perm in ALL}

    def is_privileged(self):
        """``app.is_privileged()`` — may write stock, BOMs and counts."""
        from .capabilities import EDIT_BOM

        return self.has_perm(EDIT_BOM)

    def is_admin(self):
        """``app.is_admin()`` — the ``role.is_system`` flag, as a group."""
        return self.is_superuser or self.groups.filter(name="ADMIN").exists()


def sync_role_groups():
    """Create the five role groups and give each its capabilities.

    Idempotent: run from a data migration, from ``load_legacy`` and from tests.
    """
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    from .capabilities import ROLE_GROUPS

    content_type, _ = ContentType.objects.get_or_create(app_label="accounts", model="capability")
    by_codename = {}
    for codename, label in Capability._meta.permissions:
        permission, _ = Permission.objects.get_or_create(
            codename=codename, content_type=content_type, defaults={"name": label}
        )
        by_codename[codename] = permission

    for code, spec in ROLE_GROUPS.items():
        group, _ = Group.objects.get_or_create(name=code)
        group.permissions.set([by_codename[cap.split(".", 1)[1]] for cap in spec["caps"]])
    return by_codename
