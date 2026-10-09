from django.contrib.auth import SESSION_KEY, get_user_model
from django.shortcuts import render


class DisabledAccountMiddleware:
    """
    Sign a disabled user out on their next request and show the required
    message. Django already stops authenticating an inactive account;
    this additionally destroys the session and explains why.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user_id = request.session.get(SESSION_KEY)

        if user_id and not request.user.is_authenticated:
            user = (
                get_user_model()
                .objects.filter(pk=user_id)
                .only("is_active")
                .first()
            )

            if user is not None and not user.is_active:
                request.session.flush()

                return render(
                    request,
                    "accounts/disabled.html",
                    status=403,
                )

        return self.get_response(request)
