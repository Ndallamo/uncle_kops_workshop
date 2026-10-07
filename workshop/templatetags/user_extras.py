from django import template

from workshop.currency import format_rand

register = template.Library()


@register.filter
def zar(amount):
    return format_rand(amount)


@register.filter
def user_role(user):
    profile = getattr(user, 'userprofile', None)
    if profile is not None:
        return getattr(profile, 'role', '')
    if getattr(user, 'is_staff', False):
        return 'admin'
    return ''
