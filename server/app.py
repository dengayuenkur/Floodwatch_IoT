"""
Flood Monitoring System — Main Flask Application
=================================================
Author  : Deng Daniel Ayuen Kur  (Roll No: 240103002054)
Project : Secure IoT Water Level Monitoring & Early Warning System
          for Flood Management — South Sudan Case Study

Architecture:
  • REST API  /api/v1/...  — for sensors (API-key auth) and dashboard (JWT auth)
  • WebSocket via Flask-SocketIO — pushes real-time readings to the dashboard
  • Jinja2 templates — serves the web dashboard (no separate frontend server)
  • SQLAlchemy ORM with SQLite (swappable for MySQL/PostgreSQL)

Security features:
  • JWT access tokens (8 h) + refresh tokens (30 days)
  • Pre-shared API key for sensor authentication
  • Role-based access control (admin / operator / viewer)
  • Rate limiting via Flask-Limiter
  • Full audit log (AuditLog table)
  • Input validation on every endpoint
  • Parameterised queries via ORM (SQL-injection safe)
  • CORS configured via Flask-CORS
"""

import os
import logging
import threading
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv(override=True)  # always prefer .env values over existing OS env vars

from flask import Flask, jsonify, request, render_template, redirect, url_for
from flask_cors import CORS
from flask_jwt_extended import (
    create_access_token, jwt_required, get_jwt, get_jwt_identity,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit

from config import config_map
from models import db, User, Sensor, Reading, Alert, AuditLog
from auth import (init_jwt, require_api_key, require_role, log_audit,
                  get_client_ip, validate_password_strength, _REVOKED_TOKENS)
from alert_service import send_sms_alert, send_email_alert

# ── Extension singletons (initialised later inside create_app) ────────────────
socketio = SocketIO()
limiter  = Limiter(key_func=get_remote_address)

# In-memory cooldown tracker  { sensor_id: last_alert_datetime }
_ALERT_COOLDOWN: dict = {}

ALERT_LABELS = {1: "SAFE", 2: "WARNING", 3: "DANGER"}

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
#  Application factory
# ══════════════════════════════════════════════════════════════════════════════

def create_app(config_name: str = "default") -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # Load configuration
    app.config.from_object(config_map[config_name])

    # Init extensions
    db.init_app(app)
    init_jwt(app)
    CORS(app, origins=app.config["CORS_ORIGINS"])
    socketio.init_app(app, cors_allowed_origins="*", async_mode="threading")
    limiter.init_app(app)

    _setup_logging(app)

    with app.app_context():
        db.create_all()
        _migrate_db()
        _seed_admin(app)

    # ── Security response headers (OWASP hardening) ───────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"]        = "DENY"
        response.headers["X-XSS-Protection"]       = "1; mode=block"
        response.headers["Referrer-Policy"]        = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self' ws: wss:; "
            "img-src 'self' data:;"
        )
        return response

    _register_dashboard_routes(app)
    _register_auth_api(app)
    _register_sensor_api(app)
    _register_data_api(app)
    _register_management_api(app)
    _register_error_handlers(app)

    return app


# ══════════════════════════════════════════════════════════════════════════════
#  Internal setup helpers
# ══════════════════════════════════════════════════════════════════════════════

def _setup_logging(app: Flask) -> None:
    os.makedirs("logs", exist_ok=True)
    level = getattr(logging, app.config.get("LOG_LEVEL", "INFO"), logging.INFO)
    fmt   = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"
    handlers = [
        logging.FileHandler(app.config.get("LOG_FILE", "logs/flood_monitor.log")),
        logging.StreamHandler(),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers)


def _migrate_db() -> None:
    """Add new columns to existing tables (ALTER TABLE migration for SQLite)."""
    new_columns = [
        "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN failed_login_count   INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE users ADD COLUMN locked_until         DATETIME",
    ]
    with db.engine.connect() as conn:
        for sql in new_columns:
            try:
                conn.execute(db.text(sql))
                conn.commit()
            except Exception:
                pass  # Column already exists — safe to ignore


def _seed_admin(app: Flask) -> None:
    """Create default admin account on first run."""
    if not User.query.filter_by(username="admin").first():
        admin = User(
            username="admin",
            email="admin@floodwatch.local",
            role="admin",
            is_active=True,
            must_change_password=True,   # force password change on first login
        )
        admin.set_password("Admin@FloodWatch2025!")
        db.session.add(admin)
        db.session.commit()
        app.logger.warning(
            "Default admin user created — CHANGE THE PASSWORD IMMEDIATELY: "
            "admin / Admin@FloodWatch2025!"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Dashboard (HTML page) routes
# ══════════════════════════════════════════════════════════════════════════════

def _register_dashboard_routes(app: Flask) -> None:

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/healthz")
    @limiter.exempt
    def healthz():
        # Dedicated health-check endpoint so hosting platforms (Render, etc.)
        # can poll frequently without tripping the rate limit on "/".
        return jsonify(status="ok"), 200

    @app.route("/features")
    def features_page():
        return render_template("features.html")

    @app.route("/about")
    def about_page():
        return render_template("about.html")

    @app.route("/login")
    def login_page():
        return render_template("login.html")

    @app.route("/dashboard")
    def dashboard_page():
        return render_template("dashboard.html")


# ══════════════════════════════════════════════════════════════════════════════
#  Auth API
# ══════════════════════════════════════════════════════════════════════════════

def _register_auth_api(app: Flask) -> None:

    # ── Login ─────────────────────────────────────────────────────────────────
    @app.route("/api/v1/auth/login", methods=["POST"])
    @limiter.limit("10 per minute")
    def api_login():
        data     = request.get_json(silent=True) or {}
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))

        if not username or not password:
            return jsonify({"error": "username and password are required"}), 400

        user = User.query.filter_by(username=username, is_active=True).first()

        # Account lockout check (per-username, independent of IP rate limit)
        if user and user.is_locked:
            log_audit("LOGIN_BLOCKED", user=username, ip_address=get_client_ip(),
                      details="Account temporarily locked due to repeated failures")
            return jsonify({"error": "Account temporarily locked. Try again later."}), 423

        if not user or not user.check_password(password):
            if user:
                user.failed_login_count = (user.failed_login_count or 0) + 1
                if user.failed_login_count >= 5:
                    # Lock for 15 minutes after 5 consecutive failures
                    user.locked_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=15)
                    log_audit("ACCOUNT_LOCKED", user=username, ip_address=get_client_ip(),
                              details=f"Locked after {user.failed_login_count} failed attempts")
                db.session.commit()
            log_audit("LOGIN_FAILURE", user=username, ip_address=get_client_ip(),
                      details="Invalid credentials supplied")
            return jsonify({"error": "Invalid username or password"}), 401

        # Successful login — reset lockout counters
        user.failed_login_count = 0
        user.locked_until       = None
        user.last_login         = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()

        token = create_access_token(
            identity=str(user.id),
            additional_claims={"username": user.username, "role": user.role},
        )
        log_audit("LOGIN_SUCCESS", user=username, ip_address=get_client_ip())
        return jsonify({
            "access_token":        token,
            "user":                user.to_dict(),
            "must_change_password": user.must_change_password,
        }), 200

    # ── Logout (revokes token immediately) ────────────────────────────────────
    @app.route("/api/v1/auth/logout", methods=["POST"])
    @jwt_required()
    def api_logout():
        jti    = get_jwt().get("jti")
        claims = get_jwt()
        if jti:
            _REVOKED_TOKENS.add(jti)
        log_audit("LOGOUT", user=claims.get("username"), ip_address=get_client_ip())
        return jsonify({"status": "logged out"}), 200

    # ── Profile ───────────────────────────────────────────────────────────────
    @app.route("/api/v1/auth/profile", methods=["GET"])
    @jwt_required()
    def api_profile():
        user = User.query.get(get_jwt_identity())
        if not user:
            return jsonify({"error": "User not found"}), 404
        return jsonify({"user": user.to_dict()}), 200

    # ── Change password ───────────────────────────────────────────────────────
    @app.route("/api/v1/auth/change-password", methods=["POST"])
    @jwt_required()
    def api_change_password():
        data         = request.get_json(silent=True) or {}
        old_password = str(data.get("old_password", ""))
        new_password = str(data.get("new_password", ""))

        # Enforce password complexity (uppercase, lowercase, digit, special char)
        error = validate_password_strength(new_password)
        if error:
            return jsonify({"error": error}), 400

        user = User.query.get(get_jwt_identity())
        if not user or not user.check_password(old_password):
            log_audit("PASSWORD_CHANGE_FAILED", user=user.username if user else "unknown",
                      ip_address=get_client_ip(), details="Incorrect current password")
            return jsonify({"error": "Current password is incorrect"}), 401

        user.set_password(new_password)
        user.must_change_password = False   # clear the force-change flag
        db.session.commit()
        claims = get_jwt()
        log_audit("PASSWORD_CHANGED", user=claims.get("username"),
                  ip_address=get_client_ip())
        return jsonify({"status": "password changed"}), 200


# ══════════════════════════════════════════════════════════════════════════════
#  Sensor data ingestion API  (ESP8266 → server)
# ══════════════════════════════════════════════════════════════════════════════

def _register_sensor_api(app: Flask) -> None:

    @app.route("/api/v1/reading", methods=["POST"])
    @require_api_key
    @limiter.limit("200 per minute")
    def api_submit_reading():
        data = request.get_json(silent=True)
        if data is None:
            return jsonify({"error": "Invalid JSON payload"}), 400

        # ── Extract and validate fields ────────────────────────────────────────
        sensor_id   = str(data.get("sensor_id",   "")).strip()
        location    = str(data.get("location",    "Unknown")).strip()
        distance    = data.get("distance")
        water_level = data.get("water_level")
        alert_level = int(data.get("alert_level", 1))
        rssi        = data.get("rssi")

        if not sensor_id:
            return jsonify({"error": "sensor_id is required"}), 400
        if not isinstance(distance, (int, float)):
            return jsonify({"error": "distance must be a number"}), 400
        distance = float(distance)
        if not (2.0 <= distance <= 400.0):
            return jsonify({"error": "distance out of range (2–400 cm)"}), 400
        if alert_level not in (1, 2, 3):
            return jsonify({"error": "alert_level must be 1, 2, or 3"}), 400

        # ── Auto-register sensor on first contact ──────────────────────────────
        sensor = Sensor.query.filter_by(sensor_id=sensor_id).first()
        if not sensor:
            sensor = Sensor(
                sensor_id=sensor_id,
                name=sensor_id,
                location=location,
                sensor_height=35.0,
            )
            db.session.add(sensor)
            logger.info("Auto-registered new sensor: %s", sensor_id)
        else:
            # Keep name and location in sync with whatever the firmware reports
            if location:
                sensor.location = location
            if sensor_id and (not sensor.name or sensor.name.startswith("Auto: ")):
                sensor.name = sensor_id

        sensor.last_seen = datetime.now(timezone.utc)

        # Compute water level if the firmware didn't supply it
        if water_level is None or not isinstance(water_level, (int, float)):
            water_level = max(0.0, (sensor.sensor_height or 300.0) - distance)
        water_level = float(water_level)

        # ── Persist reading ────────────────────────────────────────────────────
        reading = Reading(
            sensor_id=sensor_id,
            distance=distance,
            water_level=water_level,
            alert_level=alert_level,
            rssi=rssi,
        )
        db.session.add(reading)
        db.session.commit()

        # ── Push to dashboard via WebSocket ────────────────────────────────────
        _broadcast_reading(reading, sensor)

        # ── Trigger alerts if threshold exceeded ───────────────────────────────
        if alert_level >= 2:
            _process_alert(app, sensor, reading)

        return jsonify({
            "status":      "ok",
            "reading_id":  reading.id,
            "alert_level": alert_level,
            "alert_label": ALERT_LABELS[alert_level],
        }), 201


# ══════════════════════════════════════════════════════════════════════════════
#  Data query API  (dashboard → server)
# ══════════════════════════════════════════════════════════════════════════════

def _register_data_api(app: Flask) -> None:

    @app.route("/api/v1/readings", methods=["GET"])
    @jwt_required()
    def api_get_readings():
        sensor_id = request.args.get("sensor_id")
        limit     = min(int(request.args.get("limit",  100)), 2000)
        hours     = int(request.args.get("hours", 24))
        since     = datetime.now(timezone.utc) - timedelta(hours=hours)

        q = Reading.query.filter(Reading.timestamp >= since)
        if sensor_id:
            q = q.filter_by(sensor_id=sensor_id)
        readings = q.order_by(Reading.timestamp.asc()).limit(limit).all()
        return jsonify({"readings": [r.to_dict() for r in readings]}), 200

    @app.route("/api/v1/readings/latest", methods=["GET"])
    @jwt_required()
    def api_latest_readings():
        """Most recent reading for every active sensor."""
        sensors = Sensor.query.filter_by(is_active=True).all()
        results = []
        for s in sensors:
            r = (Reading.query
                 .filter_by(sensor_id=s.sensor_id)
                 .order_by(Reading.timestamp.desc())
                 .first())
            if r:
                d = r.to_dict()
                d["sensor_name"]     = s.name
                d["sensor_location"] = s.location
                d["sensor_online"]   = s.online
                results.append(d)
        return jsonify({"latest": results}), 200

    @app.route("/api/v1/sensors", methods=["GET"])
    @jwt_required()
    def api_list_sensors():
        sensors = Sensor.query.all()
        return jsonify({"sensors": [s.to_dict() for s in sensors]}), 200

    @app.route("/api/v1/sensors/<string:sensor_id>", methods=["GET"])
    @jwt_required()
    def api_get_sensor(sensor_id: str):
        sensor = Sensor.query.filter_by(sensor_id=sensor_id).first_or_404()
        return jsonify({"sensor": sensor.to_dict()}), 200

    @app.route("/api/v1/alerts", methods=["GET"])
    @jwt_required()
    def api_list_alerts():
        resolved = request.args.get("resolved", "false").lower() == "true"
        limit    = min(int(request.args.get("limit", 50)), 500)
        alerts   = (Alert.query
                    .filter_by(is_resolved=resolved)
                    .order_by(Alert.created_at.desc())
                    .limit(limit)
                    .all())
        return jsonify({"alerts": [a.to_dict() for a in alerts]}), 200

    @app.route("/api/v1/stats", methods=["GET"])
    @jwt_required()
    def api_stats():
        total_readings = Reading.query.count()
        active_sensors = Sensor.query.filter_by(is_active=True).count()
        open_alerts    = Alert.query.filter_by(is_resolved=False).count()
        danger_alerts  = (Alert.query
                          .filter_by(alert_type="DANGER", is_resolved=False)
                          .count())
        # Max water level in last hour
        one_hour_ago   = datetime.now(timezone.utc) - timedelta(hours=1)
        max_level_row  = (Reading.query
                          .filter(Reading.timestamp >= one_hour_ago)
                          .order_by(Reading.water_level.desc())
                          .first())
        max_level = max_level_row.water_level if max_level_row else 0.0

        return jsonify({
            "total_readings": total_readings,
            "active_sensors": active_sensors,
            "open_alerts":    open_alerts,
            "danger_alerts":  danger_alerts,
            "max_water_level": round(max_level, 2),
        }), 200


# ══════════════════════════════════════════════════════════════════════════════
#  Management API  (admin / operator actions)
# ══════════════════════════════════════════════════════════════════════════════

def _register_management_api(app: Flask) -> None:

    @app.route("/api/v1/sensors", methods=["POST"])
    @require_role("admin", "operator")
    def api_create_sensor():
        data      = request.get_json(silent=True) or {}
        sensor_id = str(data.get("sensor_id", "")).strip()
        name      = str(data.get("name",      "")).strip()
        location  = str(data.get("location",  "")).strip()

        if not sensor_id or not name:
            return jsonify({"error": "sensor_id and name are required"}), 400
        if Sensor.query.filter_by(sensor_id=sensor_id).first():
            return jsonify({"error": "Sensor ID already registered"}), 409

        sensor = Sensor(
            sensor_id=sensor_id,
            name=name,
            location=location,
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            sensor_height=float(data.get("sensor_height", 300.0)),
        )
        db.session.add(sensor)
        db.session.commit()
        claims = get_jwt()
        log_audit("SENSOR_CREATED", user=claims.get("username"),
                  ip_address=get_client_ip(), details=f"Sensor: {sensor_id}")
        return jsonify({"sensor": sensor.to_dict()}), 201

    @app.route("/api/v1/alerts/<int:alert_id>/acknowledge", methods=["POST"])
    @require_role("admin", "operator")
    def api_ack_alert(alert_id: int):
        alert  = Alert.query.get_or_404(alert_id)
        claims = get_jwt()
        alert.is_resolved      = True
        alert.resolved_at      = datetime.now(timezone.utc)
        alert.acknowledged_by  = claims.get("username", "unknown")
        db.session.commit()
        log_audit("ALERT_ACK", user=claims.get("username"),
                  ip_address=get_client_ip(), details=f"Alert #{alert_id}")
        return jsonify({"status": "acknowledged", "alert": alert.to_dict()}), 200

    @app.route("/api/v1/audit", methods=["GET"])
    @require_role("admin")
    def api_audit_log():
        limit = min(int(request.args.get("limit", 100)), 1000)
        logs  = (AuditLog.query
                 .order_by(AuditLog.timestamp.desc())
                 .limit(limit)
                 .all())
        return jsonify({"logs": [l.to_dict() for l in logs]}), 200

    @app.route("/api/v1/users", methods=["GET"])
    @require_role("admin")
    def api_list_users():
        users = User.query.all()
        return jsonify({"users": [u.to_dict() for u in users]}), 200

    @app.route("/api/v1/users", methods=["POST"])
    @require_role("admin")
    def api_create_user():
        data     = request.get_json(silent=True) or {}
        username = str(data.get("username", "")).strip()
        email    = str(data.get("email",    "")).strip()
        password = str(data.get("password", ""))
        role     = str(data.get("role",     "viewer")).strip()

        if not username or not email or len(password) < 8:
            return jsonify({"error": "username, email, and password (≥8 chars) required"}), 400
        if role not in ("admin", "operator", "viewer"):
            return jsonify({"error": "role must be admin, operator, or viewer"}), 400
        if User.query.filter_by(username=username).first():
            return jsonify({"error": "Username already taken"}), 409

        user = User(username=username, email=email, role=role)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        claims = get_jwt()
        log_audit("USER_CREATED", user=claims.get("username"),
                  ip_address=get_client_ip(), details=f"New user: {username} ({role})")
        return jsonify({"user": user.to_dict()}), 201


# ══════════════════════════════════════════════════════════════════════════════
#  Error handlers
# ══════════════════════════════════════════════════════════════════════════════

def _register_error_handlers(app: Flask) -> None:

    @app.errorhandler(400)
    def bad_request(e):
        return jsonify({"error": "Bad request"}), 400

    @app.errorhandler(404)
    def not_found(e):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(429)
    def rate_limited(e):
        return jsonify({"error": "Rate limit exceeded — slow down"}), 429

    @app.errorhandler(500)
    def server_error(e):
        logger.exception("Unhandled server error: %s", e)
        return jsonify({"error": "Internal server error"}), 500


# ══════════════════════════════════════════════════════════════════════════════
#  WebSocket event handlers
# ══════════════════════════════════════════════════════════════════════════════

@socketio.on("connect")
def ws_connect():
    emit("connected", {"message": "Connected to Flood Monitoring System"})
    logger.debug("WS client connected: %s", request.sid)


@socketio.on("request_state")
def ws_request_state():
    """On demand: send the most recent reading for every active sensor."""
    sensors = Sensor.query.filter_by(is_active=True).all()
    for s in sensors:
        r = (Reading.query
             .filter_by(sensor_id=s.sensor_id)
             .order_by(Reading.timestamp.desc())
             .first())
        if r:
            emit("new_reading", {
                "sensor_id":       s.sensor_id,
                "sensor_name":     s.name,
                "sensor_location": s.location,
                "sensor_online":   s.online,
                "distance":        r.distance,
                "water_level":     r.water_level,
                "alert_level":     r.alert_level,
                "alert_label":     r.alert_label,
                "timestamp":       r.timestamp.isoformat(),
            })


# ══════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _broadcast_reading(reading: Reading, sensor: Sensor) -> None:
    socketio.emit("new_reading", {
        "sensor_id":       sensor.sensor_id,
        "sensor_name":     sensor.name,
        "sensor_location": sensor.location,
        "sensor_online":   True,
        "distance":        reading.distance,
        "water_level":     reading.water_level,
        "alert_level":     reading.alert_level,
        "alert_label":     reading.alert_label,
        "timestamp":       reading.timestamp.isoformat(),
    })


def _process_alert(app: Flask, sensor: Sensor, reading: Reading) -> None:
    """Create an Alert record, emit to dashboard, then dispatch SMS + email in background."""
    sensor_id   = sensor.sensor_id
    alert_level = reading.alert_level
    now         = datetime.now(timezone.utc)

    cooldown = app.config.get("ALERT_COOLDOWN_SECONDS", 300)
    last     = _ALERT_COOLDOWN.get(sensor_id)
    if last and (now - last).total_seconds() < cooldown:
        logger.debug("Alert cooldown active for sensor %s", sensor_id)
        return

    _ALERT_COOLDOWN[sensor_id] = now
    alert_type = ALERT_LABELS.get(alert_level, "WARNING")
    message    = (
        f"{alert_type} at {sensor.name} ({sensor.location}). "
        f"Water level: {reading.water_level:.1f} cm."
    )

    # Persist and broadcast immediately so the dashboard updates without waiting
    # for the email/SMS round-trip.
    alert = Alert(
        sensor_id=sensor_id,
        alert_type=alert_type,
        message=message,
        water_level=reading.water_level,
    )
    db.session.add(alert)
    db.session.commit()
    socketio.emit("new_alert", alert.to_dict())
    logger.warning("ALERT %s — %s", alert_type, message)

    # Capture values needed by the thread before the request context closes.
    alert_id  = alert.id
    location  = sensor.location or "Unknown"
    wl        = reading.water_level

    def _dispatch_notifications():
        with app.app_context():
            try:
                sms_ok   = send_sms_alert(sensor_id, location, wl, alert_level)
                email_ok = send_email_alert(sensor_id, location, wl, alert_level)
                # Update the flags on the persisted alert record.
                a = db.session.get(Alert, alert_id)
                if a:
                    a.sms_sent   = sms_ok
                    a.email_sent = email_ok
                    db.session.commit()
            except Exception as exc:
                logger.error("Notification dispatch error: %s", exc)

    threading.Thread(target=_dispatch_notifications, daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
#  Entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    env = os.environ.get("FLASK_ENV", "development")
    app = create_app(env)
    socketio.run(app, host="0.0.0.0", port=5000, debug=app.config["DEBUG"])
