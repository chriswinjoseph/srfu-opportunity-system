import re

from django import forms

from .models import Bank, Branch, Club


AUSTRALIAN_STATES = [
    ("", "Select state"),
    ("ACT", "ACT"),
    ("NSW", "NSW"),
    ("NT", "NT"),
    ("QLD", "QLD"),
    ("SA", "SA"),
    ("TAS", "TAS"),
    ("VIC", "VIC"),
    ("WA", "WA"),
]


class OrganisationValidationMixin:
    """
    Shared validation used by Bank, Branch and Club forms.
    """

    def clean_public_phone(self):
        phone = self.cleaned_data.get("public_phone", "").strip()

        if not phone:
            return ""

        # Allow spaces, brackets and hyphens in user input.
        cleaned_phone = re.sub(r"[\s()-]", "", phone)

        # Australian numbers:
        # 04xxxxxxxx
        # 0xxxxxxxxx
        # +61xxxxxxxxx
        if not re.fullmatch(r"(?:\+61|0)\d{9}", cleaned_phone):
            raise forms.ValidationError(
                "Enter a valid Australian phone number."
            )

        return phone

    def clean_postcode(self):
        postcode = self.cleaned_data.get("postcode", "").strip()

        if not postcode:
            raise forms.ValidationError(
                "Postcode is required."
            )

        if not re.fullmatch(r"\d{4}", postcode):
            raise forms.ValidationError(
                "Enter a valid 4-digit Australian postcode."
            )

        return postcode

    def clean_public_email(self):
        email = self.cleaned_data.get("public_email", "").strip()
        return email

    def clean(self):
        cleaned_data = super().clean()

        region = cleaned_data.get("region", "")
        suburb = cleaned_data.get("suburb", "")

        region = region.strip() if region else ""
        suburb = suburb.strip() if suburb else ""

        cleaned_data["region"] = region
        cleaned_data["suburb"] = suburb

        if not region and not suburb:
            raise forms.ValidationError(
                "Enter a region or suburb."
            )

        return cleaned_data


class BankForm(OrganisationValidationMixin, forms.ModelForm):
    state = forms.ChoiceField(
        choices=AUSTRALIAN_STATES,
        required=True,
        label="State / Territory",
    )

    region = forms.CharField(
        max_length=100,
        required=False,
        label="Region",
    )

    suburb = forms.CharField(
        max_length=100,
        required=False,
        label="Suburb",
    )

    postcode = forms.CharField(
        max_length=4,
        required=True,
        label="Postcode",
    )

    class Meta:
        model = Bank

        fields = [
            "bank_name",
            "state",
            "region",
            "suburb",
            "postcode",
            "website_url",
            "public_email",
            "public_phone",
            "source_url",
        ]

        labels = {
            "bank_name": "Organisation Name",
            "website_url": "Website",
            "public_email": "Email",
            "public_phone": "Contact Number",
            "source_url": "Source URL",
        }

    def clean_bank_name(self):
        name = self.cleaned_data.get("bank_name", "").strip()

        if not name:
            raise forms.ValidationError(
                "Organisation name is required."
            )

        return name


class BranchForm(OrganisationValidationMixin, forms.ModelForm):
    state = forms.ChoiceField(
        choices=AUSTRALIAN_STATES,
        required=True,
        label="State / Territory",
    )

    region = forms.CharField(
        max_length=100,
        required=False,
        label="Region",
    )

    suburb = forms.CharField(
        max_length=100,
        required=False,
        label="Suburb",
    )

    postcode = forms.CharField(
        max_length=4,
        required=True,
        label="Postcode",
    )

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

        labels = {
            "bank": "Parent Bank",
            "branch_name": "Organisation Name",
            "address": "Street Address",
            "public_email": "Email",
            "public_phone": "Contact Number",
            "website_url": "Website",
        }

    def clean_branch_name(self):
        name = self.cleaned_data.get("branch_name", "").strip()

        if not name:
            raise forms.ValidationError(
                "Organisation name is required."
            )

        return name


class ClubForm(OrganisationValidationMixin, forms.ModelForm):
    state = forms.ChoiceField(
        choices=AUSTRALIAN_STATES,
        required=True,
        label="State / Territory",
    )

    region = forms.CharField(
        max_length=100,
        required=False,
        label="Region",
    )

    suburb = forms.CharField(
        max_length=100,
        required=False,
        label="Suburb",
    )

    postcode = forms.CharField(
        max_length=4,
        required=True,
        label="Postcode",
    )

    class Meta:
        model = Club

        fields = [
            "club_name",
            "club_type",
            "suburb",
            "state",
            "postcode",
            "region",
            "website_url",
            "public_email",
            "public_phone",
            "supported_by_bank",
            "supported_by_branch",
        ]

        labels = {
            "club_name": "Organisation Name",
            "club_type": "Club Type",
            "website_url": "Website",
            "public_email": "Email",
            "public_phone": "Contact Number",
            "supported_by_bank": "Supporting Bank",
            "supported_by_branch": "Supporting Branch",
        }

    def clean_club_name(self):
        name = self.cleaned_data.get("club_name", "").strip()

        if not name:
            raise forms.ValidationError(
                "Organisation name is required."
            )

        return name

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