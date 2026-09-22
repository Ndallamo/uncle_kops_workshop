from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from workshop.models import Customer
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Command(BaseCommand):
    help = 'Print decrypted sensitive fields for a Customer (by pk or email).'

    def add_arguments(self, parser):
        parser.add_argument('--pk', type=int, help='Primary key of the Customer')
        parser.add_argument('--email', type=str, help='Email of the Customer')

    def handle(self, *args, **options):
        pk = options.get('pk')
        email = options.get('email')
        if not pk and not email:
            raise CommandError('Provide --pk or --email')

        try:
            if pk:
                customer = Customer.objects.get(pk=pk)
            else:
                customer = Customer.objects.get(email=email)
        except Customer.DoesNotExist:
            raise CommandError('Customer not found')

        # Ensure key is configured
        key_b64 = getattr(settings, 'ENCRYPTION_KEY', '')
        if not key_b64:
            raise CommandError('ENCRYPTION_KEY not configured in settings')

        try:
            key = base64.b64decode(key_b64)
        except Exception as e:
            raise CommandError(f'Failed to base64-decode ENCRYPTION_KEY: {e}')

        def try_decrypt(field_value):
            if field_value is None:
                return None
            # If the field is already decrypted by model accessors, just return it
            # but in case Django returned raw DB blob, attempt manual decrypt
            try:
                if isinstance(field_value, str) and _looks_like_base64_blob(field_value):
                    data = base64.b64decode(field_value)
                    nonce = data[:12]
                    ct = data[12:]
                    aesgcm = AESGCM(key)
                    return aesgcm.decrypt(nonce, ct, None).decode('utf-8')
            except Exception:
                pass
            return field_value

        def _looks_like_base64_blob(s: str):
            try:
                b = base64.b64decode(s)
                return len(b) > 12
            except Exception:
                return False

        # Print decrypted values
        self.stdout.write(f'Customer: {customer} (pk={customer.pk})')
        self.stdout.write(f'Email: {customer.email}')
        self.stdout.write(f'Phone: {try_decrypt(customer.phone)}')
        self.stdout.write(f'Address: {try_decrypt(customer.address)}')
        self.stdout.write(f'Notes: {try_decrypt(customer.notes)}')
