"""
SQLAlchemy ORM models for the Flood Monitoring System.
"""
from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def _utcnow():
    """Return current UTC time as a naive datetime (SQLite-compatible)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model):
    """System users with role-based access control."""
    __tablename__ = "users"

    id                   = db.Column(db.Integer, primary_key=True)
    username             = db.Column(db.String(64),  unique=True, nullable=False, index=True)
    email                = db.Column(db.String(120), unique=True, nullable=False)
    phone                = db.Column(db.String(25),  nullable=True)
    password_hash        = db.Column(db.String(256), nullable=False)
    # roles: admin | operator | viewer
    role                 = db.Column(db.String(20),  default="viewer", nullable=False)
    is_active            = db.Column(db.Boolean,     default=True)
    # Security: force password change on first login (set True for seeded admin)
    must_change_password = db.Column(db.Boolean,     default=False)
    # Account lockout after repeated failed logins
    failed_login_count   = db.Column(db.Integer,     default=0, nullable=False)
    locked_until         = db.Column(db.DateTime,    nullable=True)

    created_at           = db.Column(db.DateTime,    default=_utcnow)
    last_login           = db.Column(db.DateTime,    nullable=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    @property
    def is_locked(self) -> bool:
        if self.locked_until is None:
            return False
        return _utcnow() < self.locked_until

    def to_dict(self) -> dict:
        return {
            "id":                   self.id,
            "username":             self.username,
            "email":                self.email,
            "phone":                self.phone,
            "role":                 self.role,
            "is_active":            self.is_active,
            "must_change_password": self.must_change_password,
            "created_at":           self.created_at.isoformat(),
            "last_login":           self.last_login.isoformat() if self.last_login else None,
        }


class Sensor(db.Model):
    """Registered IoT sensor nodes."""
    __tablename__ = "sensors"

    id             = db.Column(db.Integer, primary_key=True)
    sensor_id      = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name           = db.Column(db.String(100), nullable=False)
    location       = db.Column(db.String(200), nullable=True)
    latitude       = db.Column(db.Float, nullable=True)
    longitude      = db.Column(db.Float, nullable=True)
    sensor_height  = db.Column(db.Float, default=300.0)
    is_active      = db.Column(db.Boolean, default=True)
    last_seen      = db.Column(db.DateTime, nullable=True)
    created_at     = db.Column(db.DateTime, default=_utcnow)

    readings = db.relationship("Reading", backref="sensor", lazy="dynamic")
    alerts   = db.relationship("Alert",   backref="sensor", lazy="dynamic")

    @property
    def online(self) -> bool:
        """Sensor is considered online if last seen within 2 minutes."""
        if not self.last_seen:
            return False
        return (_utcnow() - self.last_seen).total_seconds() < 120

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "sensor_id":     self.sensor_id,
            "name":          self.name,
            "location":      self.location,
            "latitude":      self.latitude,
            "longitude":     self.longitude,
            "sensor_height": self.sensor_height,
            "is_active":     self.is_active,
            "online":        self.online,
            "last_seen":     self.last_seen.isoformat() if self.last_seen else None,
            "created_at":    self.created_at.isoformat(),
        }


class Reading(db.Model):
    """Water-level data points recorded by sensors."""
    __tablename__ = "readings"

    id          = db.Column(db.Integer, primary_key=True)
    sensor_id   = db.Column(db.String(50), db.ForeignKey("sensors.sensor_id"),
                            nullable=False, index=True)
    distance    = db.Column(db.Float, nullable=False)
    water_level = db.Column(db.Float, nullable=False)
    alert_level = db.Column(db.Integer, default=1)
    rssi        = db.Column(db.Integer, nullable=True)
    timestamp   = db.Column(db.DateTime, default=_utcnow, index=True)

    @property
    def alert_label(self) -> str:
        return {1: "SAFE", 2: "WARNING", 3: "DANGER"}.get(self.alert_level, "UNKNOWN")

    def to_dict(self) -> dict:
        return {
            "id":          self.id,
            "sensor_id":   self.sensor_id,
            "distance":    round(self.distance,    2),
            "water_level": round(self.water_level, 2),
            "alert_level": self.alert_level,
            "alert_label": self.alert_label,
            "rssi":        self.rssi,
            "timestamp":   self.timestamp.isoformat(),
        }


class Alert(db.Model):
    """Alert events generated when thresholds are exceeded."""
    __tablename__ = "alerts"

    id               = db.Column(db.Integer, primary_key=True)
    sensor_id        = db.Column(db.String(50), db.ForeignKey("sensors.sensor_id"),
                                 nullable=False, index=True)
    alert_type       = db.Column(db.String(20), nullable=False)
    message          = db.Column(db.Text, nullable=False)
    water_level      = db.Column(db.Float, nullable=True)
    is_resolved      = db.Column(db.Boolean, default=False)
    sms_sent         = db.Column(db.Boolean, default=False)
    email_sent       = db.Column(db.Boolean, default=False)
    created_at       = db.Column(db.DateTime, default=_utcnow, index=True)
    resolved_at      = db.Column(db.DateTime, nullable=True)
    acknowledged_by  = db.Column(db.String(64), nullable=True)

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "sensor_id":        self.sensor_id,
            "alert_type":       self.alert_type,
            "message":          self.message,
            "water_level":      self.water_level,
            "is_resolved":      self.is_resolved,
            "sms_sent":         self.sms_sent,
            "email_sent":       self.email_sent,
            "created_at":       self.created_at.isoformat(),
            "resolved_at":      self.resolved_at.isoformat() if self.resolved_at else None,
            "acknowledged_by":  self.acknowledged_by,
        }


class AuditLog(db.Model):
    """Immutable security audit trail for all significant events."""
    __tablename__ = "audit_logs"

    id         = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50), nullable=False, index=True)
    user       = db.Column(db.String(64), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    details    = db.Column(db.Text, nullable=True)
    timestamp  = db.Column(db.DateTime, default=_utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id":         self.id,
            "event_type": self.event_type,
            "user":       self.user,
            "ip_address": self.ip_address,
            "details":    self.details,
            "timestamp":  self.timestamp.isoformat(),
        }
