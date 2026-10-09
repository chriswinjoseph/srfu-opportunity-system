from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.forms import AuthenticationForm

from .models import User
from .roles import ROLE_CHOICES

DISABLED_ACCOUNT_MESSAGE = (
    "Your account has been disabled. Please contact an administrator."
)


class EmailAuthenticationForm(AuthenticationForm):
    """
    Django's AuthenticationForm defaults to a 'username' field.
    Sprint 1 spec logs in with email, so relabel it and let
    USERNAME_FIELD = 'email' on the User model do the rest.
    """

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True}),
    )

    error_messages = {
        "invalid_login": "Please enter a correct email or password.",
        "inactive": DISABLED_ACCOUNT_MESSAGE,
    }

    def clean(self):
        username = self.cleaned_data.get("username")
        password = self.cleaned_data.get("password")

        if username is not None and password:
            self.user_cache = authenticate(
                self.request,
                username=username,
                password=password,
            )

            if self.user_cache is None:
                # Only reveal that an account is disabled to someone who
                # proved they know its password.
                user = User.objects.filter(email__iexact=username).first()

                if (
                    user is not None
                    and not user.is_active
                    and user.check_password(password)
                ):
                    raise forms.ValidationError(
                        DISABLED_ACCOUNT_MESSAGE,
                        code="inactive",
                    )

                raise self.get_invalid_login_error()

            self.confirm_login_allowed(self.user_cache)

        return self.cleaned_data


class ForgotPasswordForm(forms.Form):
    email = forms.EmailField(label="Email")



class AddUserForm(forms.Form):
    full_name = forms.CharField(
        label="User Name",
        max_length=300,
        error_messages={"required": "User name is required."},
    )
    email = forms.EmailField(
        label="User Email",
        error_messages={
            "required": "User email is required.",
            "invalid": "Enter a valid email address.",
        },
    )
    role = forms.ChoiceField(
        label="Role",
        choices=ROLE_CHOICES,
        widget=forms.RadioSelect,
        error_messages={
            "required": "Please choose a role.",
            "invalid_choice": "Please choose a role.",
        },
    )

    def clean_full_name(self):
        name = " ".join(self.cleaned_data["full_name"].split())

        if not name:
            raise forms.ValidationError("User name is required.")

        return name

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "A user with this email address already exists."
            )

        return email
