from django import template

from outreach.email_ui import status_css, status_label

register = template.Library()


@register.filter
def draft_status_label(status):
    return status_label(status)


@register.filter
def draft_status_css(status):
    return status_css(status)
