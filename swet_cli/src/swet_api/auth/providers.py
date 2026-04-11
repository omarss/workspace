"""OTP delivery providers: console (dev), Twilio Verify, Twilio SMS, SendGrid (email)."""

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class OTPProvider(Protocol):
    """Protocol for OTP delivery providers."""

    # Whether this provider manages OTP generation and verification itself
    # (e.g. Twilio Verify). When True, the auth router skips local OTP
    # generation/storage and delegates verification to the provider.
    manages_verification: bool

    def send(self, destination: str, code: str) -> None:
        """Send an OTP code to the destination (email or phone number).

        For providers with manages_verification=True, `code` is ignored —
        the provider generates and delivers its own code.
        """
        ...

    def verify(self, destination: str, code: str) -> bool:
        """Verify an OTP code. Only used when manages_verification=True."""
        ...


class ConsoleOTPProvider:
    """Development provider that prints OTP to the console/logs."""

    manages_verification = False

    def send(self, destination: str, code: str) -> None:
        logger.info("OTP for %s: %s", destination, code)
        print(f"[DEV] OTP for {destination}: {code}")  # noqa: T201

    def verify(self, destination: str, code: str) -> bool:
        return False  # Not used — auth router checks its own hash


class TwilioVerifyProvider:
    """Send and verify OTP via Twilio Verify API.

    Twilio Verify handles OTP generation, delivery (SMS/WhatsApp/email),
    rate limiting, and fraud protection. No Twilio phone number needed.
    """

    manages_verification = True

    def __init__(self, account_sid: str, auth_token: str, verify_service_sid: str) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.verify_service_sid = verify_service_sid

    def send(self, destination: str, code: str) -> None:
        from twilio.rest import Client

        client = Client(self.account_sid, self.auth_token)
        # Determine channel based on destination format
        channel = "email" if "@" in destination else "sms"
        client.verify.v2.services(self.verify_service_sid).verifications.create(
            to=destination, channel=channel
        )

    def verify(self, destination: str, code: str) -> bool:
        from twilio.rest import Client

        client = Client(self.account_sid, self.auth_token)
        try:
            check = client.verify.v2.services(
                self.verify_service_sid
            ).verification_checks.create(to=destination, code=code)
            return check.status == "approved"
        except Exception:
            logger.exception("Twilio Verify check failed")
            return False


class TwilioOTPProvider:
    """Send OTP via Twilio basic SMS (requires a Twilio phone number)."""

    manages_verification = False

    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number

    def send(self, destination: str, code: str) -> None:
        from twilio.rest import Client

        client = Client(self.account_sid, self.auth_token)
        client.messages.create(
            body=f"Your SWET verification code is: {code}",
            from_=self.from_number,
            to=destination,
        )

    def verify(self, destination: str, code: str) -> bool:
        return False


class SendGridOTPProvider:
    """Send OTP via SendGrid email."""

    manages_verification = False

    def __init__(self, api_key: str, from_email: str) -> None:
        self.api_key = api_key
        self.from_email = from_email

    def send(self, destination: str, code: str) -> None:
        import sendgrid
        from sendgrid.helpers.mail import Content, Email, Mail, To

        sg = sendgrid.SendGridAPIClient(api_key=self.api_key)
        mail = Mail(
            from_email=Email(self.from_email),
            to_emails=To(destination),
            subject="SWET Verification Code",
            plain_text_content=Content("text/plain", f"Your SWET verification code is: {code}"),
        )
        sg.client.mail.send.post(request_body=mail.get())

    def verify(self, destination: str, code: str) -> bool:
        return False


def get_otp_provider() -> OTPProvider:
    """Get the configured OTP provider based on config."""
    from swet_api.config import get_api_config

    config = get_api_config()

    if config.otp_provider == "twilio_verify":
        return TwilioVerifyProvider(
            account_sid=config.twilio_account_sid,
            auth_token=config.twilio_auth_token,
            verify_service_sid=config.twilio_verify_service_sid,
        )
    elif config.otp_provider == "twilio":
        return TwilioOTPProvider(
            account_sid=config.twilio_account_sid,
            auth_token=config.twilio_auth_token,
            from_number=config.twilio_phone_number,
        )
    elif config.otp_provider == "sendgrid":
        return SendGridOTPProvider(
            api_key=config.sendgrid_api_key,
            from_email=config.sendgrid_from_email,
        )
    else:
        return ConsoleOTPProvider()
