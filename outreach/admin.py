from django.contrib import admin
from .models import Bank, Branch, Club, Contact, Opportunity


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = ('bank_name', 'region', 'contact_status', 'public_email', 'date_added')
    list_filter = ('contact_status', 'region')
    search_fields = ('bank_name', 'public_email')


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('branch_name', 'bank', 'region', 'contact_status')
    list_filter = ('contact_status', 'region')
    search_fields = ('branch_name',)


@admin.register(Club)
class ClubAdmin(admin.ModelAdmin):
    list_display = ('club_name', 'club_type', 'region', 'supported_by_bank', 'contact_status')
    list_filter = ('contact_status', 'region')
    search_fields = ('club_name',)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('contact_name', 'organisation', 'role', 'email')
    search_fields = ('contact_name', 'email')


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ('organisation', 'status', 'approved', 'date_contacted')
    list_filter = ('status', 'approved')