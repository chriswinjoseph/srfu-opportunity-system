from django.db import migrations


def migrate_workflow_statuses_forward(apps, schema_editor):
    EmailDraft = apps.get_model("outreach", "EmailDraft")

    EmailDraft.objects.filter(
        workflow_status="needs_approving"
    ).update(
        workflow_status="awaiting_approval"
    )

    EmailDraft.objects.filter(
        workflow_status="rejected"
    ).update(
        workflow_status="changes_requested"
    )


def migrate_workflow_statuses_backward(apps, schema_editor):
    EmailDraft = apps.get_model("outreach", "EmailDraft")

    EmailDraft.objects.filter(
        workflow_status="awaiting_approval"
    ).update(
        workflow_status="needs_approving"
    )

    EmailDraft.objects.filter(
        workflow_status="changes_requested"
    ).update(
        workflow_status="rejected"
    )


class Migration(migrations.Migration):

    dependencies = [
        (
            "outreach",
            "0023_alter_emaildraft_options_emaildraft_approved_at_and_more",
        ),
    ]

    operations = [
        migrations.RunPython(
            migrate_workflow_statuses_forward,
            migrate_workflow_statuses_backward,
        ),
    ]