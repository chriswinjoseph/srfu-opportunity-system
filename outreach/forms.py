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


# Inclusive postcode ranges per state/territory (Australia Post).
STATE_POSTCODE_RANGES = {
    "ACT": [(200, 299), (2600, 2618), (2900, 2920)],
    "NSW": [(1000, 2599), (2619, 2898), (2921, 2999)],
    "NT": [(800, 999)],
    "QLD": [(4000, 4999), (9000, 9999)],
    "SA": [(5000, 5999)],
    "TAS": [(7000, 7999)],
    "VIC": [(3000, 3999), (8000, 8999)],
    "WA": [(6000, 6999)],
}


def postcode_matches_state(postcode, state):
    ranges = STATE_POSTCODE_RANGES.get(state)

    if ranges is None or not postcode.isdigit():
        return True

    value = int(postcode)

    return any(low <= value <= high for low, high in ranges)


# Australian numbers once spaces, brackets and hyphens are removed:
# mobile 04xxxxxxxx, landline 0[2378]xxxxxxxx, 1300/1800 xxxxxx,
# 13 xx xx, each optionally in +61 international form.
AUSTRALIAN_PHONE_RE = re.compile(
    r"(?:\+61|0)[2378]\d{8}"
    r"|(?:\+61|0)4\d{8}"
    r"|1[38]00\d{6}"
    r"|13\d{4}"
)


class OrganisationValidationMixin:
    """
    Shared validation used by Bank, Branch and Club forms.
    """

    def clean_public_phone(self):
        phone = self.cleaned_data.get("public_phone", "").strip()

        if not phone:
            return ""

        cleaned_phone = re.sub(r"[\s()-]", "", phone)

        if not AUSTRALIAN_PHONE_RE.fullmatch(cleaned_phone):
            raise forms.ValidationError(
                "Enter a valid Australian phone number."
            )

        return phone

    def clean_contact_name(self):
        return (self.cleaned_data.get("contact_name") or "").strip()

    def clean_contact_role(self):
        return (self.cleaned_data.get("contact_role") or "").strip()

    def clean_notes(self):
        return (self.cleaned_data.get("notes") or "").strip()

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
        email = self.cleaned_data.get(
            "public_email",
            "",
        ).strip()

        return email

    def clean(self):
        cleaned_data = super().clean()

        state = cleaned_data.get("state", "")
        suburb = cleaned_data.get("suburb", "")
        region = cleaned_data.get("region", "")

        state = state.strip() if state else ""
        suburb = suburb.strip() if suburb else ""
        region = region.strip() if region else ""

        cleaned_data["state"] = state
        cleaned_data["suburb"] = suburb
        cleaned_data["region"] = region

        # At least one genuine region or suburb is required. The
        # state is never copied into the region to satisfy this.
        if (
            not region
            and not suburb
            and "suburb" not in self.errors
            and "region" not in self.errors
        ):
            message = "Enter a region or a suburb (at least one is required)."
            self.add_error("region", message)
            self.add_error("suburb", message)

        postcode = cleaned_data.get("postcode", "")

        if (
            state
            and postcode
            and not postcode_matches_state(postcode, state)
        ):
            self.add_error(
                "postcode",
                f"Postcode {postcode} is not valid for {state}. "
                "Check the postcode or the state/territory.",
            )

        return cleaned_data


class BankForm(
    OrganisationValidationMixin,
    forms.ModelForm,
):
    state = forms.ChoiceField(
        choices=AUSTRALIAN_STATES,
        required=True,
        label="State / Territory",
    )

    region = forms.CharField(
        max_length=100,
        required=False,
        label="Region",
        help_text="Provide a region or a suburb (at least one).",
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

    public_email = forms.EmailField(
        required=False,
        label="Email",
    )

    contact_name = forms.CharField(
        max_length=255,
        required=False,
        label="Contact Person Name",
    )

    contact_role = forms.CharField(
        max_length=100,
        required=False,
        label="Contact Person Role",
    )

    notes = forms.CharField(
        required=False,
        label="Notes / Other Public Information",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = Bank

        fields = [
            "bank_name",
            "state",
            "region",
            "address",
            "suburb",
            "postcode",
            "website_url",
            "public_email",
            "public_phone",
            "source_url",
        ]

        labels = {
            "bank_name": "Organisation Name",
            "address": "Street Address",
            "website_url": "Website",
            "public_email": "Email",
            "public_phone": "Contact Number",
            "source_url": "Source URL",
        }

    def clean_bank_name(self):
        name = self.cleaned_data.get(
            "bank_name",
            "",
        ).strip()

        if not name:
            raise forms.ValidationError(
                "Organisation name is required."
            )

        return name


class BranchForm(
    OrganisationValidationMixin,
    forms.ModelForm,
):
    state = forms.ChoiceField(
        choices=AUSTRALIAN_STATES,
        required=True,
        label="State / Territory",
    )

    region = forms.CharField(
        max_length=100,
        required=False,
        label="Region",
        help_text="Provide a region or a suburb (at least one).",
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

    public_email = forms.EmailField(
        required=False,
        label="Email",
    )

    contact_name = forms.CharField(
        max_length=255,
        required=False,
        label="Contact Person Name",
    )

    contact_role = forms.CharField(
        max_length=100,
        required=False,
        label="Contact Person Role",
    )

    notes = forms.CharField(
        required=False,
        label="Notes / Other Public Information",
        widget=forms.Textarea(attrs={"rows": 3}),
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
        name = self.cleaned_data.get(
            "branch_name",
            "",
        ).strip()

        if not name:
            raise forms.ValidationError(
                "Organisation name is required."
            )

        return name


class ClubForm(
    OrganisationValidationMixin,
    forms.ModelForm,
):
    state = forms.ChoiceField(
        choices=AUSTRALIAN_STATES,
        required=True,
        label="State / Territory",
    )

    region = forms.CharField(
        max_length=100,
        required=False,
        label="Region",
        help_text="Provide a region or a suburb (at least one).",
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

    public_email = forms.EmailField(
        required=False,
        label="Email",
    )

    contact_name = forms.CharField(
        max_length=255,
        required=False,
        label="Contact Person Name",
    )

    contact_role = forms.CharField(
        max_length=100,
        required=False,
        label="Contact Person Role",
    )

    notes = forms.CharField(
        required=False,
        label="Notes / Other Public Information",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = Club

        fields = [
            "club_name",
            "club_type",
            "address",
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
            "address": "Street Address",
            "website_url": "Website",
            "public_email": "Email",
            "public_phone": "Contact Number",
            "supported_by_bank": "Supporting Bank",
            "supported_by_branch": "Supporting Branch",
        }

    def clean_club_name(self):
        name = self.cleaned_data.get(
            "club_name",
            "",
        ).strip()

        if not name:
            raise forms.ValidationError(
                "Organisation name is required."
            )

        return name

    def clean(self):
        cleaned_data = super().clean()

        bank = cleaned_data.get(
            "supported_by_bank"
        )

        branch = cleaned_data.get(
            "supported_by_branch"
        )

        if (
            bank
            and branch
            and branch.bank_id != bank.id
        ):
            raise forms.ValidationError(
                "The selected branch must belong to the "
                "selected supporting bank."
            )

        return cleaned_data