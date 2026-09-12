import requests

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_POST

from .forms import EmailAuthenticationForm, ForgotPasswordForm, SignUpForm
from .models import User


def signup_view(request):
    if request.user.is_authenticated:
        return redirect("outreach_dashboard")

    if request.method == "POST":
        form = SignUpForm(request.POST)

        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("outreach_dashboard")
    else:
        form = SignUpForm()

    return render(
        request,
        "accounts/signup.html",
        {"form": form},
    )


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy("outreach_dashboard")


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def dashboard_view(request):
    """
    Redirect the old account dashboard URL to the new Sprint 2 dashboard.
    """
    return redirect("outreach_dashboard")


def forgot_password_view(request):
    submitted = False

    if request.method == "POST":
        form = ForgotPasswordForm(request.POST)

        if form.is_valid():
            email = form.cleaned_data["email"].lower().strip()
            user = User.objects.filter(email=email).first()

            # Always show the same confirmation whether or not the account
            # exists. This prevents leaking registered email addresses.
            if user is not None:
                _send_password_reset_email(request, user)

            submitted = True
            form = ForgotPasswordForm()
    else:
        form = ForgotPasswordForm()

    return render(
        request,
        "accounts/forgot_password.html",
        {
            "form": form,
            "submitted": submitted,
        },
    )


def _send_password_reset_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    reset_path = reverse_lazy(
        "password_reset_confirm",
        kwargs={
            "uidb64": uid,
            "token": token,
        },
    )

    reset_url = request.build_absolute_uri(str(reset_path))

    subject = "Reset your Safe Roads For Us password"

    message = render_to_string(
        "accounts/email/password_reset_email.txt",
        {
            "user": user,
            "reset_url": reset_url,
        },
    )

    try:
        response = requests.post(
            "https://api.elasticemail.com/v2/email/send",
            data={
                "apikey": settings.ELASTIC_EMAIL_API_KEY,
                "from": settings.DEFAULT_FROM_EMAIL,
                "to": user.email,
                "subject": subject,
                "bodyText": message,
            },
            timeout=10,
        )

    except requests.RequestException as exc:
        print(
            "[password reset] Request to Elastic Email failed "
            f"for {user.email}: {exc}"
        )
        return

    # Elastic Email may return HTTP 200 even when sending fails.
    # The JSON success field contains the actual result.
    try:
        result = response.json()

    except ValueError:
        print(
            "[password reset] Non-JSON response for "
            f"{user.email}: {response.status_code} "
            f"{response.text[:200]}"
        )
        return

    if result.get("success"):
        message_id = result.get("data", {}).get("messageid")

        print(
            f"[password reset] Sent to {user.email}, "
            f"messageid={message_id}"
        )
    else:
        print(
            "[password reset] Elastic Email rejected send to "
            f"{user.email}: {result.get('error')}"
        )