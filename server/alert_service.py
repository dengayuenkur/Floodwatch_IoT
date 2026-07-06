"""
Alert notification service.

Supports:
  • SMS via Twilio REST API
  • Email via the Resend HTTP API

Both channels are optional: if the relevant credentials are absent the
function returns False and logs a warning rather than raising an exception,
keeping the system operational even when external services are unavailable.
"""
import logging
from datetime import datetime, timezone

import requests
from flask import current_app

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"

# ── Alert message templates ───────────────────────────────────────────────────

_TEMPLATES = {
    2: {
        "subject": "[FLOOD WARNING] Water Level Rising — {location}",
        "body": (
            "FLOOD WARNING ALERT\n"
            + "=" * 48 + "\n" +
            "Sensor ID  : {sensor_id}\n"
            "Location   : {location}\n"
            "Water Level: {water_level:.1f} cm\n"
            "Alert Level: WARNING\n"
            "Time (UTC) : {timestamp}\n"
            + "-" * 48 + "\n" +
            "ACTION REQUIRED:\n"
            "  Water levels are rising above normal. Monitor closely.\n"
            "  Pre-activate emergency response teams.\n"
            "  Notify downstream communities.\n"
            "\nThis is an automated alert from the IoT Flood Monitoring System.\n"
        ),
    },
    3: {
        "subject": "!!! DANGER — FLOOD ALERT — IMMEDIATE ACTION REQUIRED — {location}",
        "body": (
            "!!! CRITICAL FLOOD DANGER ALERT !!!\n"
            + "=" * 48 + "\n" +
            "Sensor ID  : {sensor_id}\n"
            "Location   : {location}\n"
            "Water Level: {water_level:.1f} cm  ← CRITICAL\n"
            "Alert Level: DANGER\n"
            "Time (UTC) : {timestamp}\n"
            + "-" * 48 + "\n" +
            "IMMEDIATE ACTIONS REQUIRED:\n"
            "  1. Activate full emergency response protocols.\n"
            "  2. EVACUATE all flood-risk zones immediately.\n"
            "  3. Alert emergency services (police / fire / medical).\n"
            "  4. Broadcast public warnings via all available channels.\n"
            "  5. Notify downstream communities and dam operators.\n"
            "\nThis is an automated alert from the IoT Flood Monitoring System.\n"
        ),
    },
}


# ── Public API ────────────────────────────────────────────────────────────────

def send_sms_alert(sensor_id: str, location: str,
                   water_level: float, alert_level: int) -> bool:
    """Send an SMS to all configured recipients via Twilio."""
    try:
        from twilio.rest import Client
    except ImportError:
        logger.warning("Twilio not installed — pip install twilio")
        return False

    try:
        cfg        = current_app.config
        account_sid = cfg.get("TWILIO_ACCOUNT_SID",  "")
        auth_token  = cfg.get("TWILIO_AUTH_TOKEN",   "")
        from_number = cfg.get("TWILIO_FROM_NUMBER",  "")
        to_numbers  = cfg.get("ALERT_PHONE_NUMBERS", [])

        if not (account_sid and auth_token and from_number and to_numbers):
            logger.warning("SMS config incomplete — skipping SMS alert")
            return False

        body   = _build_sms(sensor_id, location, water_level, alert_level)
        client = Client(account_sid, auth_token)
        for number in to_numbers:
            client.messages.create(body=body, from_=from_number, to=number)
            logger.info("SMS sent to %s", number)
        return True

    except Exception as exc:
        logger.error("SMS alert failed: %s", exc)
        return False


def send_email_alert(sensor_id: str, location: str,
                     water_level: float, alert_level: int) -> bool:
    """Send an email alert to all configured recipients via the Resend HTTP API."""
    cfg        = current_app.config
    api_key    = cfg.get("RESEND_API_KEY", "")
    from_email = cfg.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    recipients = cfg.get("ALERT_EMAILS", [])

    if not (api_key and recipients):
        logger.warning("Email config incomplete — skipping email alert")
        return False

    tpl     = _TEMPLATES.get(alert_level, _TEMPLATES[2])
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    subject = tpl["subject"].format(location=location)
    body    = tpl["body"].format(
        sensor_id=sensor_id,
        location=location,
        water_level=water_level,
        timestamp=now_str,
    )

    try:
        resp = requests.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": f"Flood Monitor <{from_email}>",
                "to": recipients,
                "subject": subject,
                "text": body,
            },
            timeout=10,
        )
        if resp.status_code >= 400:
            logger.error("Email alert failed: HTTP %s — %s", resp.status_code, resp.text)
            return False

        logger.info("Email alert sent to %s", recipients)
        return True

    except requests.RequestException as exc:
        logger.error("Email alert failed: %s", exc)
        return False


# ── Private helpers ───────────────────────────────────────────────────────────

def _build_sms(sensor_id: str, location: str,
               water_level: float, alert_level: int) -> str:
    level_str = "WARNING" if alert_level == 2 else "DANGER"
    now_str   = datetime.now(timezone.utc).strftime("%H:%M UTC")
    return (
        f"FLOOD {level_str}! {sensor_id} at {location}. "
        f"Water: {water_level:.0f}cm. {now_str}. "
        f"Take immediate action!"
    )
