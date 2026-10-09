from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, PasswordResetConfirmView
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse_lazy
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_POST

from .forms import EmailAuthenticationForm, ForgotPasswordForm
from .models import User


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
    Redirect the old account dashboard URL to the Sprint 2 dashboard.
    """
    return redirect("outreach_dashboard")


def forgot_password_view(request):
    submitted = False

    if request.method == "POST":
        form = ForgotPasswordForm(request.POST)

        if form.is_valid():
            email = form.cleaned_data["email"].lower().strip()
            # Disabled accounts and pending invitations must not obtain
            # access through password reset. Only an Admin can resend an
            # invitation.
            user = User.objects.filter(
                email=email,
                is_active=True,
                invitation_pending=False,
            ).first()

            # Use the same confirmation for registered and unknown emails.
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

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
    )


class PasswordSetupView(PasswordResetConfirmView):
    """
    Password reset / invitation setup. Disabled accounts get the normal
    "invalid link" page, so a disabled user can never regain access by
    setting a password.
    """

    template_name = "accounts/password_reset_confirm.html"
    success_url = "/accounts/reset/done/"

    def get_user(self, uidb64):
        user = super().get_user(uidb64)

        if user is None or not user.is_active:
            return None

        return user

    def form_valid(self, form):
        user = self.user
        was_pending = user.invitation_pending

        response = super().form_valid(form)

        if was_pending:
            from .models import UserActivity

            User.objects.filter(pk=user.pk).update(
                invitation_pending=False,
            )
            UserActivity.objects.create(
                actor=None,
                target=user,
                actor_email="",
                target_email=user.email,
                action="invitation_accepted",
            )

        return response
