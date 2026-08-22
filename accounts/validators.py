import re
from django.core.exceptions import ValidationError


class ComplexPasswordValidator:
    """
    Enforces Sprint 1 acceptance criteria exactly:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    - At least one special character
    """

    def validate(self, password, user=None):
        errors = []

        if len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
        if not re.search(r"[A-Z]", password):
            errors.append("Password must contain at least one uppercase letter.")
        if not re.search(r"[a-z]", password):
            errors.append("Password must contain at least one lowercase letter.")
        if not re.search(r"[0-9]", password):
            errors.append("Password must contain at least one number.")
        if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=\[\];'`~/\\]", password):
            errors.append("Password must contain at least one special character.")

        if errors:
            raise ValidationError(errors)

    def get_help_text(self):
        return (
            "Your password must be at least 8 characters and include an uppercase "
            "letter, a lowercase letter, a number and a special character."
        )
