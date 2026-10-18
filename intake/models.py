"""
Data for bulk import, duplicate review and the live scraper.

Source identifiers are scoped to their source (``source_key``) and are kept
separate from the internal organisation UUID. ``Review Required`` is a state
of a run result or a review item; it is never a ``contact_status``.
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

ORGANISATION_MODELS = (
    models.Q(app_label="outreach", model="bank")
    | models.Q(app_label="outreach", model="branch")
    | models.Q(app_label="outreach", model="club")
)


class IntakeRun(models.Model):
    KIND_IMPORT = "import"
    KIND_SCRAPER = "scraper"
    KIND_CHOICES = [
        (KIND_IMPORT, "Excel import"),
        (KIND_SCRAPER, "Live scraper"),
    ]

    STATUS_PREVIEWED = "previewed"
    STATUS_QUEUED = "queued"
    STATUS_RUNNING = "running"
    STATUS_SUCCESSFUL = "successful"
    STATUS_PARTIAL = "partial"
    STATUS_FAILED = "failed"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        (STATUS_PREVIEWED, "Awaiting confirmation"),
        (STATUS_QUEUED, "Queued"),
        (STATUS_RUNNING, "Running"),
        (STATUS_SUCCESSFUL, "Successful"),
        (STATUS_PARTIAL, "Partially Successful"),
        (STATUS_FAILED, "Failed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]
    FINISHED_STATUSES = (
        STATUS_SUCCESSFUL,
        STATUS_PARTIAL,
        STATUS_FAILED,
        STATUS_CANCELLED,
    )

    kind = models.CharField(max_length=10, choices=KIND_CHOICES)
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_PREVIEWED
    )
    source_key = models.CharField(max_length=60, blank=True)
    source_label = models.CharField(max_length=120, blank=True)
    filename = models.CharField(max_length=255, blank=True)
    file_sha256 = models.CharField(max_length=64, blank=True)
    options = models.JSONField(default=dict, blank=True)
    # Parsed workbook groups (import) kept so the preview can be confirmed
    # without keeping the uploaded file.
    payload = models.JSONField(null=True, blank=True)
    totals = models.JSONField(default=dict, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    lease_token = models.CharField(max_length=40, blank=True)
    progress_done = models.PositiveIntegerField(default=0)
    progress_total = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["kind", "status"])]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk} ({self.status})"

    @property
    def is_finished(self):
        return self.status in self.FINISHED_STATUSES


class IntakeResult(models.Model):
    """One processed record, page or structural problem of a run."""

    KIND_ORGANISATION = "organisation"
    KIND_CONTACT = "contact"
    KIND_PAGE = "page"
    KIND_STRUCTURE = "structure"

    OUTCOME_CHOICES = [
        ("created", "Created"),
        ("exact", "Exact duplicate matched"),
        ("updated", "Existing record updated"),
        ("unchanged", "Unchanged"),
        ("review", "Review required"),
        ("incomplete", "Incomplete"),
        ("failed", "Failed"),
        ("rejected", "Rejected"),
    ]

    run = models.ForeignKey(
        IntakeRun, on_delete=models.CASCADE, related_name="results"
    )
    kind = models.CharField(max_length=14, default=KIND_ORGANISATION)
    outcome = models.CharField(max_length=12, choices=OUTCOME_CHOICES)
    row_ref = models.CharField(max_length=300, blank=True)
    source_id = models.CharField(max_length=200, blank=True)
    org_type = models.CharField(max_length=10, blank=True)
    name = models.CharField(max_length=255, blank=True)
    field = models.CharField(max_length=60, blank=True)
    message = models.TextField(blank=True)
    action_required = models.TextField(blank=True)
    target_content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    target_id = models.PositiveIntegerField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["run", "outcome"])]


class DuplicateReview(models.Model):
    """A held record waiting for an Admin decision."""

    KIND_DUPLICATE = "duplicate"
    KIND_EVIDENCE = "evidence"
    KIND_CONTACT = "contact"
    KIND_CHOICES = [
        (KIND_DUPLICATE, "Possible duplicate organisation"),
        (KIND_EVIDENCE, "Conflicting outreach evidence"),
        (KIND_CONTACT, "Shared contact email"),
    ]

    STATUS_PENDING = "pending"
    STATUS_DECIDED = "decided"

    run = models.ForeignKey(
        IntakeRun, on_delete=models.CASCADE, related_name="reviews"
    )
    result = models.OneToOneField(
        IntakeResult, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="review",
    )
    kind = models.CharField(max_length=12, choices=KIND_CHOICES)
    status = models.CharField(max_length=10, default=STATUS_PENDING)
    decision = models.CharField(max_length=24, blank=True)
    source_key = models.CharField(max_length=60, blank=True)
    source_id = models.CharField(max_length=200, blank=True)
    reason = models.TextField(blank=True)
    # The submitted record, and the possible matches with the reasons.
    submission = models.JSONField(default=dict)
    matches = models.JSONField(default=list, blank=True)
    target_content_type = models.ForeignKey(
        ContentType, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    target_id = models.PositiveIntegerField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["status", "source_key", "source_id"])]


class ProposedChange(models.Model):
    """A different (or no-longer-found) value that needs an Admin decision."""

    KIND_CHANGE = "change"
    KIND_REMOVED = "removed"

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_STALE = "stale"

    run = models.ForeignKey(
        IntakeRun, null=True, on_delete=models.SET_NULL, related_name="changes"
    )
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, limit_choices_to=ORGANISATION_MODELS,
        related_name="+",
    )
    object_id = models.PositiveIntegerField()
    organisation = GenericForeignKey("content_type", "object_id")
    field = models.CharField(max_length=60)
    kind = models.CharField(max_length=10, default=KIND_CHANGE)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    source_label = models.CharField(max_length=120, blank=True)
    source_url = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, default=STATUS_PENDING)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["content_type", "object_id", "status"])]


class OrganisationSource(models.Model):
    """
    Where an organisation came from. ``source_org_id`` is the identifier in
    that source and is unique only within ``source_key``.
    """

    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, limit_choices_to=ORGANISATION_MODELS,
        related_name="+",
    )
    object_id = models.PositiveIntegerField()
    organisation = GenericForeignKey("content_type", "object_id")
    source_key = models.CharField(max_length=60)
    source_org_id = models.CharField(max_length=200, blank=True)
    source_url = models.CharField(max_length=500, blank=True)
    source_filename = models.CharField(max_length=255, blank=True)
    first_collected_at = models.DateTimeField()
    last_checked_at = models.DateTimeField()
    last_run = models.ForeignKey(
        IntakeRun, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    collected_fields = models.JSONField(default=list, blank=True)
    requires_verification = models.BooleanField(default=False)
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_key", "source_org_id"],
                condition=~models.Q(source_org_id=""),
                name="intake_unique_source_org_id",
            ),
            models.UniqueConstraint(
                fields=["content_type", "object_id", "source_key"],
                name="intake_unique_org_source",
            ),
        ]
        indexes = [models.Index(fields=["content_type", "object_id"])]


class ContactSource(models.Model):
    contact = models.OneToOneField(
        "outreach.Contact", on_delete=models.CASCADE, related_name="intake_source",
    )
    source_key = models.CharField(max_length=60)
    source_contact_id = models.CharField(max_length=200)
    last_run = models.ForeignKey(
        IntakeRun, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    name_needs_verification = models.BooleanField(null=True)
    affiliation_needs_verification = models.BooleanField(null=True)
    first_observed_at = models.DateTimeField(null=True, blank=True)
    last_observed_at = models.DateTimeField(null=True, blank=True)
    outreach_evidence = models.CharField(max_length=60, blank=True)
    sent_flag = models.BooleanField(null=True)
    human_reply = models.BooleanField(null=True)
    contact_type = models.CharField(max_length=60, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source_key", "source_contact_id"],
                name="intake_unique_source_contact_id",
            ),
        ]


class FieldProvenance(models.Model):
    """Where one organisation field value came from and whether it was verified."""

    ORIGIN_CHOICES = [
        ("import", "Import"),
        ("scraper", "Scraper"),
        ("admin_review", "Approved by an Admin"),
    ]

    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, limit_choices_to=ORGANISATION_MODELS,
        related_name="+",
    )
    object_id = models.PositiveIntegerField()
    field = models.CharField(max_length=60)
    origin = models.CharField(max_length=14, choices=ORIGIN_CHOICES)
    source_key = models.CharField(max_length=60, blank=True)
    source_url = models.CharField(max_length=500, blank=True)
    verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    collected_at = models.DateTimeField()
    last_checked_at = models.DateTimeField()
    # Set when a later check no longer finds the value. The stored value is
    # kept and marked for verification; it is never deleted automatically.
    not_found_since = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id", "field"],
                name="intake_unique_field_provenance",
            ),
        ]


class IntakeLock(models.Model):
    """Serialises writers so concurrent runs cannot create the same record."""

    key = models.CharField(max_length=60, unique=True)
    counter = models.PositiveIntegerField(default=0)


class WorkerHeartbeat(models.Model):
    """Proof that a background worker is running (shown to Admins and monitoring)."""

    name = models.CharField(max_length=80, unique=True)
    host = models.CharField(max_length=120, blank=True)
    pid = models.PositiveIntegerField(null=True, blank=True)
    started_at = models.DateTimeField()
    heartbeat_at = models.DateTimeField()
    jobs_run = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.name} ({self.heartbeat_at:%Y-%m-%d %H:%M:%S})"
