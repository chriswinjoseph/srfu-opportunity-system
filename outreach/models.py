from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType


CONTACT_STATUS_CHOICES = [
    ("not_yet_contacted", "Not Yet Contacted"),
    ("contacted", "Contacted"),
    ("interested", "Interested"),
    ("not_interested", "Not Interested"),
    ("do_not_contact", "Do Not Contact"),
]


class Bank(models.Model):
    bank_name = models.CharField(max_length=255)
    website_url = models.URLField(blank=True)
    region = models.CharField(max_length=100)
    contact_status = models.CharField(
        max_length=20, choices=CONTACT_STATUS_CHOICES, default="not_yet_contacted"
    )
    public_email = models.EmailField(blank=True)
    public_phone = models.CharField(max_length=30, blank=True)
    source_url = models.URLField(blank=True)
    date_added = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    contacts = GenericRelation("Contact", related_query_name="bank")
    opportunities = GenericRelation("Opportunity", related_query_name="bank")

    def __str__(self):
        return self.bank_name


class Branch(models.Model):
    bank = models.ForeignKey(Bank, on_delete=models.CASCADE, related_name="branches")
    branch_name = models.CharField(max_length=255)
    address = models.CharField(max_length=255, blank=True)
    suburb = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    postcode = models.CharField(max_length=10, blank=True)
    region = models.CharField(max_length=100, blank=True)
    public_email = models.EmailField(blank=True)
    public_phone = models.CharField(max_length=30, blank=True)
    website_url = models.URLField(blank=True)
    contact_status = models.CharField(
        max_length=20, choices=CONTACT_STATUS_CHOICES, default="not_yet_contacted"
    )

    contacts = GenericRelation("Contact", related_query_name="branch")
    opportunities = GenericRelation("Opportunity", related_query_name="branch")

    class Meta:
        verbose_name_plural = "branches"

    def __str__(self):
        return f"{self.branch_name} ({self.bank.bank_name})"


class Club(models.Model):
    club_name = models.CharField(max_length=255)
    club_type = models.CharField(max_length=100, blank=True)
    suburb = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    region = models.CharField(max_length=100, blank=True)
    website_url = models.URLField(blank=True)
    public_email = models.EmailField(blank=True)
    public_phone = models.CharField(max_length=30, blank=True)
    supported_by_bank = models.ForeignKey(
        Bank, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="supported_clubs",
    )
    contact_status = models.CharField(
        max_length=20, choices=CONTACT_STATUS_CHOICES, default="not_yet_contacted"
    )

    contacts = GenericRelation("Contact", related_query_name="club")
    opportunities = GenericRelation("Opportunity", related_query_name="club")

    def __str__(self):
        return self.club_name


ORGANISATION_MODELS = models.Q(app_label="outreach", model="bank") | \
    models.Q(app_label="outreach", model="branch") | \
    models.Q(app_label="outreach", model="club")


class Contact(models.Model):
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, limit_choices_to=ORGANISATION_MODELS
    )
    object_id = models.PositiveIntegerField()
    organisation = GenericForeignKey("content_type", "object_id")

    contact_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    source_url = models.URLField(blank=True)
    last_verified = models.DateField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.contact_name or 'Unnamed contact'} @ {self.organisation}"


class Opportunity(models.Model):
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, limit_choices_to=ORGANISATION_MODELS
    )
    object_id = models.PositiveIntegerField()
    organisation = GenericForeignKey("content_type", "object_id")

    status = models.CharField(
        max_length=20, choices=CONTACT_STATUS_CHOICES, default="not_yet_contacted"
    )
    date_created = models.DateTimeField(auto_now_add=True)
    date_contacted = models.DateTimeField(null=True, blank=True)
    outreach_method = models.CharField(max_length=50, blank=True)
    draft_email = models.TextField(blank=True)
    approved = models.BooleanField(default=False)
    approved_by = models.CharField(max_length=255, blank=True)
    date_approved = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        indexes = [models.Index(fields=["content_type", "object_id"])]
        verbose_name_plural = "opportunities"

    def __str__(self):
        return f"Opportunity for {self.organisation} - {self.status}"
