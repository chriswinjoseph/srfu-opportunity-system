import uuid
from datetime import timedelta


from django.conf import settings

from django.db import models, transaction
from django.db.models import F
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from django.contrib.contenttypes.fields import (
    GenericForeignKey,
    GenericRelation,
)

from django.contrib.contenttypes.models import ContentType


# Whether direct outreach has occurred for an organisation.

ORGANISATION_CONTACT_STATUS_CHOICES = [
    ("not_yet_contacted", "Not Yet Contacted"),
    ("contacted", "Contacted"),
]


# The result or current stage of an outreach opportunity.

OPPORTUNITY_STATUS_CHOICES = [
    ("not_yet_contacted", "Not Yet Contacted"),
    ("contacted", "Contacted"),
    ("interested", "Interested"),
    ("not_interested", "Not Interested"),
    ("do_not_contact", "Do Not Contact"),
]


class Bank(models.Model):
    organisation_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_banks",
    )

    record_source = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    duplicate_override_reason = models.TextField(
        blank=True,
        default="",
    )

    duplicate_override_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    duplicate_override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bank_duplicate_overrides",
    )
    duplicate_override_match = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    bank_name = models.CharField(
        max_length=255,
    )

    website_url = models.URLField(
        blank=True,
    )

    address = models.CharField(
        max_length=255,
        blank=True,
    )

    region = models.CharField(
        max_length=100,
    )

    suburb = models.CharField(
        max_length=100,
        blank=True,
    )

    state = models.CharField(
        max_length=50,
        blank=True,
    )

    postcode = models.CharField(
        max_length=10,
        blank=True,
    )

    contact_status = models.CharField(
        max_length=20,
        choices=ORGANISATION_CONTACT_STATUS_CHOICES,
        default="not_yet_contacted",
    )

    public_email = models.EmailField(
        blank=True,
    )

    public_phone = models.CharField(
        max_length=30,
        blank=True,
    )

    source_url = models.URLField(
        blank=True,
    )

    date_added = models.DateTimeField(
        auto_now_add=True,
    )

    last_updated = models.DateTimeField(
        auto_now=True,
    )

    contacts = GenericRelation(
        "Contact",
        related_query_name="bank",
    )

    opportunities = GenericRelation(
        "Opportunity",
        related_query_name="bank",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    contact_status__in=(
                        "not_yet_contacted",
                        "contacted",
                    )
                ),
                name="bank_valid_contact_status",
            ),
        ]

    def __str__(self):

        return self.bank_name


class Branch(models.Model):
    organisation_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_branches",
    )

    record_source = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    duplicate_override_reason = models.TextField(
        blank=True,
        default="",
    )

    duplicate_override_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    duplicate_override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="branch_duplicate_overrides",
    )

    duplicate_override_match = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    date_added = models.DateTimeField(
        auto_now_add=True,
        null=True,
    )

    bank = models.ForeignKey(
        Bank,
        on_delete=models.CASCADE,
        related_name="branches",
    )

    branch_name = models.CharField(
        max_length=255,
    )

    address = models.CharField(
        max_length=255,
        blank=True,
    )

    suburb = models.CharField(
        max_length=100,
        blank=True,
    )

    state = models.CharField(
        max_length=50,
        blank=True,
    )

    postcode = models.CharField(
        max_length=10,
        blank=True,
    )

    region = models.CharField(
        max_length=100,
        blank=True,
    )

    public_email = models.EmailField(
        blank=True,
    )

    public_phone = models.CharField(
        max_length=30,
        blank=True,
    )

    website_url = models.URLField(
        blank=True,
    )

    contact_status = models.CharField(
        max_length=20,
        choices=ORGANISATION_CONTACT_STATUS_CHOICES,
        default="not_yet_contacted",
    )

    contacts = GenericRelation(
        "Contact",
        related_query_name="branch",
    )

    opportunities = GenericRelation(
        "Opportunity",
        related_query_name="branch",
    )

    class Meta:
        verbose_name_plural = "branches"

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    contact_status__in=(
                        "not_yet_contacted",
                        "contacted",
                    )
                ),
                name="branch_valid_contact_status",
            ),
        ]

    def __str__(self):

        return f"{self.branch_name} ({self.bank.bank_name})"


class Club(models.Model):
    organisation_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_clubs",
    )

    record_source = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )
    duplicate_override_reason = models.TextField(
        blank=True,
        default="",
    )

    duplicate_override_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    duplicate_override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="club_duplicate_overrides",
    )

    duplicate_override_match = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    date_added = models.DateTimeField(
        auto_now_add=True,
        null=True,
    )

    club_name = models.CharField(
        max_length=255,
    )

    club_type = models.CharField(
        max_length=100,
        blank=True,
    )

    address = models.CharField(
        max_length=255,
        blank=True,
    )

    suburb = models.CharField(
        max_length=100,
        blank=True,
    )

    state = models.CharField(
        max_length=50,
        blank=True,
    )

    region = models.CharField(
        max_length=100,
        blank=True,
    )

    postcode = models.CharField(
        max_length=10,
        blank=True,
    )

    website_url = models.URLField(
        blank=True,
    )

    public_email = models.EmailField(
        blank=True,
    )

    public_phone = models.CharField(
        max_length=30,
        blank=True,
    )

    supported_by_bank = models.ForeignKey(
        Bank,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supported_clubs",
    )

    supported_by_branch = models.ForeignKey(
        Branch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supported_clubs",
    )

    contact_status = models.CharField(
        max_length=20,
        choices=ORGANISATION_CONTACT_STATUS_CHOICES,
        default="not_yet_contacted",
    )

    contacts = GenericRelation(
        "Contact",
        related_query_name="club",
    )

    opportunities = GenericRelation(
        "Opportunity",
        related_query_name="club",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    contact_status__in=(
                        "not_yet_contacted",
                        "contacted",
                    )
                ),
                name="club_valid_contact_status",
            ),
        ]

    def __str__(self):

        return self.club_name


class OrganisationCreationLock(models.Model):
    """
    Single-row-per-key lock used to serialise manual organisation
    creation, so the in-transaction duplicate re-check cannot race
    with another submission (double click / two users).
    """

    key = models.CharField(
        max_length=50,
        unique=True,
    )

    counter = models.PositiveIntegerField(
        default=0,
    )


# Contact and Opportunity can link to a Bank, Branch or Club.

ORGANISATION_MODELS = (
    models.Q(
        app_label="outreach",
        model="bank",
    )
    | models.Q(
        app_label="outreach",
        model="branch",
    )
    | models.Q(
        app_label="outreach",
        model="club",
    )
)


class Contact(models.Model):
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        limit_choices_to=ORGANISATION_MODELS,
    )

    object_id = models.PositiveIntegerField()

    organisation = GenericForeignKey(
        "content_type",
        "object_id",
    )

    contact_name = models.CharField(
        max_length=255,
        blank=True,
    )

    role = models.CharField(
        max_length=100,
        blank=True,
    )

    email = models.EmailField(
        blank=True,
    )

    phone = models.CharField(
        max_length=30,
        blank=True,
    )

    source_url = models.URLField(
        blank=True,
    )

    last_verified = models.DateField(
        null=True,
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(
                fields=[
                    "content_type",
                    "object_id",
                ],
            ),
        ]

    def __str__(self):

        name = self.contact_name or "Unnamed contact"

        return f"{name} @ {self.organisation}"


class Opportunity(models.Model):
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        limit_choices_to=ORGANISATION_MODELS,
    )

    object_id = models.PositiveIntegerField()

    organisation = GenericForeignKey(
        "content_type",
        "object_id",
    )

    status = models.CharField(
        max_length=20,
        choices=OPPORTUNITY_STATUS_CHOICES,
        default="not_yet_contacted",
    )

    date_created = models.DateTimeField(
        auto_now_add=True,
    )

    date_contacted = models.DateTimeField(
        null=True,
        blank=True,
    )

    outreach_method = models.CharField(
        max_length=50,
        blank=True,
    )

    # Keep this for compatibility with existing code.

    draft_email = models.TextField(
        blank=True,
    )

    approved = models.BooleanField(
        default=False,
    )

    approved_by = models.CharField(
        max_length=255,
        blank=True,
    )

    date_approved = models.DateTimeField(
        null=True,
        blank=True,
    )

    notes = models.TextField(
        blank=True,
    )

    class Meta:
        indexes = [
            models.Index(
                fields=[
                    "content_type",
                    "object_id",
                ],
            ),
        ]

        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=(
                        "not_yet_contacted",
                        "contacted",
                        "interested",
                        "not_interested",
                        "do_not_contact",
                    )
                ),
                name="opportunity_valid_status",
            ),
        ]

        verbose_name_plural = "opportunities"

    def __str__(self):

        return f"Opportunity for {self.organisation} - {self.status}"


# ---------------------------------------------------------
# Approved Email Template
# ---------------------------------------------------------


class EmailTemplate(models.Model):
    name = models.CharField(
        max_length=150,
    )

    version = models.CharField(
        max_length=50,
        default="v1",
    )

    purpose = models.CharField(
        max_length=255,
    )

    template_body = models.TextField()

    sender_name = models.CharField(
        max_length=150,
    )

    sender_role = models.CharField(
        max_length=150,
        blank=True,
    )

    project_details = models.TextField(
        blank=True,
    )

    call_to_action = models.TextField()

    signature = models.TextField()

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return f"{self.name} ({self.version})"


# ---------------------------------------------------------
# AI Email Draft
# ---------------------------------------------------------


class EmailDraft(models.Model):

    WORKFLOW_CHOICES = [
        ("draft", "Draft"),
        ("awaiting_approval", "Awaiting Approval"),
        ("changes_requested", "Changes Requested"),
        ("approved", "Approved"),
        ("sending", "Sending"),
        ("sent", "Sent"),
        ("send_failed", "Send Failed"),
        ("cancelled", "Cancelled"),
    ]

    GENERATION_CHOICES = [
        ("pending", "Pending"),
        ("success", "Success"),
        ("failed", "Failed"),
        ("timed_out", "Timed Out"),
    ]

    draft_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )

    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.CASCADE,
        related_name="email_drafts",
    )

    template = models.ForeignKey(
        EmailTemplate,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="email_drafts",
    )

    recipient_email = models.EmailField(
        blank=True,
    )

    subject = models.CharField(
        max_length=255,
        blank=True,
    )

    body = models.TextField(
        blank=True,
    )

    outreach_purpose = models.CharField(
        max_length=255,
    )

    template_version = models.CharField(
        max_length=50,
        default="v1",
    )

    workflow_status = models.CharField(
        max_length=30,
        choices=WORKFLOW_CHOICES,
        default="draft",
    )

    generation_status = models.CharField(
        max_length=20,
        choices=GENERATION_CHOICES,
        default="pending",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_email_drafts",
    )

    last_edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="edited_email_drafts",
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_email_drafts",
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    approved_version = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_email_drafts",
    )

    sent_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    send_failure_reason = models.TextField(
        blank=True,
    )

    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_email_drafts",
    )

    cancelled_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    cancellation_reason = models.TextField(
        blank=True,
    )

    # Set when the draft enters Awaiting Approval; the overdue
    # threshold is measured from this timestamp.
    submitted_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # True when the draft was submitted while no active user held
    # the approval permission. An administrator must assign one.
    approver_unavailable = models.BooleanField(
        default=False,
    )

    # Set once an overdue approval has been flagged/notified.
    overdue_flagged_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # Durable evidence that the email backend confirmed delivery.
    smtp_confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    # True when the email was sent but the database could not be
    # finalised. Blocks any further send until reconciled.
    reconciliation_required = models.BooleanField(
        default=False,
    )

    trigger_source = models.CharField(
        max_length=20,
        default="manual",
    )

    version = models.PositiveIntegerField(
        default=1,
    )

    regeneration_attempts = models.PositiveIntegerField(
        default=0,
    )

    error_message = models.TextField(
        blank=True,
    )

    is_incomplete = models.BooleanField(
        default=False,
    )

    validation_issues = models.TextField(
        blank=True,
    )

    rejection_reason = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        permissions = [
            (
                "generate_emaildraft",
                "Can generate email draft",
            ),
            (
                "approve_emaildraft",
                "Can approve email draft",
            ),
            (
                "send_emaildraft",
                "Can send email draft",
            ),
        ]

    def approval_overdue_threshold(self):
        return timedelta(
            hours=settings.EMAIL_APPROVAL_OVERDUE_HOURS
        )

    @property
    def is_approval_overdue(self):
        if self.workflow_status != "awaiting_approval":
            return False

        if self.submitted_at is None:
            return False

        return (
            timezone.now() - self.submitted_at
            >= self.approval_overdue_threshold()
        )

    def __str__(self):
        return f"{self.draft_id} - {self.workflow_status}"
    # ---------------------------------------------------------
# AI Email Generation Audit Log
# ---------------------------------------------------------
class EmailDraftHistory(models.Model):
    ACTION_CHOICES = [
        ("created", "Created"),
        ("edited", "Edited"),
        ("submitted", "Submitted for Approval"),
        ("changes_requested", "Changes Requested"),
        ("approved", "Approved"),
        ("approval_invalidated", "Approval Invalidated"),
        ("withdrawn", "Withdrawn for Editing"),
        ("cancelled", "Cancelled"),
        ("send_started", "Send Started"),
        ("sent", "Sent"),
        ("send_failed", "Send Failed"),
        ("no_approver_available", "No Approver Available"),
        ("approval_overdue", "Approval Overdue"),
        ("recipient_changed", "Recipient Email Changed"),
        ("reconciliation_required", "Reconciliation Required"),
        ("blocked_do_not_contact", "Blocked - Do Not Contact"),
    ]

    draft = models.ForeignKey(
        EmailDraft,
        on_delete=models.CASCADE,
        related_name="workflow_history",
    )

    action = models.CharField(
        max_length=30,
        choices=ACTION_CHOICES,
    )

    from_status = models.CharField(
        max_length=30,
        blank=True,
    )

    to_status = models.CharField(
        max_length=30,
        blank=True,
    )

    version = models.PositiveIntegerField(
        default=1,
    )

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_draft_history_actions",
    )

    reason = models.TextField(
        blank=True,
    )

    recipient_email_snapshot = models.EmailField(
        blank=True,
    )

    subject_snapshot = models.CharField(
        max_length=255,
        blank=True,
    )

    body_snapshot = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.draft.draft_id} - "
            f"{self.action} - "
            f"v{self.version}"
        )


class EmailGenerationLog(models.Model):

    STATUS_CHOICES = [
        ("success", "Success"),
        ("failed", "Failed"),
        ("timed_out", "Timed Out"),
    ]

    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
    )

    object_id = models.PositiveIntegerField()

    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generation_logs",
    )

    draft = models.ForeignKey(
        EmailDraft,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="generation_logs",
    )

    template_version = models.CharField(
        max_length=50,
        blank=True,
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="email_generation_logs",
    )

    trigger_source = models.CharField(
        max_length=20,
        default="manual",
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
    )

    attempt_number = models.PositiveIntegerField(
        default=1,
    )

    input_tokens = models.PositiveIntegerField(
        default=0,
    )

    output_tokens = models.PositiveIntegerField(
        default=0,
    )

    total_tokens = models.PositiveIntegerField(
        default=0,
    )

    error_message = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    def __str__(self):
        return (
            f"Email generation {self.status} "
            f"for object {self.object_id}"
        )


# ---------------------------------------------------------
# Recipient email change after approval
#
# If an organisation's public email changes, any draft that
# was awaiting approval, approved, or failed to send can no
# longer be trusted: the approver reviewed a different
# recipient. Return it to Draft, wipe the approval and keep
# the previous version in workflow history.
#
# Note: QuerySet.update()/bulk_update() bypass signals. The
# approve and send views independently re-check the recipient,
# so those paths are still blocked from sending.
# ---------------------------------------------------------

EMAIL_REAPPROVAL_STATUSES = (
    "awaiting_approval",
    "approved",
    "send_failed",
)


@receiver(pre_save, sender=Bank)
@receiver(pre_save, sender=Branch)
@receiver(pre_save, sender=Club)
def remember_previous_public_email(sender, instance, **kwargs):
    instance._previous_public_email = None

    if instance.pk is None:
        return

    instance._previous_public_email = (
        sender.objects
        .filter(pk=instance.pk)
        .values_list("public_email", flat=True)
        .first()
    )


@receiver(post_save, sender=Bank)
@receiver(post_save, sender=Branch)
@receiver(post_save, sender=Club)
def invalidate_drafts_on_recipient_change(
    sender,
    instance,
    created,
    **kwargs,
):
    previous = getattr(instance, "_previous_public_email", None)

    if created or previous is None:
        return

    new_email = (instance.public_email or "").strip().lower()

    if (previous or "").strip().lower() == new_email:
        return

    content_type = ContentType.objects.get_for_model(sender)

    with transaction.atomic():
        candidates = _lock_recipient_candidates(
            content_type,
            instance.pk,
        )

        for draft in candidates:
            if (draft.recipient_email or "").strip().lower() == new_email:
                continue

            old_status = draft.workflow_status

            if old_status == "sending":
                # A send has already been claimed and is in flight to
                # the recipient that was approved. It cannot be recalled
                # or rewritten; record the change for reconciliation.
                EmailDraftHistory.objects.create(
                    draft=draft,
                    action="recipient_changed",
                    from_status="sending",
                    to_status="sending",
                    version=draft.version,
                    reason=(
                        "Organisation recipient email changed to "
                        f"{instance.public_email or '(none)'} while "
                        "this email was already being sent to "
                        f"{draft.recipient_email}. The email goes to "
                        "the approved recipient; verify the outcome."
                    ),
                    recipient_email_snapshot=draft.recipient_email,
                    subject_snapshot=draft.subject,
                    body_snapshot=draft.body,
                )
                continue

            was_approved = draft.approved_version is not None

            # Conditional on the state and version just read under the
            # lock: a stale instance can never overwrite Sending/Sent
            # or a newer version.
            updated = EmailDraft.objects.filter(
                pk=draft.pk,
                workflow_status=old_status,
                version=draft.version,
            ).update(
                workflow_status="draft",
                approved_by=None,
                approved_at=None,
                approved_version=None,
                submitted_at=None,
                approver_unavailable=False,
                overdue_flagged_at=None,
                version=F("version") + 1,
            )

            if updated != 1:
                continue

            # History records the state exactly as it was reviewed.
            EmailDraftHistory.objects.create(
                draft=draft,
                action="recipient_changed",
                from_status=old_status,
                to_status="draft",
                version=draft.version,
                reason=(
                    "Organisation recipient email changed from "
                    f"{draft.recipient_email or previous} to "
                    f"{instance.public_email or '(none)'}. "
                    + (
                        "The previous approval is no longer valid; "
                        "the draft must be updated and reapproved."
                        if was_approved
                        else "The draft must be updated and "
                        "resubmitted."
                    )
                ),
                recipient_email_snapshot=draft.recipient_email,
                subject_snapshot=draft.subject,
                body_snapshot=draft.body,
            )


def _lock_recipient_candidates(content_type, object_id):
    """
    Take the write lock (effective on SQLite, where select_for_update
    is a no-op) and return a fresh read of the drafts that a recipient
    change may affect. Split out so tests can interleave a competing
    send claim between this read and the conditional update.
    """
    base = EmailDraft.objects.filter(
        opportunity__content_type=content_type,
        opportunity__object_id=object_id,
        workflow_status__in=EMAIL_REAPPROVAL_STATUSES + ("sending",),
    )

    base.update(version=F("version"))

    return list(base.select_for_update())
