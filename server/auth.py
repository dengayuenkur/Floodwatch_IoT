"""
Authentication and authorisation utilities.

Security design:
  • Sensor nodes authenticate with a pre-shared API key (X-API-Key header).
  • Human users authenticate with username + password and receive a short-lived
    JWT access token (8 h) plus a long-lived refresh token (30 days).
  • Role-based access control: admin > operator > viewer.
  • Every authentication attempt (success or failure) is written to AuditLog.
  • Revoked tokens are tracked in an in-memory set (blocklist); logout adds to it.
"""
import functools
import logging
import re

from flask import request, jsonify, current_app
from flask_jwt_extended import JWTManager, get_jwt, get_jwt_identity, jwt_required

logger = logging.getLogger(__name__)
jwt    = JWTManager()

# In-memory JWT blocklist — holds revoked token JTIs until server restart.
# Tokens expire after 8 h anyway, so this provides immediate logout capability.
_REVOKED_TOKENS: set = set()

# Password complexity: min 8 chars, upper, lower, digit, special character.
_PASSWORD_RE = re.compile(
    r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[!@#$%^&*()_+\-=\[\]{}|;:,.<>?]).{8,}$'
)


def init_jwt(app):
    jwt.init_app(app)

    @jwt.token_in_blocklist_loader
    def check_if_revoked(jwt_header, jwt_payload):
        return jwt_payload.get("jti") in _REVOKED_TOKENS

    @jwt.revoked_token_loader
    def revoked_token(jwt_header, jwt_payload):
        return jsonify({"error": "Token has been revoked — please log in again"}), 401

    @jwt.unauthorized_loader
    def missing_token(reason):
        return jsonify({"error": f"Unauthorized: {reason}"}), 401

    @jwt.invalid_token_loader
    def invalid_token(reason):
        return jsonify({"error": f"Invalid token: {reason}"}), 422

    @jwt.expired_token_loader
    def expired_token(jwt_header, jwt_payload):
        return jsonify({"error": "Token has expired"}), 401


# ── Decorators ────────────────────────────────────────────────────────────────

def require_api_key(f):
    """Validate the shared sensor API key (X-API-Key header)."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        provided_key = request.headers.get("X-API-Key", "")
        expected_key = current_app.config.get("SENSOR_API_KEY", "")
        if not provided_key or provided_key != expected_key:
            log_audit(
                "UNAUTHORIZED_API_KEY",
                ip_address=get_client_ip(),
                details=f"Invalid API key from {get_client_ip()}",
            )
            return jsonify({"error": "Unauthorized: invalid API key"}), 401
        return f(*args, **kwargs)
    return decorated


def require_role(*roles):
    """Require a valid JWT AND one of the specified roles."""
    def decorator(f):
        @functools.wraps(f)
        @jwt_required()
        def decorated(*args, **kwargs):
            claims    = get_jwt()
            user_role = claims.get("role", "")
            if user_role not in roles:
                log_audit(
                    "FORBIDDEN_ROLE",
                    user=claims.get("username"),
                    ip_address=get_client_ip(),
                    details=f"Required {roles}, user has '{user_role}'",
                )
                return jsonify({"error": "Forbidden: insufficient privileges"}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


def validate_password_strength(password: str) -> str | None:
    """Return an error message if password fails complexity requirements, else None."""
    if len(password) < 8:
        return "Password must be at least 8 characters"
    if not re.search(r'[a-z]', password):
        return "Password must contain at least one lowercase letter"
    if not re.search(r'[A-Z]', password):
        return "Password must contain at least one uppercase letter"
    if not re.search(r'\d', password):
        return "Password must contain at least one number"
    if not re.search(r'[!@#$%^&*()\-_=+\[\]{}|;:,.<>?]', password):
        return "Password must contain at least one special character (!@#$%^&* etc.)"
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def log_audit(event_type: str, user: str = None,
              ip_address: str = None, details: str = None) -> None:
    """Write one row to AuditLog; silently absorbed on DB errors."""
    try:
        from models import db, AuditLog
        entry = AuditLog(
            event_type=event_type,
            user=user,
            ip_address=ip_address,
            details=details,
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as exc:
        logger.error("AuditLog write failed: %s", exc)
        try:
            from models import db
            db.session.rollback()
        except Exception:
            pass


def get_client_ip() -> str:
    """Return the real client IP, accounting for reverse proxies."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"
