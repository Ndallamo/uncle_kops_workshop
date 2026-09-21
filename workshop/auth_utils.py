import secrets
import hashlib
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.core.cache import cache
from .models import EmailVerificationToken


def send_verification_email(request, user, ttl_minutes=30):
    raw_token, token_obj = EmailVerificationToken.generate_for_user(user, ttl_minutes=ttl_minutes)
    host = request.get_host()
    scheme = 'https' if request.is_secure() else 'http'
    verify_url = f"{scheme}://{host}/verify-email/?token={raw_token}"
    subject = 'Verify your Uncle Kop\'s Workshop account'
    customer_name = user.get_full_name() or user.username
    message = (
        f"Hi {customer_name},\n\n"
        "Thank you for creating an account with Uncle Kop's Workshop. "
        f"Please verify your account by clicking the link below (valid for {ttl_minutes} minutes):\n\n"
        f"{verify_url}\n\n"
        "Once verified, you can log in and manage your vehicles, appointments, and service requests.\n\n"
        "If you did not sign up, you can ignore this message."
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])
    return token_obj


def send_service_request_confirmation(user_email, user_name, appointment, repair_order=None):
    vehicle = appointment.vehicle
    vehicle_summary = 'Unknown vehicle'
    if vehicle:
        parts = [str(vehicle.year), vehicle.make, vehicle.model]
        vehicle_summary = ' '.join(part for part in parts if part)
        if vehicle.license_plate:
            vehicle_summary = f"{vehicle_summary} (Plate: {vehicle.license_plate})"

    reference = f"RO#{repair_order.pk}" if repair_order else 'pending review'
    subject = 'Your service request has been received'
    message = (
        f"Hi {user_name or 'Customer'},\n\n"
        "Thank you for submitting your service request to Uncle Kop's Workshop. "
        "We have received the details below and a mechanic will review it shortly.\n\n"
        f"Service reference: {reference}\n"
        f"Vehicle: {vehicle_summary}\n"
        f"Appointment date/time: {appointment.date_time:%Y-%m-%d %H:%M}\n"
        f"Estimated duration: {appointment.duration} minutes\n"
        f"Requested service: {appointment.service_desc or 'Not specified'}\n"
        f"Customer notes: {appointment.notes or 'No additional notes'}\n\n"
        "What happens next:\n"
        "1. Our team will review your request and confirm the work needed.\n"
        "2. If we need more information, we will contact you directly.\n"
        "3. Once approved, the job will be scheduled and updates will be available in your dashboard.\n\n"
        "If you need to amend your request, please contact the workshop as soon as possible."
    )
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user_email])
    return True


def can_resend_verification(user, limit=3, period_seconds=3600):
    key = f"resend_verif:{user.pk}"
    data = cache.get(key, 0)
    if data >= limit:
        return False
    # increment
    cache.incr(key, delta=1) if cache.get(key) is not None else cache.set(key, 1, timeout=period_seconds)
    return True
