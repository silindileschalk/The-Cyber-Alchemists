"""
Solar Tracker — Database Layer (EPG317E Capstone)
==================================================
Built with SQLAlchemy ORM following the patterns from the
"Introduction to SQLAlchemy: Storing & Analysing Sensor Data" module notes.

Tables
------
  sensor_readings   — time-series telemetry from the ESP32
  control_commands  — log of every command sent to the ESP32
  system_events     — connection, alerts, and error logs
  users             — who can access the dashboard
  sessions          — active login sessions per user

Switching databases (change ONE line)
--------------------------------------
  SQLite  (local):      DATABASE_URL = "sqlite:///solar_data.db"
  PostgreSQL (online):  DATABASE_URL = "postgresql://user:password@host:5432/solar_db"
  MySQL (online):       DATABASE_URL = "mysql+pymysql://user:password@host:3306/solar_db"

Dependencies
------------
  pip install sqlalchemy pandas matplotlib seaborn
  For PostgreSQL: pip install psycopg2-binary
  For MySQL:      pip install pymysql
"""

import os
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import (
    Boolean, Column, DateTime, Float,
    ForeignKey, Integer, String, Text,
    create_engine, event, func
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

# ─────────────────────────────────────────────────────────────
# CONNECTION — change this ONE line to go online
# ─────────────────────────────────────────────────────────────
DATABASE_URL = "sqlite:///solar_data.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite only — remove for Postgres/MySQL
    echo=False,  # Set True to print every SQL statement (useful for debugging)
)

# Enable foreign key enforcement for SQLite (disabled by default)
@event.listens_for(engine, "connect")
def enable_sqlite_fks(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

# Base class — all table classes inherit from this (matches lecture notes pattern)
Base = declarative_base()


# ─────────────────────────────────────────────────────────────
# TABLE 1: SENSOR READINGS
# Extended from the lecture notes SensorReading class.
# Added: servo_pan, servo_tilt, battery to match the ESP32 payload.
# ─────────────────────────────────────────────────────────────
class SensorReading(Base):
    """
    One row = one timestamped snapshot of all ESP32 sensor values.
    Matches the pattern from EPG317E lecture notes, extended for
    the full solar tracker payload.
    """
    __tablename__ = "sensor_readings"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    timestamp   = Column(DateTime, nullable=False, default=datetime.utcnow)
    temperature = Column(Float, nullable=False)
    humidity    = Column(Float, nullable=False)
    light       = Column(Float, nullable=False)       # Lux
    servo_pan   = Column(Float, nullable=True)        # Pan angle (0–180°)
    servo_tilt  = Column(Float, nullable=True)        # Tilt angle (0–90°)
    battery     = Column(Float, nullable=True)        # Battery voltage (V)

    def __repr__(self):
        return (
            f"<Reading {self.timestamp:%Y-%m-%d %H:%M} | "
            f"T={self.temperature}°C, H={self.humidity}%RH, "
            f"L={self.light} lux, Pan={self.servo_pan}°, "
            f"Tilt={self.servo_tilt}°, Bat={self.battery}V>"
        )


# ─────────────────────────────────────────────────────────────
# TABLE 2: CONTROL COMMANDS
# Logs every command sent from the dashboard to the ESP32.
# ─────────────────────────────────────────────────────────────
class ControlCommand(Base):
    """
    One row = one MQTT command published to the ESP32.
    Links to the user who sent it so you can audit who changed what.
    """
    __tablename__ = "control_commands"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    timestamp    = Column(DateTime, nullable=False, default=datetime.utcnow)
    topic_key    = Column(String(100), nullable=False)   # e.g. "servo_pan", "tracking_mode"
    payload      = Column(String(255), nullable=False)   # e.g. "90", "AUTO"
    sent_by      = Column(String(100), nullable=True)    # Username of operator
    acknowledged = Column(Boolean, default=False)        # Did the ESP32 confirm receipt?

    def __repr__(self):
        return (
            f"<Command {self.timestamp:%Y-%m-%d %H:%M} | "
            f"{self.topic_key}={self.payload} by {self.sent_by}>"
        )


# ─────────────────────────────────────────────────────────────
# TABLE 3: SYSTEM EVENTS
# Captures MQTT connections, disconnections, threshold alerts,
# and any errors that occur during operation.
# ─────────────────────────────────────────────────────────────
class SystemEvent(Base):
    """
    One row = one notable system event.
    Use event_type to categorise and severity to prioritise.
    """
    __tablename__ = "system_events"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    timestamp  = Column(DateTime, nullable=False, default=datetime.utcnow)
    event_type = Column(String(50),  nullable=False)   # "connection" | "alert" | "error" | "info"
    severity   = Column(String(20),  nullable=False)   # "info" | "warning" | "critical"
    message    = Column(Text,        nullable=False)    # Human-readable description

    def __repr__(self):
        return (
            f"<Event {self.timestamp:%Y-%m-%d %H:%M} | "
            f"[{self.severity.upper()}] {self.event_type}: {self.message[:60]}>"
        )


# ─────────────────────────────────────────────────────────────
# TABLE 4: USERS
# Tracks who can log into the dashboard and what they can do.
# Roles: admin (full access), operator (view + control), viewer (read-only)
# ─────────────────────────────────────────────────────────────
class User(Base):
    """
    One row = one dashboard user account.
    """
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(String(80),  unique=True, nullable=False)
    email         = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)   # Never store plain-text passwords
    role          = Column(String(20),  nullable=False, default="viewer")
    created_at    = Column(DateTime, default=datetime.utcnow)
    is_active     = Column(Boolean, default=True)

    # Relationship — makes it easy to get all sessions for a user
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username} | role={self.role}, active={self.is_active}>"


# ─────────────────────────────────────────────────────────────
# TABLE 5: SESSIONS
# Tracks active logins. One user can have multiple sessions
# (e.g. logged in from two different browsers).
# ─────────────────────────────────────────────────────────────
class Session(Base):
    """
    One row = one active login session for a user.
    """
    __tablename__ = "sessions"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    token      = Column(String(255), unique=True, nullable=False)   # Auth token
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    ip_address = Column(String(45), nullable=True)    # Supports IPv6 (max 45 chars)
    is_active  = Column(Boolean, default=True)

    # Relationship — gives back the User object from a Session
    user = relationship("User", back_populates="sessions")

    def __repr__(self):
        return (
            f"<Session user_id={self.user_id} | "
            f"active={self.is_active}, expires={self.expires_at:%Y-%m-%d %H:%M}>"
        )


# ─────────────────────────────────────────────────────────────
# CREATE ALL TABLES
# ─────────────────────────────────────────────────────────────
Base.metadata.create_all(engine)

# Create a session factory (matches lecture notes pattern)
Session_factory = sessionmaker(bind=engine)
session = Session_factory()

print("✅ Solar Tracker database initialised successfully.")
print(f"   Location: {os.path.abspath('solar_data.db')}")


# ─────────────────────────────────────────────────────────────
# WRITE HELPERS
# Based on Exercise 4 from lecture notes:
# "Write a function store_mqtt_reading(session, payload)…"
# ─────────────────────────────────────────────────────────────
def store_mqtt_reading(payload: dict) -> None:
    """
    Insert one MQTT sensor payload into sensor_readings.

    Usage:
        store_mqtt_reading({
            "temperature": 24.1,
            "humidity":    60.2,
            "light":       8500,
            "servo_pan":   90,
            "servo_tilt":  45,
            "battery":     3.7,
        })
    """
    reading = SensorReading(
        timestamp   = datetime.now(),
        temperature = payload.get("temperature"),
        humidity    = payload.get("humidity"),
        light       = payload.get("light"),
        servo_pan   = payload.get("servo_pan"),
        servo_tilt  = payload.get("servo_tilt"),
        battery     = payload.get("battery"),
    )
    session.add(reading)
    session.commit()


def log_command(topic_key: str, payload: str, sent_by: str = "system") -> None:
    """Log a control command that was published to the ESP32."""
    cmd = ControlCommand(
        timestamp = datetime.now(),
        topic_key = topic_key,
        payload   = payload,
        sent_by   = sent_by,
    )
    session.add(cmd)
    session.commit()


def log_event(event_type: str, severity: str, message: str) -> None:
    """
    Log a system event.
    event_type: "connection" | "alert" | "error" | "info"
    severity:   "info" | "warning" | "critical"
    """
    evt = SystemEvent(
        timestamp  = datetime.now(),
        event_type = event_type,
        severity   = severity,
        message    = message,
    )
    session.add(evt)
    session.commit()


# ─────────────────────────────────────────────────────────────
# QUERY HELPERS
# Following the querying patterns from the lecture notes.
# ─────────────────────────────────────────────────────────────
def get_recent_readings(limit: int = 20):
    """Return the last N sensor readings (newest first)."""
    return (
        session.query(SensorReading)
        .order_by(SensorReading.timestamp.desc())
        .limit(limit)
        .all()
    )


def get_hot_readings(threshold: float = 30.0):
    """Return all readings where temperature exceeds the threshold."""
    return (
        session.query(SensorReading)
        .filter(SensorReading.temperature > threshold)
        .order_by(SensorReading.timestamp)
        .all()
    )


def get_readings_by_date_range(start: datetime, end: datetime):
    """Return all readings between two datetime objects."""
    return (
        session.query(SensorReading)
        .filter(SensorReading.timestamp >= start)
        .filter(SensorReading.timestamp < end)
        .order_by(SensorReading.timestamp)
        .all()
    )


def get_readings_last_n_hours(hours: int = 1):
    """Return readings from the last N hours — used by the dashboard time filter."""
    cutoff = datetime.now() - timedelta(hours=hours)
    return (
        session.query(SensorReading)
        .filter(SensorReading.timestamp >= cutoff)
        .order_by(SensorReading.timestamp)
        .all()
    )


def get_summary_stats():
    """
    Return min / avg / max for temperature, humidity, light.
    Matches the aggregation example from the lecture notes.
    """
    stats = session.query(
        func.min(SensorReading.temperature).label("temp_min"),
        func.avg(SensorReading.temperature).label("temp_avg"),
        func.max(SensorReading.temperature).label("temp_max"),
        func.min(SensorReading.humidity).label("humid_min"),
        func.avg(SensorReading.humidity).label("humid_avg"),
        func.max(SensorReading.humidity).label("humid_max"),
        func.min(SensorReading.light).label("light_min"),
        func.avg(SensorReading.light).label("light_avg"),
        func.max(SensorReading.light).label("light_max"),
    ).one()
    return stats


def get_command_history(limit: int = 50):
    """Return the last N control commands sent to the ESP32."""
    return (
        session.query(ControlCommand)
        .order_by(ControlCommand.timestamp.desc())
        .limit(limit)
        .all()
    )


def get_critical_events():
    """Return all critical severity system events."""
    return (
        session.query(SystemEvent)
        .filter(SystemEvent.severity == "critical")
        .order_by(SystemEvent.timestamp.desc())
        .all()
    )


# ─────────────────────────────────────────────────────────────
# PANDAS INTEGRATION
# Loading query results into DataFrames for analysis and plotting,
# as shown in Section 6 of the lecture notes.
# ─────────────────────────────────────────────────────────────
def load_all_readings_to_df() -> pd.DataFrame:
    """
    Load all sensor readings into a Pandas DataFrame.
    Matches lecture notes pattern using pd.read_sql().
    """
    df = pd.read_sql(
        "SELECT * FROM sensor_readings ORDER BY timestamp",
        engine,
        parse_dates=["timestamp"]
    )
    return df


def load_readings_last_n_hours_to_df(hours: int = 24) -> pd.DataFrame:
    """Load only recent readings into a DataFrame — lighter than loading everything."""
    cutoff = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    query  = "SELECT * FROM sensor_readings WHERE timestamp >= ? ORDER BY timestamp"
    df = pd.read_sql(query, engine, params=(cutoff,), parse_dates=["timestamp"])
    return df


def load_commands_to_df() -> pd.DataFrame:
    """Load all control commands into a Pandas DataFrame."""
    return pd.read_sql("SELECT * FROM control_commands ORDER BY timestamp", engine)


def load_events_to_df() -> pd.DataFrame:
    """Load all system events into a Pandas DataFrame."""
    return pd.read_sql("SELECT * FROM system_events ORDER BY timestamp", engine)


# ─────────────────────────────────────────────────────────────
# SIMULATION: SEED DATA FOR TESTING
# Generates 7 days of realistic ESP32 readings (672 rows)
# matching the bulk insert example in the lecture notes.
# Run this once to populate the database before testing the dashboard.
# ─────────────────────────────────────────────────────────────
def seed_test_data(days: int = 7) -> None:
    """
    Generate simulated sensor data for testing.
    Mirrors the sinusoidal temperature, humidity, and bell-curve
    lux model from the lecture notes bulk insert example.
    """
    import numpy as np

    print(f"Seeding {days} days of test data...")
    np.random.seed(42)

    start    = datetime.now() - timedelta(days=days)
    n_points = days * 24 * 4  # 15-minute intervals
    timestamps = [start + timedelta(minutes=15 * i) for i in range(n_points)]

    readings = []
    for ts in timestamps:
        hour = ts.hour + ts.minute / 60.0

        # Temperature: daily sinusoidal cycle (18–32°C)
        temp  = 25 + 7 * __import__("math").sin(2 * __import__("math").pi * (hour - 6) / 24)
        temp += np.random.normal(0, 0.5)

        # Humidity: inversely related to temperature
        humid = 85 - 0.8 * (temp - 18) + np.random.normal(0, 2)
        humid = float(np.clip(humid, 30, 95))

        # Light: bell curve during daytime, near zero at night
        if 6 <= hour <= 18:
            lux = 50000 * __import__("math").exp(-0.5 * ((hour - 12) / 2.5) ** 2)
            lux = max(lux + np.random.normal(0, 500), 0)
        else:
            lux = float(np.random.uniform(0, 5))

        # Servo: slowly sweeping pan, gentle tilt
        pan  = 90 + 45 * __import__("math").sin(2 * __import__("math").pi * hour / 12)
        tilt = 45 + 20 * __import__("math").sin(2 * __import__("math").pi * hour / 24)

        # Battery: slow discharge with midday solar recharge
        battery = round(3.5 + 0.3 * __import__("math").sin(2 * __import__("math").pi * (hour - 14) / 24), 2)

        readings.append(SensorReading(
            timestamp   = ts,
            temperature = round(temp, 2),
            humidity    = round(humid, 2),
            light       = round(lux, 2),
            servo_pan   = round(pan, 1),
            servo_tilt  = round(tilt, 1),
            battery     = battery,
        ))

    session.bulk_save_objects(readings)
    session.commit()

    total = session.query(SensorReading).count()
    print(f"✅ Seed complete. Total readings in database: {total}")


# ─────────────────────────────────────────────────────────────
# QUICK DEMO — runs when you execute: python database.py
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # 1. Seed the database with test data
    if session.query(SensorReading).count() == 0:
        seed_test_data(days=7)

    # 2. Load into DataFrame and show summary (matches lecture notes Section 6)
    df = load_all_readings_to_df()
    print(f"\nShape: {df.shape}")
    print(f"Date range: {df['timestamp'].min()} → {df['timestamp'].max()}")
    print()
    print(df.describe().round(2))

    # 3. Summary statistics (matches lecture notes aggregation example)
    stats = get_summary_stats()
    print("\n=== Summary Statistics ===")
    print(f"  Temperature:  {stats.temp_min:.1f} / {stats.temp_avg:.1f} / {stats.temp_max:.1f} °C")
    print(f"  Humidity:     {stats.humid_min:.1f} / {stats.humid_avg:.1f} / {stats.humid_max:.1f} %RH")
    print(f"  Light:        {stats.light_min:.0f} / {stats.light_avg:.0f} / {stats.light_max:.0f} lux")

    # 4. Filter: hot readings above 30°C (matches lecture notes filtering example)
    hot = get_hot_readings(threshold=30.0)
    print(f"\nReadings above 30°C: {len(hot)}")
    for r in hot[:5]:
        print(f"  {r.timestamp:%Y-%m-%d %H:%M}  →  {r.temperature}°C")

    # 5. Log a sample command and event
    log_command("tracking_mode", "AUTO", sent_by="admin")
    log_event("connection", "info", "MQTT connected to broker.hivemq.com")
    print("\n✅ Sample command and event logged.")

    session.close()
