"""
Configuration for the Flood Monitoring System server.
All sensitive values are read from environment variables so the
same codebase can be deployed across development and production
without code changes.
"""
import os
from datetime import timedelta


class Config:
    # ── Flask ──────────────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY", "CHANGE-THIS-SECRET-IN-PRODUCTION")
    DEBUG      = False
    TESTING    = False

    # ── Database ───────────────────────────────────────────────────────────────
    # SQLite is the default; swap for MySQL/PostgreSQL in production:
    #   mysql+pymysql://user:pass@host/db  or  postgresql://user:pass@host/db
    SQLALCHEMY_DATABASE_URI     = os.environ.get("DATABASE_URL", "sqlite:///flood_monitor.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # ── JWT ─────────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY                    = os.environ.get("JWT_SECRET_KEY", "JWT-SECRET-CHANGE-THIS")
    JWT_ACCESS_TOKEN_EXPIRES          = timedelta(hours=8)
    JWT_REFRESH_TOKEN_EXPIRES         = timedelta(days=30)
    # Enable in-memory token blocklist so logout takes effect immediately
    JWT_ACCESS_TOKEN_REQUIRES_BLOCKLIST_CHECK = True

    # ── Sensor API Key (shared secret between ESP8266 and server) ───────────────
    SENSOR_API_KEY = os.environ.get("SENSOR_API_KEY", "SENSOR-API-KEY-CHANGE-THIS")

    # ── Rate limiting ──────────────────────────────────────────────────────────
    RATELIMIT_DEFAULT     = "300 per day;60 per hour"
    RATELIMIT_STORAGE_URL = "memory://"

    # ── MQTT (optional — comment out broker settings to disable) ───────────────
    MQTT_ENABLED     = os.environ.get("MQTT_ENABLED", "false").lower() == "true"
    MQTT_BROKER_HOST = os.environ.get("MQTT_BROKER_HOST", "localhost")
    MQTT_BROKER_PORT = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
    MQTT_TOPIC       = os.environ.get("MQTT_TOPIC",  "flood/sensors/#")
    MQTT_USERNAME    = os.environ.get("MQTT_USERNAME", "")
    MQTT_PASSWORD    = os.environ.get("MQTT_PASSWORD", "")

    # ── Alert Thresholds (distance in cm: smaller = higher water) ──────────────
    SAFE_THRESHOLD    = int(os.environ.get("SAFE_THRESHOLD",    "200"))
    WARNING_THRESHOLD = int(os.environ.get("WARNING_THRESHOLD", "100"))
    DANGER_THRESHOLD  = int(os.environ.get("DANGER_THRESHOLD",  "50"))

    # ── SMS (Twilio) ────────────────────────────────────────────────────────────
    TWILIO_ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID",  "")
    TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN",   "")
    TWILIO_FROM_NUMBER  = os.environ.get("TWILIO_FROM_NUMBER",  "")
    # Comma-separated phone numbers: +211912345678,+211923456789
    ALERT_PHONE_NUMBERS = [n.strip() for n in
                           os.environ.get("ALERT_PHONE_NUMBERS", "").split(",") if n.strip()]

    # ── Email (Resend HTTP API) ─────────────────────────────────────────────────
    # Raw SMTP (ports 25/465/587) is blocked outbound on many PaaS free tiers
    # (Render included), so email alerts go through Resend's HTTPS API instead.
    RESEND_API_KEY    = os.environ.get("RESEND_API_KEY", "")
    RESEND_FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    # Comma-separated email addresses
    ALERT_EMAILS  = [e.strip() for e in
                     os.environ.get("ALERT_EMAILS", "").split(",") if e.strip()]

    # ── Logging ────────────────────────────────────────────────────────────────
    LOG_FILE  = os.environ.get("LOG_FILE",  "logs/flood_monitor.log")
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # ── CORS ───────────────────────────────────────────────────────────────────
    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")

    # ── Miscellaneous ──────────────────────────────────────────────────────────
    # Minimum seconds between repeated alerts for the same sensor
    ALERT_COOLDOWN_SECONDS = int(os.environ.get("ALERT_COOLDOWN_SECONDS", "300"))
    # How many days of readings to keep before automatic cleanup
    DATA_RETENTION_DAYS    = int(os.environ.get("DATA_RETENTION_DAYS", "90"))


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///flood_monitor_dev.db")
    RATELIMIT_DEFAULT = "1000 per day;200 per hour"


class ProductionConfig(Config):
    DEBUG = False
    RATELIMIT_DEFAULT = "100 per day;20 per hour"


config_map = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "default":     DevelopmentConfig,
}
