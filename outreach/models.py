import uuid

from django.conf import settings
from django.db import models
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

    bank_name = models.CharField(
        max_length=255,
    )

    website_url = models.URLField(
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
        name = (
            self.contact_name
            or "Unnamed contact"
        )

        return (
            f"{name} @ "
            f"{self.organisation}"
        )


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
        return (
            f"Opportunity for "
            f"{self.organisation} - "
            f"{self.status}"
        )