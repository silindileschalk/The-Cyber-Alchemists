"""
Solar Tracker — Database Layer (EPG317E Capstone)
==================================================
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
# ─────────────────────────────────────────────────────────────
class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    timestamp   = Column(DateTime, nullable=False, default=datetime.utcnow)
    temperature = Column(Float, nullable=False)
    humidity    = Column(Float, nullable=False)
    light       = Column(Float, nullable=False)
    servo_pan   = Column(Float, nullable=True)
    servo_tilt  = Column(Float, nullable=True)
    battery     = Column(Float, nullable=True)

    def __repr__(self):
        return (
            f"<Reading {self.timestamp:%Y-%m-%d %H:%M} | "
            f"T={self.temperature}°C, H={self.humidity}%RH, "
            f"L={self.light} lux, Pan={self.servo_pan}°, "
            f"Tilt={self.servo_tilt}°, Bat={self.battery}V>"
        )


# ─────────────────────────────────────────────────────────────
# TABLE 2: CONTROL COMMANDS
# ─────────────────────────────────────────────────────────────
class ControlCommand(Base):
    __tablename__ = "control_commands"

    id           = Column(Integer, primary_key=True, autoincrement=True)
    timestamp    = Column(DateTime, nullable=False, default=datetime.utcnow)
    topic_key    = Column(String(100), nullable=False)
    payload      = Column(String(255), nullable=False)
    sent_by      = Column(String(100), nullable=True)
    acknowledged = Column(Boolean, default=False)

    def __repr__(self):
        return (
            f"<Command {self.timestamp:%Y-%m-%d %H:%M} | "
            f"{self.topic_key}={self.payload} by {self.sent_by}>"
        )


# ─────────────────────────────────────────────────────────────
# TABLE 3: SYSTEM EVENTS
# ─────────────────────────────────────────────────────────────
class SystemEvent(Base):
    __tablename__ = "system_events"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    timestamp  = Column(DateTime, nullable=False, default=datetime.utcnow)
    event_type = Column(String(50),  nullable=False)
    severity   = Column(String(20),  nullable=False)
    message    = Column(Text,        nullable=False)

    def __repr__(self):
        return (
            f"<Event {self.timestamp:%Y-%m-%d %H:%M} | "
            f"[{self.severity.upper()}] {self.event_type}: {self.message[:60]}>"
        )


# ─────────────────────────────────────────────────────────────
# TABLE 4: USERS
# ─────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, autoincrement=True)
    username      = Column(String(80),  unique=True, nullable=False)
    email         = Column(String(120), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role          = Column(String(20),  nullable=False, default="viewer")
    created_at    = Column(DateTime, default=datetime.utcnow)
    is_active     = Column(Boolean, default=True)

    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User {self.username} | role={self.role}, active={self.is_active}>"


# ─────────────────────────────────────────────────────────────
# TABLE 5: SESSIONS
# ─────────────────────────────────────────────────────────────
class Session(Base):
    __tablename__ = "sessions"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    token      = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    ip_address = Column(String(45), nullable=True)
    is_active  = Column(Boolean, default=True)

    user = relationship("User", back_populates="sessions")

    def __repr__(self):
        return (
            f"<Session user_id={self.user_id} | "
            f"active={self.is_active}, expires={self.expires_at:%Y-%m-%d %H:%M}>"
        )


# ─────────────────────────────────────────────────────────────
# CREATE ALL TABLES  ← must happen before any queries
# ─────────────────────────────────────────────────────────────
Base.metadata.create_all(engine)

# Create a session factory
Session_factory = sessionmaker(bind=engine)
session = Session_factory()

print("✅ Solar Tracker database initialised successfully.")
print(f"   Location: {os.path.abspath('solar_data.db')}")


# ─────────────────────────────────────────────────────────────
# WRITE HELPERS
# ─────────────────────────────────────────────────────────────
def store_mqtt_reading(payload: dict) -> None:
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
    cmd = ControlCommand(
        timestamp = datetime.now(),
        topic_key = topic_key,
        payload   = payload,
        sent_by   = sent_by,
    )
    session.add(cmd)
    session.commit()


def log_event(event_type: str, severity: str, message: str) -> None:
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
# ─────────────────────────────────────────────────────────────
def get_recent_readings(limit: int = 20):
    return (
        session.query(SensorReading)
        .order_by(SensorReading.timestamp.desc())
        .limit(limit)
        .all()
    )


def get_hot_readings(threshold: float = 30.0):
    return (
        session.query(SensorReading)
        .filter(SensorReading.temperature > threshold)
        .order_by(SensorReading.timestamp)
        .all()
    )


def get_readings_by_date_range(start: datetime, end: datetime):
    return (
        session.query(SensorReading)
        .filter(SensorReading.timestamp >= start)
        .filter(SensorReading.timestamp < end)
        .order_by(SensorReading.timestamp)
        .all()
    )


def get_readings_last_n_hours(hours: int = 1):
    cutoff = datetime.now() - timedelta(hours=hours)
    return (
        session.query(SensorReading)
        .filter(SensorReading.timestamp >= cutoff)
        .order_by(SensorReading.timestamp)
        .all()
    )


def get_summary_stats():
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
    return (
        session.query(ControlCommand)
        .order_by(ControlCommand.timestamp.desc())
        .limit(limit)
        .all()
    )


def get_critical_events():
    return (
        session.query(SystemEvent)
        .filter(SystemEvent.severity == "critical")
        .order_by(SystemEvent.timestamp.desc())
        .all()
    )


# ─────────────────────────────────────────────────────────────
# PANDAS INTEGRATION
# ─────────────────────────────────────────────────────────────
def load_all_readings_to_df() -> pd.DataFrame:
    df = pd.read_sql(
        "SELECT * FROM sensor_readings ORDER BY timestamp",
        engine,
        parse_dates=["timestamp"]
    )
    return df


def load_readings_last_n_hours_to_df(hours: int = 24) -> pd.DataFrame:
    from sqlalchemy import text
    cutoff = datetime.now() - timedelta(hours=hours)
    query  = text(
        "SELECT * FROM sensor_readings WHERE timestamp >= :cutoff ORDER BY timestamp"
    )
    with engine.connect() as conn:
        df = pd.read_sql(query, conn, params={"cutoff": cutoff}, parse_dates=["timestamp"])
    return df


def load_commands_to_df() -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM control_commands ORDER BY timestamp", engine)


def load_events_to_df() -> pd.DataFrame:
    return pd.read_sql("SELECT * FROM system_events ORDER BY timestamp", engine)


# ─────────────────────────────────────────────────────────────
# SEED DATA
# ─────────────────────────────────────────────────────────────
def seed_existing_data():
    print('Seeding database with preserved data...')

    reading_data = [
        ('2026-05-12 06:05:36.831705', 34.5, 30.4, 25785.6, 94.0, 48.0, 3.57),
        ('2026-05-12 06:05:42.604805', 24.9, 32.3, 65256.6, 98.0, 49.0, 3.74),
        ('2026-05-12 06:05:51.591697', 31.8, 60.1, 70065.6, 101.0, 51.0, 3.59),
        ('2026-05-12 06:06:01.670224', 30.2, 61.6, 12379.1, 103.0, 53.0, 4.03),
        ('2026-05-12 06:06:12.745980', 32.7, 33.8, 61096.2, 107.0, 56.0, 4.12),
        ('2026-05-12 06:06:27.343716', 33.7, 51.4, 6317.0, 111.0, 58.0, 3.68),
        ('2026-05-12 06:06:42.051108', 36.2, 35.1, 52178.4, 112.0, 59.0, 4.03),
        ('2026-05-12 06:06:58.854288', 29.9, 55.8, 68893.7, 116.0, 61.0, 3.87),
        ('2026-05-12 06:07:08.574739', 23.3, 64.5, 28029.4, 120.0, 63.0, 3.76),
        ('2026-05-12 06:07:22.190972', 32.9, 60.4, 12261.5, 122.0, 64.0, 3.81),
        ('2026-05-12 06:07:43.294990', 28.3, 66.5, 52459.6, 126.0, 66.0, 3.44),
        ('2026-05-12 06:08:00.120460', 34.9, 45.9, 48118.9, 129.0, 69.0, 3.51),
        ('2026-05-12 06:08:21.211004', 31.8, 36.9, 14747.7, 130.0, 70.0, 3.63),
        ('2026-05-12 06:09:02.796303', 35.6, 42.6, 17155.7, 134.0, 72.0, 3.47),
        ('2026-05-12 06:09:23.580424', 26.9, 67.3, 49447.0, 135.0, 75.0, 3.45),
        ('2026-05-12 06:09:40.771672', 32.4, 32.1, 48048.5, 139.0, 77.0, 3.65),
        ('2026-05-12 06:10:05.516796', 37.6, 63.2, 36169.1, 143.0, 79.0, 3.83),
        ('2026-05-12 06:10:18.174666', 37.0, 57.6, 60907.5, 146.0, 82.0, 4.02),
        ('2026-05-12 06:10:31.843314', 35.7, 42.1, 19685.9, 149.0, 83.0, 4.13),
        ('2026-05-12 06:10:44.938314', 34.0, 34.9, 53554.4, 152.0, 86.0, 3.83),
        ('2026-05-12 06:10:54.746406', 32.3, 54.2, 12004.6, 155.0, 88.0, 3.57),
        ('2026-05-12 06:11:07.014191', 29.2, 51.1, 53888.9, 157.0, 90.0, 3.7),
        ('2026-05-12 06:11:26.415216', 29.1, 66.5, 59988.2, 158.0, 88.0, 4.01),
        ('2026-05-12 06:11:46.519640', 32.3, 32.5, 42779.9, 162.0, 86.0, 4.07),
        ('2026-05-12 06:12:00.250283', 35.5, 69.5, 58345.4, 165.0, 85.0, 3.79),
        ('2026-05-12 06:12:20.409406', 30.0, 46.6, 16252.4, 167.0, 84.0, 3.99),
        ('2026-05-12 06:12:34.482570', 31.1, 55.5, 60706.9, 171.0, 83.0, 4.09),
        ('2026-05-12 06:12:45.618412', 32.3, 64.7, 65868.9, 173.0, 80.0, 4.04),
        ('2026-05-12 06:12:55.121758', 28.3, 39.2, 54093.8, 175.0, 78.0, 3.67),
        ('2026-05-12 06:13:06.543729', 31.4, 51.7, 64269.1, 176.0, 76.0, 4.17),
        ('2026-05-12 06:13:24.594008', 23.4, 34.5, 14987.6, 179.0, 75.0, 3.7),
        ('2026-05-12 06:13:39.419218', 30.9, 41.0, 48411.5, 180.0, 74.0, 3.84),
        ('2026-05-12 06:13:53.514105', 22.9, 34.6, 60497.4, 176.0, 73.0, 4.07),
        ('2026-05-12 06:14:03.075958', 24.3, 49.7, 59491.7, 174.0, 72.0, 3.86),
        ('2026-05-12 06:14:15.562136', 23.6, 43.8, 11960.9, 172.0, 71.0, 4.12),
        ('2026-05-12 06:14:28.971489', 32.4, 58.4, 41026.0, 171.0, 69.0, 3.93),
        ('2026-05-12 06:14:41.000999', 35.2, 37.5, 39200.0, 170.0, 68.0, 4.1),
        ('2026-05-12 06:14:53.158999', 22.0, 66.8, 65398.7, 166.0, 65.0, 3.57),
        ('2026-05-12 06:15:13.211623', 26.1, 68.6, 22625.0, 165.0, 62.0, 4.08),
        ('2026-05-12 06:15:32.881285', 22.1, 41.4, 76770.6, 161.0, 60.0, 3.88),
        ('2026-05-12 06:16:01.529788', 29.5, 46.6, 63401.9, 158.0, 59.0, 4.03),
        ('2026-05-12 06:16:37.465497', 22.1, 54.5, 75827.5, 157.0, 56.0, 3.52),
        ('2026-05-12 06:17:01.940780', 35.0, 60.6, 76807.0, 155.0, 55.0, 3.59),
        ('2026-05-12 06:17:17.813149', 24.4, 57.3, 20102.2, 151.0, 52.0, 3.42),
        ('2026-05-12 06:17:34.885646', 23.5, 46.5, 15077.9, 148.0, 51.0, 3.65),
        ('2026-05-12 06:17:49.074127', 30.4, 56.6, 11687.3, 146.0, 49.0, 4.07),
        ('2026-05-12 06:17:59.727206', 30.7, 41.1, 19636.1, 144.0, 47.0, 3.82),
        ('2026-05-12 06:18:17.961821', 35.1, 62.8, 63451.8, 141.0, 46.0, 4.07),
        ('2026-05-12 06:18:29.689940', 30.7, 37.3, 14503.2, 140.0, 43.0, 3.7),
        ('2026-05-12 06:18:41.831917', 26.6, 33.2, 74236.4, 136.0, 42.0, 4.13),
        ('2026-05-12 06:18:52.051175', 36.0, 50.6, 35151.3, 135.0, 41.0, 3.7),
        ('2026-05-12 06:18:59.430755', 25.0, 67.1, 17845.5, 132.0, 38.0, 4.04),
        ('2026-05-12 06:19:06.607186', 22.9, 43.0, 42223.7, 128.0, 36.0, 3.41),
        ('2026-05-12 06:19:14.886716', 32.3, 54.7, 59810.7, 124.0, 33.0, 3.43),
        ('2026-05-12 06:19:27.412425', 35.1, 52.3, 23265.3, 120.0, 32.0, 4.06),
        ('2026-05-12 06:19:36.881978', 23.3, 54.4, 47873.4, 116.0, 29.0, 4.15),
        ('2026-05-12 06:19:47.189884', 35.5, 48.8, 59491.9, 112.0, 28.0, 3.82),
        ('2026-05-12 06:19:57.044685', 22.2, 58.8, 42352.8, 108.0, 27.0, 3.59),
        ('2026-05-12 06:20:07.360763', 29.3, 38.8, 50612.4, 104.0, 24.0, 4.11),
        ('2026-05-12 06:20:17.615491', 32.5, 37.7, 12312.2, 100.0, 23.0, 3.69),
        ('2026-05-12 06:20:27.171679', 33.6, 35.2, 52304.0, 97.0, 21.0, 3.93),
        ('2026-05-12 06:20:36.781680', 37.5, 56.8, 69262.2, 94.0, 19.0, 3.78),
        ('2026-05-12 06:20:45.732570', 28.9, 49.4, 69601.0, 91.0, 16.0, 3.7),
        ('2026-05-12 06:21:15.071713', 37.5, 57.4, 57134.5, 87.0, 12.0, 3.43),
        ('2026-05-12 06:21:29.660180', 23.0, 33.1, 39205.0, 85.0, 11.0, 3.82),
        ('2026-05-12 06:21:39.444203', 24.2, 38.2, 74991.9, 84.0, 9.0, 3.74),
        ('2026-05-12 06:21:47.016246', 23.2, 36.6, 47845.6, 81.0, 6.0, 3.46),
        ('2026-05-12 06:21:55.427483', 36.2, 39.2, 79098.2, 79.0, 3.0, 4.04),
        ('2026-05-12 06:22:03.064380', 32.1, 42.0, 58069.1, 78.0, 1.0, 3.52),
        ('2026-05-12 06:22:13.336975', 25.7, 30.8, 28813.5, 75.0, 0.0, 4.12),
        ('2026-05-12 06:22:22.889823', 36.5, 39.2, 54214.2, 71.0, 1.0, 3.46),
        ('2026-05-12 06:22:32.616456', 34.5, 37.6, 50155.7, 67.0, 4.0, 4.0),
        ('2026-05-12 06:22:42.729594', 24.1, 48.7, 65841.4, 65.0, 5.0, 3.6),
        ('2026-05-12 06:22:53.305937', 25.3, 37.4, 65221.9, 64.0, 8.0, 3.85),
        ('2026-05-12 06:23:05.524634', 24.7, 60.0, 18404.0, 61.0, 11.0, 3.72),
        ('2026-05-12 06:23:22.853236', 37.9, 55.7, 67735.4, 59.0, 12.0, 3.44),
        ('2026-05-12 06:23:53.795212', 25.7, 67.7, 46578.4, 55.0, 14.0, 3.6),
        ('2026-05-12 06:24:02.833277', 32.3, 54.7, 47894.2, 52.0, 15.0, 4.03),
        ('2026-05-12 06:24:10.743211', 31.4, 56.5, 37617.4, 50.0, 17.0, 3.48),
        ('2026-05-12 06:24:20.983064', 28.0, 61.8, 34961.5, 47.0, 20.0, 4.2),
        ('2026-05-12 06:24:29.173319', 29.8, 69.0, 56831.6, 45.0, 22.0, 3.84),
        ('2026-05-12 06:24:38.688209', 31.6, 52.3, 28696.7, 43.0, 25.0, 3.88),
        ('2026-05-12 06:24:47.866904', 27.5, 43.6, 63010.0, 39.0, 27.0, 3.51),
        ('2026-05-12 06:25:25.392773', 35.6, 30.8, 7621.9, 35.0, 28.0, 4.05),
        ('2026-05-12 06:25:41.276979', 31.0, 36.2, 76101.5, 33.0, 29.0, 3.59),
        ('2026-05-12 06:26:03.090442', 30.2, 48.2, 70017.0, 31.0, 31.0, 3.88),
        ('2026-05-12 06:26:09.947833', 35.8, 31.8, 71875.9, 30.0, 32.0, 3.51),
        ('2026-05-12 06:26:17.507991', 27.6, 67.7, 42146.5, 29.0, 34.0, 3.92),
        ('2026-05-12 15:58:53.654600', 23.0, 51.0, 0.0, 18.0, 90.0, 0.1),
        ('2026-05-12 15:59:57.233180', 23.0, 51.0, 46.0, 168.0, 57.0, 0.13),
        ('2026-05-12 16:00:46.073772', 22.0, 52.0, 427.0, 177.0, 39.0, 0.29),
        ('2026-05-12 16:00:58.187012', 23.0, 51.0, 2.0, 180.0, 48.0, 0.09),
        ('2026-05-12 16:01:08.061704', 22.0, 52.0, 394.0, 177.0, 33.0, 0.29),
        ('2026-05-12 16:01:12.541674', 22.0, 52.0, 142.0, 180.0, 39.0, 0.29),
        ('2026-05-12 16:01:15.388533', 23.0, 51.0, 387.0, 177.0, 27.0, 0.3),
        ('2026-05-12 16:01:53.745523', 22.0, 52.0, 273.0, 180.0, 39.0, 0.3),
        ('2026-05-12 16:01:56.641008', 23.0, 51.0, 388.0, 180.0, 30.0, 0.1),
        ('2026-05-12 16:02:16.320647', 22.0, 52.0, 393.0, 174.0, 30.0, 0.29),
        ('2026-05-12 16:02:54.568434', 22.0, 52.0, 391.0, 174.0, 30.0, 0.29),
        ('2026-05-12 16:04:35.080270', 22.0, 52.0, 385.0, 180.0, 30.0, 0.29),
        ('2026-05-12 16:05:37.618196', 22.0, 52.0, 384.0, 180.0, 30.0, 0.3),
        ('2026-05-12 16:08:13.328131', 23.0, 53.0, 155.0, 90.0, 45.0, 0.24),
        ('2026-05-12 16:10:22.401025', 22.0, 52.0, 250.0, 138.0, 0.0, 0.3),
        ('2026-05-13 15:39:14.593277', 20.0, 58.0, 339.0, 102.0, 48.0, 0.0),
        ('2026-05-13 15:40:18.722619', 22.0, 83.0, 108.0, 177.0, 90.0, 0.23),
        ('2026-05-13 15:42:02.707763', 21.0, 55.0, 110.0, 180.0, 90.0, 0.28),
        ('2026-05-13 15:45:11.970801', 22.0, 55.0, 245.0, 100.0, 75.0, 0.26),
        ('2026-05-14 02:03:38.079473', 23.0, 61.0, 1.0, 87.0, 48.0, 0.07),
    ]
    readings = [SensorReading(
        timestamp=pd.to_datetime(row[0]).to_pydatetime(),
        temperature=row[1], humidity=row[2], light=row[3],
        servo_pan=row[4], servo_tilt=row[5], battery=row[6]
    ) for row in reading_data]
    session.bulk_save_objects(readings)

    command_data = [
        ('2026-05-12 05:22:29.716513', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-12 05:25:24.666160', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-12 05:32:35.096990', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-12 05:32:38.904843', 'servo_pan', '29', 'operator', 0),
        ('2026-05-12 05:32:42.644752', 'servo_pan', '109', 'operator', 0),
        ('2026-05-12 05:32:48.592033', 'servo_tilt', '80', 'operator', 0),
        ('2026-05-12 05:39:44.946575', 'led', 'TOGGLE', 'operator', 0),
        ('2026-05-12 05:39:47.612644', 'buzzer', 'TRIGGER', 'operator', 0),
        ('2026-05-12 06:08:51.878426', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-12 06:12:09.819352', 'servo_tilt', '59', 'operator', 0),
        ('2026-05-12 06:26:47.391390', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-12 06:27:26.538052', 'servo_pan', '151', 'operator', 0),
        ('2026-05-12 06:27:32.441118', 'servo_tilt', '61', 'operator', 0),
        ('2026-05-12 06:31:56.045574', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-12 06:32:01.532317', 'servo_pan', '125', 'operator', 0),
        ('2026-05-12 06:38:03.473324', 'servo_pan', '92', 'operator', 0),
        ('2026-05-12 06:38:06.683299', 'tracking_mode', 'AUTO', 'operator', 0),
        ('2026-05-12 06:42:54.299801', 'led', 'TOGGLE', 'operator', 0),
        ('2026-05-12 12:45:28.179626', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-12 12:45:38.132360', 'servo_pan', '140', 'operator', 0),
        ('2026-05-12 12:50:24.705232', 'tracking_mode', 'AUTO', 'operator', 0),
        ('2026-05-12 16:06:14.740613', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-12 16:06:28.217313', 'servo_pan', '42', 'operator', 0),
        ('2026-05-12 16:06:38.836172', 'servo_tilt', '68', 'operator', 0),
        ('2026-05-12 16:06:54.258045', 'servo_tilt', '39', 'operator', 0),
        ('2026-05-12 16:07:01.272077', 'buzzer', 'TRIGGER', 'operator', 0),
        ('2026-05-12 16:07:07.509057', 'buzzer', 'TRIGGER', 'operator', 0),
        ('2026-05-12 16:07:12.958635', 'buzzer', 'TRIGGER', 'operator', 0),
        ('2026-05-12 16:07:15.907615', 'buzzer', 'TRIGGER', 'operator', 0),
        ('2026-05-12 16:07:21.821764', 'buzzer', 'TRIGGER', 'operator', 0),
        ('2026-05-12 16:08:22.242876', 'servo_pan', '109', 'operator', 0),
        ('2026-05-12 16:08:30.138705', 'servo_pan', '77', 'operator', 0),
        ('2026-05-12 16:09:13.117900', 'tracking_mode', 'AUTO', 'operator', 0),
        ('2026-05-12 16:09:55.219343', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-13 15:27:13.822798', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-13 15:39:10.805222', 'tracking_mode', 'AUTO', 'operator', 0),
        ('2026-05-13 15:41:12.033401', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-13 15:43:29.027427', 'servo_pan', '46', 'operator', 0),
        ('2026-05-13 15:43:39.566378', 'tracking_mode', 'AUTO', 'operator', 0),
        ('2026-05-13 15:44:21.414369', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-13 15:44:48.034592', 'led', 'TOGGLE', 'operator', 0),
        ('2026-05-13 15:44:50.117169', 'led', 'TOGGLE', 'operator', 0),
        ('2026-05-13 15:44:53.797877', 'buzzer', 'TRIGGER', 'operator', 0),
        ('2026-05-14 01:44:55.622551', 'tracking_mode', 'MANUAL', 'operator', 0),
        ('2026-05-14 01:45:04.789626', 'servo_pan', '81', 'operator', 0),
        ('2026-05-14 01:50:00.661765', 'servo_pan', '68', 'operator', 0),
        ('2026-05-14 01:50:33.580902', 'buzzer', 'TRIGGER', 'operator', 0),
    ]
    commands = [ControlCommand(
        timestamp=pd.to_datetime(row[0]).to_pydatetime(),
        topic_key=row[1], payload=row[2], sent_by=row[3], acknowledged=row[4]
    ) for row in command_data]
    session.bulk_save_objects(commands)

    event_data = [
        ('2026-05-12 04:06:30.786372', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 04:12:07.883548', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 04:36:49.057644', 'connection', 'warning', 'MQTT disconnected (rc=Unspecified error)'),
        ('2026-05-12 04:36:52.919142', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 04:51:19.482132', 'connection', 'warning', 'MQTT disconnected (rc=Unspecified error)'),
        ('2026-05-12 04:51:23.672769', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 05:04:45.640514', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 05:07:41.574961', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 05:24:03.309789', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 05:28:44.678826', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 05:30:58.313979', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 05:34:02.366761', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 05:38:33.318460', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 06:00:40.043839', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 06:01:05.866942', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 06:01:52.817582', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 06:04:56.041396', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 06:25:06.716238', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 06:25:54.261268', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 06:31:16.849787', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 06:43:03.286339', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 08:02:10.752806', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 08:03:00.428869', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 08:28:45.477642', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 08:40:55.855181', 'connection', 'warning', 'MQTT disconnected (rc=Unspecified error)'),
        ('2026-05-12 12:44:16.261334', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 12:45:00.241800', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 13:27:58.593626', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 13:29:03.193787', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 14:07:51.735167', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 14:08:59.851214', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 15:08:55.691245', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 15:19:44.805356', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 15:20:16.296765', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 15:58:05.583244', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 15:59:53.007645', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 16:02:04.790624', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 16:02:46.486556', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 16:04:33.578691', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 16:05:27.843548', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-12 16:10:37.065126', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-13 14:53:56.859540', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-13 14:58:27.098873', 'connection', 'warning', 'MQTT disconnected (rc=Unspecified error)'),
        ('2026-05-13 14:59:34.067598', 'connection', 'warning', 'MQTT disconnected (rc=Unspecified error)'),
        ('2026-05-13 15:00:46.037948', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-13 15:15:28.266570', 'connection', 'warning', 'MQTT disconnected (rc=Keep alive timeout)'),
        ('2026-05-13 15:15:28.527824', 'connection', 'warning', 'MQTT disconnected (rc=Keep alive timeout)'),
        ('2026-05-13 15:15:40.481268', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-13 15:26:54.731792', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-13 15:45:00.490517', 'connection', 'warning', 'MQTT disconnected (rc=Keep alive timeout)'),
        ('2026-05-13 15:45:00.554959', 'connection', 'warning', 'MQTT disconnected (rc=Keep alive timeout)'),
        ('2026-05-13 15:45:05.856291', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-14 00:39:01.611810', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
        ('2026-05-14 01:43:11.666369', 'connection', 'info', 'MQTT connected to 4438a6aa9a8f42ddb3bbbf61da5f9cf5.s1.eu.hivemq.cloud'),
    ]
    events = [SystemEvent(
        timestamp=pd.to_datetime(row[0]).to_pydatetime(),
        event_type=row[1], severity=row[2], message=row[3]
    ) for row in event_data]
    session.bulk_save_objects(events)

    session.commit()
    print('✅ Existing data successfully restored.')

if session.query(SensorReading).count() == 0:
    seed_existing_data()


# ─────────────────────────────────────────────────────────────
# RUN DIRECTLY (local testing only)
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    df = load_all_readings_to_df()
    print(f"\nShape: {df.shape}")
    print(f"Date range: {df['timestamp'].min()} → {df['timestamp'].max()}")
    print(df.describe().round(2))
    session.close()