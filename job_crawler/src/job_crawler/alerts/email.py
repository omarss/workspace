"""Email alerts via plain async SMTP — zero paid-API dependency.

Why SMTP (not Resend / Mailgun / SES)
-------------------------------------
The project's standing rule (see AGENTS.md → "OSS-first") is to avoid
paid SaaS/GenAI dependencies when an open-source equivalent does the job.
`aiosmtplib` (MIT) gives us full async SMTP with STARTTLS / SMTPS in
~5 kB of code, and works with any SMTP relay:

  * Gmail SMTP (smtp.gmail.com:587, STARTTLS, app-password auth)
    — recommended for personal-scale alerting to your own Gmail inbox.
  * A self-hosted postfix on the same machine (smtp://127.0.0.1:25)
    — fastest, but Gmail deliverability depends on SPF/DKIM/DMARC.
  * Any RFC-compliant relay (mail-in-a-box, Postal, etc.).

Environment variables (all required for an email to actually be sent;
otherwise the alerter logs and exits cleanly):

    SMTP_HOST           e.g. smtp.gmail.com
    SMTP_PORT           e.g. 587 (STARTTLS) or 465 (SMTPS)
    SMTP_USERNAME       e.g. omar.s.shaaban@gmail.com
    SMTP_PASSWORD       app password / SMTP password
    SMTP_STARTTLS       'true' (default) or 'false'
    SMTP_USE_SSL        'true' or 'false' (default) — implicit SMTPS on :465
    ALERT_EMAIL_FROM    e.g. "job-crawler <alerts@jobs.omarss.net>"
    ALERT_EMAIL_TO      e.g. omar.s.shaaban@gmail.com

Costs nothing, deliverable to Gmail with an app password, and behaves
identically whether the alerter is running locally or in k3s.
"""

from __future__ import annotations

import logging
import os
from email.message import EmailMessage
from typing import Final

import aiosmtplib

_LOG: Final = logging.getLogger("job_crawler.alerts")


async def send_alert(
    subject: str,
    body: str,
    *,
    to: str | None = None,
    from_addr: str | None = None,
) -> bool:
    """Send one plain-text alert. Returns True on success.

    Never raises — a broken alerter must not break a crawl run. All
    failures (missing config, SMTP error, auth refused) are logged.
    """
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        _LOG.info("SMTP_HOST unset; skipping alert: %s", subject)
        return False

    addr_to = (to or os.environ.get("ALERT_EMAIL_TO", "")).strip()
    if not addr_to:
        _LOG.info("ALERT_EMAIL_TO unset; skipping alert: %s", subject)
        return False
    addr_from = (
        from_addr
        or os.environ.get("ALERT_EMAIL_FROM", "").strip()
        or "alerts@jobs.omarss.net"
    )

    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME", "").strip() or None
    password = os.environ.get("SMTP_PASSWORD", "").strip() or None
    use_ssl = _truthy(os.environ.get("SMTP_USE_SSL", "false"))
    use_starttls = _truthy(os.environ.get("SMTP_STARTTLS", "true")) and not use_ssl

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = addr_from
    msg["To"] = addr_to
    msg.set_content(body)

    try:
        await aiosmtplib.send(
            msg,
            hostname=host,
            port=port,
            username=username,
            password=password,
            use_tls=use_ssl,
            start_tls=use_starttls,
            timeout=15.0,
        )
        _LOG.info("alert sent: %s", subject)
        return True
    except Exception:
        _LOG.exception("SMTP send failed for alert: %s", subject)
        return False


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
