from django import forms

from .models import Bank, Branch, Club


class BankForm(forms.ModelForm):
    class Meta:
        model = Bank
        fields = [
            "bank_name",
            "region",
            "website_url",
            "public_email",
            "public_phone",
            "source_url",
        ]


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = [
            "bank",
            "branch_name",
            "address",
            "suburb",
            "state",
            "postcode",
            "region",
            "public_email",
            "public_phone",
            "website_url",
        ]


class ClubForm(forms.ModelForm):
    class Meta:
        model = Club
        fields = [
            "club_name",
            "club_type",
            "suburb",
            "state",
            "region",
            "website_url",
            "public_email",
            "public_phone",
            "supported_by_bank",
            "supported_by_branch",
        ]

    def clean(self):
        cleaned_data = super().clean()
        bank = cleaned_data.get("supported_by_bank")
        branch = cleaned_data.get("supported_by_branch")

        if bank and branch and branch.bank_id != bank.id:
            raise forms.ValidationError(
                "The selected branch must belong to the "
                "selected supporting bank."
            )

        return cleaned_data