from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType


# The 5 possible outreach statuses an organisation can have.
# Used by Bank, Branch, Club (their own status) and Opportunity (outreach status).
CONTACT_STATUS_CHOICES = [
    ("not_yet_contacted", "Not Yet Contacted"),
    ("contacted", "Contacted"),
    ("interested", "Interested"),
    ("not_interested", "Not Interested"),
    ("do_not_contact", "Do Not Contact"),
]


# A community bank - the main organisation Shane reaches out to.
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

    # Lets us find all Contacts / Opportunities linked to this bank.
    contacts = GenericRelation("Contact", related_query_name="bank")
    opportunities = GenericRelation("Opportunity", related_query_name="bank")

    def __str__(self):
        return self.bank_name


# A single branch belonging to a bank (e.g. "Riverside CBD Branch").
class Branch(models.Model):
    # Every branch belongs to exactly one bank.
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
        # Fixes the admin panel showing "Branchs" instead of "Branches".
        verbose_name_plural = "branches"

    def __str__(self):
        return f"{self.branch_name} ({self.bank.bank_name})"


# A sporting club or youth group that a bank/branch might sponsor.
class Club(models.Model):
    club_name = models.CharField(max_length=255)
    club_type = models.CharField(max_length=100, blank=True)
    suburb = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    region = models.CharField(max_length=100, blank=True)
    website_url = models.URLField(blank=True)
    public_email = models.EmailField(blank=True)
    public_phone = models.CharField(max_length=30, blank=True)

    # A club can be supported by a bank directly...
    supported_by_bank = models.ForeignKey(
        Bank, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="supported_clubs",
    )
    # ...or by one specific branch of a bank instead. Both are optional -
    # a club might have neither, either, or (rarely) both filled in.
    supported_by_branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="supported_clubs",
    )

    contact_status = models.CharField(
        max_length=20, choices=CONTACT_STATUS_CHOICES, default="not_yet_contacted"
    )

    contacts = GenericRelation("Contact", related_query_name="club")
    opportunities = GenericRelation("Opportunity", related_query_name="club")

    def __str__(self):
        return self.club_name


# Used below so Contact/Opportunity can link to a Bank, a Branch, OR a Club
# (whichever one applies) instead of needing 3 separate fields.
ORGANISATION_MODELS = models.Q(app_label="outreach", model="bank") | \
    models.Q(app_label="outreach", model="branch") | \
    models.Q(app_label="outreach", model="club")


# A real person's contact details at a bank, branch, or club.
class Contact(models.Model):
    # These two fields together point at "whichever organisation this belongs to".
    content_type = models.ForeignKey(
        ContentType, on_delete=models.CASCADE, limit_choices_to=ORGANISATION_MODELS
    )
    object_id = models.PositiveIntegerField()
    # This is the actual shortcut: contact.organisation gives you the
    # real Bank/Branch/Club object, not just an ID.
    organisation = GenericForeignKey("content_type", "object_id")

    contact_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    source_url = models.URLField(blank=True)
    last_verified = models.DateField(null=True, blank=True)

    class Meta:
        # Makes searching by organisation fast even with lots of contacts.
        indexes = [models.Index(fields=["content_type", "object_id"])]

    def __str__(self):
        return f"{self.contact_name or 'Unnamed contact'} @ {self.organisation}"


# Tracks the outreach process for one organisation - draft email,
# approval, and whether/when it was actually sent.
class Opportunity(models.Model):
    # Same "link to any organisation type" trick as Contact above.
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
        # Fixes the admin panel showing "Opportunitys" instead of "Opportunities".
        verbose_name_plural = "opportunities"

    def __str__(self):
        return f"Opportunity for {self.organisation} - {self.status}"