from django.db import migrations
from django.db.models import Q


# Anyone holding one of these (directly, via a group, or as a superuser)
# could manage organisations or approve drafts before roles existed, so
# they keep that access as Admins. Everyone else becomes Staff.
ADMIN_LEVEL_CODENAMES = (
    "approve_emaildraft",
    "add_bank",
    "add_branch",
    "add_club",
)


def assign_initial_roles(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Permission = apps.get_model("auth", "Permission")

    # A fresh database has no users yet: nothing to do. The first Admin
    # is created afterwards with the create_first_admin command.
    if not User.objects.exists():
        return

    permissions = Permission.objects.filter(
        content_type__app_label="outreach",
        codename__in=ADMIN_LEVEL_CODENAMES,
    )

    admin_level = (
        Q(is_superuser=True)
        | Q(user_permissions__in=permissions)
        | Q(groups__permissions__in=permissions)
    )

    admin_ids = set(
        User.objects.filter(admin_level).values_list("pk", flat=True)
    )

    User.objects.filter(pk__in=admin_ids).update(role="admin")
    User.objects.exclude(pk__in=admin_ids).update(role="staff")


def noop(apps, schema_editor):
    # Roles are additive data on a new column; reversing the schema
    # migration drops the column, so there is nothing to undo here.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_admin_roles_and_archiving"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(assign_initial_roles, noop),
    ]
