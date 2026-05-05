from django import template

register = template.Library()

@register.filter
def user_role(user):
    profile = getattr(user, 'userprofile', None)
    if profile is not None:
        return getattr(profile, 'role', '')
    if getattr(user, 'is_staff', False):
        return 'admin'
    return ''
