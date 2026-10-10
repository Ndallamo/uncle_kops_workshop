from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .models import Customer


class CustomerProfileCompletionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        profile = getattr(user, 'userprofile', None) if user.is_authenticated else None
        allowed_paths = {
            reverse('customer_profile'),
            reverse('logout'),
            reverse('privacy_policy'),
            reverse('terms_and_conditions'),
        }
        is_asset_request = request.path_info.startswith(('/static/', '/media/'))

        if profile and profile.role == 'customer' and not is_asset_request and request.path_info not in allowed_paths:
            customer = Customer.objects.filter(email=user.email).first()
            if not customer or not customer.has_required_contact_details:
                messages.info(request, 'Please update your phone number and address before continuing.')
                return redirect('customer_profile')

        return self.get_response(request)
