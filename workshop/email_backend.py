"""Django email backend for Resend's HTTPS email API.

Railway Trial, Free, and Hobby plans cannot use outbound SMTP. This backend
submits emails over HTTPS, which works on those plans.
"""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.mail.backends.base import BaseEmailBackend


class ResendEmailBackend(BaseEmailBackend):
    api_url = 'https://api.resend.com/emails'

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = getattr(settings, 'RESEND_API_KEY', '')
        from_email = getattr(settings, 'RESEND_FROM_EMAIL', '')
        if not api_key:
            raise ImproperlyConfigured('RESEND_API_KEY is required to send email through Resend.')
        if not from_email:
            raise ImproperlyConfigured('RESEND_FROM_EMAIL must be a verified sender address.')

        sent_count = 0
        timeout = settings.EMAIL_API_TIMEOUT
        for message in email_messages:
            recipients = message.recipients()
            if not recipients:
                continue

            payload = {
                'from': from_email,
                'to': recipients,
                'subject': message.subject,
                'text': message.body,
            }
            html_body = next(
                (
                    content
                    for content, mimetype in getattr(message, 'alternatives', ())
                    if mimetype == 'text/html'
                ),
                None,
            )
            if html_body:
                payload['html'] = html_body
            if message.cc:
                payload['cc'] = message.cc
            if message.bcc:
                payload['bcc'] = message.bcc

            request = Request(
                self.api_url,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                },
                method='POST',
            )
            try:
                with urlopen(request, timeout=timeout) as response:
                    if 200 <= response.status < 300:
                        sent_count += 1
            except HTTPError as exc:
                raise RuntimeError(
                    f'Resend rejected the email request with HTTP {exc.code}.'
                ) from None
            except (TimeoutError, URLError, OSError) as exc:
                raise RuntimeError('Could not submit the email to Resend over HTTPS.') from exc

        return sent_count
