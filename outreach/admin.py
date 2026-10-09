from django.contrib import admin
from .models import Bank, Branch, Club, Contact, Opportunity


# Fields that carry workflow state or audit history. They change only
# through the application (status transitions, Add/Archive Organisation),
# never by editing a record directly in the Django admin.
PROTECTED_ORGANISATION_FIELDS = (
    "contact_status",
    "is_archived",
    "archived_at",
    "archived_by",
    "created_by",
    "record_source",
    "duplicate_override_reason",
    "duplicate_override_at",
    "duplicate_override_by",
    "duplicate_override_match",
    "organisation_id",
    "date_added",
    "last_updated",
)


class ProtectedOrganisationAdmin(admin.ModelAdmin):
    """
    Organisations are created with Add Organisation (duplicate checks and
    locking), archived rather than deleted, and their contact status
    follows the status-transition rules. The admin can correct plain
    details of an unarchived organisation and nothing else.
    """

    actions = None

    def get_readonly_fields(self, request, obj=None):
        model_fields = {field.name for field in self.model._meta.fields}

        return [
            name
            for name in PROTECTED_ORGANISATION_FIELDS
            if name in model_fields
        ]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.is_archived:
            return False

        return super().has_change_permission(request, obj)

    def save_model(self, request, obj, form, change):
        if not change:
            return super().save_model(request, obj, form, change)

        # Write only the fields that were edited, so a stale form can
        # never overwrite contact status or archive state changed by the
        # application meanwhile. Saving still fires the recipient-email
        # signal that invalidates pending drafts.
        fields = [
            name
            for name in form.changed_data
            if name not in PROTECTED_ORGANISATION_FIELDS
        ]

        if fields:
            if any(
                field.name == "last_updated"
                for field in self.model._meta.fields
            ):
                fields.append("last_updated")

            obj.save(update_fields=fields)


@admin.register(Bank)
class BankAdmin(ProtectedOrganisationAdmin):
    list_display = ('bank_name', 'region', 'contact_status', 'public_email', 'date_added')
    list_filter = ('contact_status', 'region')
    search_fields = ('bank_name', 'public_email')


@admin.register(Branch)
class BranchAdmin(ProtectedOrganisationAdmin):
    list_display = ('branch_name', 'bank', 'region', 'contact_status')
    list_filter = ('contact_status', 'region')
    search_fields = ('branch_name',)


@admin.register(Club)
class ClubAdmin(ProtectedOrganisationAdmin):
    list_display = ('club_name', 'club_type', 'region', 'supported_by_bank', 'contact_status')
    list_filter = ('contact_status', 'region')
    search_fields = ('club_name',)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('contact_name', 'organisation', 'role', 'email')
    search_fields = ('contact_name', 'email')

    def _organisation_archived(self, obj):
        organisation = obj.organisation if obj is not None else None

        return bool(getattr(organisation, "is_archived", False))

    def has_change_permission(self, request, obj=None):
        if self._organisation_archived(obj):
            return False

        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self._organisation_archived(obj):
            return False

        return super().has_delete_permission(request, obj)


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    """
    Read-only. Opportunity status (including Do Not Contact) and the
    approval fields change only through the outreach workflow, which
    validates transitions and records history.
    """

    list_display = ('organisation', 'status', 'approved', 'date_contacted')
    list_filter = ('status', 'approved')
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
