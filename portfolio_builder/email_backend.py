
import base64
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.core.mail.backends.base import BaseEmailBackend


class ResendEmailBackend(BaseEmailBackend):
    API_URL = "https://api.resend.com/emails"
    TIMEOUT = 15

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        api_key = os.getenv("RESEND_API_KEY")
        if not api_key:
            raise RuntimeError("RESEND_API_KEY is not configured.")

        sent = 0

        for message in email_messages:
            try:
                self._send_one(message, api_key)
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise

        return sent

    def _send_one(self, message, api_key):
        recipients = message.recipients()

        if not recipients:
            return False

        payload = {
            "from": message.from_email,
            "to": recipients,
            "subject": message.subject,
            "text": message.body,
        }

        if message.cc:
            payload["cc"] = message.cc

        if message.bcc:
            payload["bcc"] = message.bcc

        if message.reply_to:
            payload["reply_to"] = message.reply_to

        attachments = []

        for attachment in message.attachments:
            if not isinstance(attachment, tuple):
                raise ValueError(
                    "Unsupported attachment format for Resend."
                )

            filename, content, *extra = attachment

            if isinstance(content, str):
                content = content.encode("utf-8")

            attachments.append({
                "filename": filename,
                "content": base64.b64encode(
                    content
                ).decode("ascii"),
            })

        if attachments:
            payload["attachments"] = attachments

        request = Request(
            self.API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PortfolioBackend/1.0 (Django; Python)",
        },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.TIMEOUT) as response:
                result = json.loads(
                    response.read().decode("utf-8")
                )

                if response.status != 200:
                    raise RuntimeError(
                        f"Resend HTTP error: {response.status}"
                    )

                if not result.get("id"):
                    raise RuntimeError(
                        "Resend did not return an email ID."
                    )

                return True

        except HTTPError as exc:
            details = exc.read().decode(
                "utf-8", errors="replace"
            )
            raise RuntimeError(
                f"Resend API error {exc.code}: {details}"
            ) from exc

        except URLError as exc:
            raise RuntimeError(
                f"Resend connection failed: {exc.reason}"
            ) from exc
