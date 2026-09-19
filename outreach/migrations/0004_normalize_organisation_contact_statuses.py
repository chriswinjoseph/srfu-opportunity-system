from django.db import migrations


OUTCOME_STATUSES = (
    "interested",
    "not_interested",
    "do_not_contact",
)


def normalize_organisation_statuses(apps, schema_editor):
    """
    Preserve organisation outcomes in Opportunity and normalise the
    organisation contact status to Contacted.
    """
    ContentType = apps.get_model(
        "contenttypes",
        "ContentType",
    )
    Opportunity = apps.get_model(
        "outreach",
        "Opportunity",
    )

    organisation_models = (
        (
            "bank",
            apps.get_model("outreach", "Bank"),
        ),
        (
            "branch",
            apps.get_model("outreach", "Branch"),
        ),
        (
            "club",
            apps.get_model("outreach", "Club"),
        ),
    )

    for model_name, organisation_model in organisation_models:
        organisations = organisation_model.objects.filter(
            contact_status__in=OUTCOME_STATUSES,
        )

        # A fresh test database has no existing records to normalise.
        if not organisations.exists():
            continue

        content_type, _ = ContentType.objects.get_or_create(
            app_label="outreach",
            model=model_name,
        )

        for organisation in organisations:
            old_status = organisation.contact_status

            Opportunity.objects.get_or_create(
                content_type_id=content_type.pk,
                object_id=organisation.pk,
                status=old_status,
                defaults={
                    "notes": (
                        "Outcome preserved while normalising the "
                        "organisation contact status."
                    ),
                },
            )

            organisation.contact_status = "contacted"
            organisation.save(
                update_fields=["contact_status"],
            )


class Migration(migrations.Migration):

    dependencies = [
        (
            "outreach",
            "0003_club_supported_by_branch",
        ),
    ]

    operations = [
        migrations.RunPython(
            normalize_organisation_statuses,
            migrations.RunPython.noop,
        ),
    ]