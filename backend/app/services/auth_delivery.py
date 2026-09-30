from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import quote

from app.core.config import get_settings

settings = get_settings()


class AuthEmailDelivery(Protocol):
    def send_verification(self, *, email: str, token: str) -> None: ...

    def send_password_reset(self, *, email: str, token: str) -> None: ...


class DisabledAuthEmailDelivery:
    def _raise(self) -> None:
        raise RuntimeError("AUTH_EMAIL_DELIVERY_UNAVAILABLE")

    def send_verification(self, *, email: str, token: str) -> None:
        self._raise()

    def send_password_reset(self, *, email: str, token: str) -> None:
        self._raise()


class SmtpAuthEmailDelivery:
    def _send(self, *, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = settings.auth_smtp_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(
            settings.auth_smtp_host,
            settings.auth_smtp_port,
            timeout=10,
        ) as client:
            if settings.auth_smtp_starttls:
                client.starttls()
            if settings.auth_smtp_username:
                client.login(
                    settings.auth_smtp_username,
                    settings.auth_smtp_password,
                )
            client.send_message(message)

    def send_verification(self, *, email: str, token: str) -> None:
        base = settings.auth_public_base_url.rstrip("/")
        link = f"{base}/verify-email?token={quote(token, safe='')}"
        self._send(
            to=email,
            subject="验证你的迹忆邮箱",
            body=f"请在有效期内完成邮箱验证：\n{link}\n",
        )

    def send_password_reset(self, *, email: str, token: str) -> None:
        base = settings.auth_public_base_url.rstrip("/")
        link = f"{base}/reset-password?token={quote(token, safe='')}"
        self._send(
            to=email,
            subject="重置你的迹忆密码",
            body=f"请在有效期内重置密码：\n{link}\n",
        )


class MemoryAuthEmailDelivery:
    """Deterministic test adapter. It never logs token material."""

    def __init__(self) -> None:
        self.verification_tokens: list[tuple[str, str]] = []
        self.password_reset_tokens: list[tuple[str, str]] = []

    def send_verification(self, *, email: str, token: str) -> None:
        self.verification_tokens.append((email, token))

    def send_password_reset(self, *, email: str, token: str) -> None:
        self.password_reset_tokens.append((email, token))


_test_delivery: AuthEmailDelivery | None = None


def set_auth_email_delivery_for_testing(
    provider: AuthEmailDelivery | None,
) -> None:
    global _test_delivery
    _test_delivery = provider


def get_auth_email_delivery() -> AuthEmailDelivery:
    if _test_delivery is not None:
        return _test_delivery
    if settings.auth_email_delivery_mode == "smtp":
        return SmtpAuthEmailDelivery()
    return DisabledAuthEmailDelivery()
