from django.contrib.auth.models import AbstractUser, Group
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.functional import cached_property

from .capabilities import ALL, ROLE_GROUPS, ROLE_TABS, SCREEN_CODES

#: the role that holds every right and cannot be edited, so nobody can take
#: the last way back into Users & Settings away from everyone
ADMIN_ROLE = "ADMIN"


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


class Role(models.Model):
    """A role as people see it: a name and the screens it opens.

    The group behind it holds the capabilities, as Django permissions, so
    ``user.has_perm`` keeps answering every capability question. This row adds
    what a group cannot carry, and what an admin edits from Users & Settings.
    """

    group = models.OneToOneField(Group, on_delete=models.CASCADE, primary_key=True, related_name="role")
    name = models.CharField(max_length=80, unique=True)
    screens = ArrayField(models.CharField(max_length=16), default=list, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def code(self):
        return self.group.name

    @property
    def is_admin(self):
        """Admin / Owner: every screen and right, never edited."""
        return self.group.name == ADMIN_ROLE

    @property
    def is_builtin(self):
        """One of the five the app shipped with — editable, but not deletable."""
        return self.group.name in ROLE_GROUPS


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

    # ── role and screens ─────────────────────────────────────────────────
    @cached_property
    def role(self):
        """This login's role, or ``None``. One role per login, by policy."""
        return Role.objects.select_related("group").filter(group__user=self).first()

    @property
    def role_name(self):
        if self.role:
            return self.role.name
        return "Superuser" if self.is_superuser else "No role"

    @property
    def screens(self):
        """The screens this login may open. No role means none at all."""
        if self.is_superuser or (self.role and self.role.is_admin):
            return SCREEN_CODES
        return tuple(self.role.screens) if self.role else ()

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
        return self.is_superuser or bool(self.role and self.role.is_admin)


def sync_role_groups():
    """Create the role groups and give each its default capabilities — once.

    Rights are editable from the Django admin by a superuser, so a deploy must
    never put back a right someone took away. A group gets its full defaults only when
    it is first created; after that, only a capability that did not exist before
    this run is granted, to the groups that list it by default. For that to work
    a migration that adds a capability runs this before Django's own post-migrate
    step creates the permission row.

    Idempotent: run from data migrations, from ``load_legacy`` and from tests.
    """
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType

    from .capabilities import ROLE_GROUPS

    content_type, _ = ContentType.objects.get_or_create(app_label="accounts", model="capability")
    by_codename, new = {}, set()
    for codename, label in Capability._meta.permissions:
        permission, created = Permission.objects.get_or_create(
            codename=codename, content_type=content_type, defaults={"name": label}
        )
        by_codename[codename] = permission
        if created:
            new.add(codename)

    for code, spec in ROLE_GROUPS.items():
        group, created = Group.objects.get_or_create(name=code)
        defaults = [by_codename[cap.split(".", 1)[1]] for cap in spec["caps"]]
        if created:
            group.permissions.set(defaults)
        else:
            group.permissions.add(*[p for p in defaults if p.codename in new])
    return by_codename


def sync_roles():
    """:func:`sync_role_groups`, then a :class:`Role` for every group without one.

    Kept apart from ``sync_role_groups`` because the migrations that call that
    run before the role table exists. A built-in role starts with its seeded
    screens; any other group (one made in the Django admin) starts with none.
    """
    sync_role_groups()
    for group in Group.objects.filter(role__isnull=True):
        spec = ROLE_GROUPS.get(group.name)
        Role.objects.create(
            group=group,
            name=spec["name"] if spec else group.name.title(),
            screens=list(ROLE_TABS.get(group.name, ())),
        )
