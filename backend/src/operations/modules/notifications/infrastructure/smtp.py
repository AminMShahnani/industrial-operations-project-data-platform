import ipaddress
import smtplib
import ssl
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from pydantic import EmailStr, Field, SecretStr, model_validator

from operations.contracts import Command, ServiceError
from operations.modules.notifications.application.email_contracts import EmailContent, EmailResult


class SmtpProfile(Command):
    organization_id: UUID
    host: str = Field(min_length=1, max_length=253, pattern=r"^[a-zA-Z0-9.:-]+$")
    port: int = Field(default=587, ge=1, le=65535)
    sender: EmailStr
    username: SecretStr | None = None
    password: SecretStr | None = None
    tls: bool = True
    app_origin: str = Field(max_length=2048)

    @model_validator(mode="after")
    def validate_profile(self) -> SmtpProfile:
        if (self.username is None) != (self.password is None):
            raise ValueError("SMTP credentials must be configured together")
        origin = urlparse(self.app_origin)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.query
            or origin.fragment
            or origin.path not in {"", "/"}
        ):
            raise ValueError(
                "Application origin must be an HTTP(S) origin without credentials or path"
            )
        if not self.tls:
            try:
                loopback = ipaddress.ip_address(self.host).is_loopback
            except ValueError:
                loopback = self.host == "localhost"
            if not loopback or self.username is not None:
                raise ValueError(
                    "Cleartext SMTP is allowed only on an unauthenticated loopback sink"
                )
        return self


def load_profile(directory: str | None, org: UUID, production: bool) -> SmtpProfile:
    if directory is None:
        raise ServiceError(503, "email_not_configured")
    try:
        path = Path(directory) / (str(org) + ".json")
        with path.open("rb") as stream:
            content = stream.read(16385)
        if len(content) > 16384:
            raise ValueError("Profile size exceeded")
        profile = SmtpProfile.model_validate_json(content)
        if profile.organization_id != org:
            raise ValueError("Profile tenant mismatch")
        if production and (not profile.tls or urlparse(profile.app_origin).scheme != "https"):
            raise ValueError("Production email requires TLS and HTTPS")
        return profile
    except OSError, ValueError:
        raise ServiceError(503, "email_profile_unavailable") from None


class SmtpTransport:
    def __init__(self, profile: SmtpProfile) -> None:
        self.profile = profile

    def send(self, identifier: UUID, content: EmailContent) -> EmailResult:
        message = EmailMessage()
        message["From"] = str(self.profile.sender)
        message["To"] = content.recipient
        message["Subject"] = content.subject
        message["Message-ID"] = f"<{identifier}@operations.invalid>"
        message.set_content(content.text)
        client: smtplib.SMTP | None = None
        in_data = False
        try:
            client = smtplib.SMTP(self.profile.host, self.profile.port, timeout=5)
            client.ehlo()
            if self.profile.tls:
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            if self.profile.username and self.profile.password:
                client.login(
                    self.profile.username.get_secret_value(),
                    self.profile.password.get_secret_value(),
                )
            code, _ = client.mail(str(self.profile.sender))
            if code != 250:
                return self.rejected(code)
            code, _ = client.rcpt(content.recipient)
            if code not in {250, 251}:
                return self.rejected(code)
            in_data = True
            code, _ = client.data(message.as_bytes(policy=SMTP_POLICY))
            return EmailResult("sent") if code == 250 else self.rejected(code)
        except smtplib.SMTPResponseException as error:
            return self.rejected(error.smtp_code)
        except OSError, smtplib.SMTPServerDisconnected:
            return EmailResult(
                "uncertain" if in_data else "retry",
                "smtp_uncertain" if in_data else "smtp_unavailable",
            )
        except smtplib.SMTPException:
            return EmailResult(
                "uncertain" if in_data else "failed",
                "smtp_uncertain" if in_data else "smtp_configuration",
            )
        finally:
            if client is not None:
                client.close()

    @staticmethod
    def rejected(code: int) -> EmailResult:
        return EmailResult("retry" if 400 <= code < 500 else "failed", "smtp_rejected")
