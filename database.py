"""
database.py - SQLite Persistence Layer for Telemetry and Anomalies

This module provides thread-safe relational persistence using Python's built-in
sqlite3 module. It stores incoming telemetry frames, extracted channel values,
and detected anomalies, and supports historical rolling window queries for
the anomaly detection engine and dashboard charts.
"""

from datetime import datetime, timezone
import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple

from config import DEFAULT_DB_PATH
from telemetry import TelemetryFrame


class DatabaseManager:
    """
    Manages SQLite database initialization, storage, and queries.
    Thread-safe through internal reentrant locking.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._init_connection()
        self.create_tables()

    def _init_connection(self) -> None:
        """Initialize SQLite connection with thread sharing enabled under lock."""
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Enable WAL mode for high concurrency and immediate write durability
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")

    def close(self) -> None:
        """Safely commit and close the database connection."""
        with self._lock:
            if self._conn:
                try:
                    self._conn.commit()
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def create_tables(self) -> None:
        """Create telemetry and anomaly relational tables if they do not exist."""
        with self._lock:
            cursor = self._conn.cursor()

            # 1. Telemetry frames table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS telemetry_frames (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    spacecraft_id TEXT NOT NULL,
                    sequence_number INTEGER NOT NULL UNIQUE,
                    timestamp TEXT NOT NULL,
                    readings_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

            # 2. Per-channel sensor readings for fast indexed historical queries
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS channel_readings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    frame_id INTEGER NOT NULL REFERENCES telemetry_frames(id) ON DELETE CASCADE,
                    channel_name TEXT NOT NULL,
                    value REAL,
                    timestamp TEXT NOT NULL
                );
            """)

            # 3. Anomaly detection records
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS anomalies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    frame_id INTEGER NOT NULL REFERENCES telemetry_frames(id) ON DELETE CASCADE,
                    channel_name TEXT NOT NULL,
                    observed_value REAL,
                    severity TEXT NOT NULL,
                    detection_type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
            """)

            # Create indices for fast historical lookups
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_channel_readings_query 
                ON channel_readings (channel_name, id DESC);
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_anomalies_timestamp 
                ON anomalies (id DESC);
            """)

            self._conn.commit()

    def insert_telemetry_frame(self, frame: TelemetryFrame) -> Optional[int]:
        """
        Insert a telemetry frame and its individual channel readings.
        Prevents duplicate sequence numbers via UNIQUE constraint.

        Returns:
            The generated frame_id (int), or None if duplicate frame.
        """
        with self._lock:
            cursor = self._conn.cursor()
            now_iso = datetime.now(timezone.utc).isoformat()

            try:
                cursor.execute("""
                    INSERT INTO telemetry_frames (
                        spacecraft_id, sequence_number, timestamp, readings_json, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    frame.spacecraft_id,
                    frame.sequence_number,
                    frame.timestamp,
                    json.dumps(frame.readings),
                    now_iso,
                ))
                frame_id = cursor.lastrowid
            except sqlite3.IntegrityError:
                # Duplicate sequence number encountered
                return None

            # Insert channel readings for indexed historical retrieval
            channel_rows = [
                (frame_id, channel_name, val, frame.timestamp)
                for channel_name, val in frame.readings.items()
            ]
            cursor.executemany("""
                INSERT INTO channel_readings (frame_id, channel_name, value, timestamp)
                VALUES (?, ?, ?, ?)
            """, channel_rows)

            self._conn.commit()
            return frame_id

    def insert_anomaly(
        self,
        frame_id: int,
        channel_name: str,
        observed_value: Optional[float],
        severity: str,
        detection_type: str,
        reason: str,
        timestamp: str,
    ) -> int:
        """Insert a single detected anomaly event record."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                INSERT INTO anomalies (
                    frame_id, channel_name, observed_value, severity,
                    detection_type, reason, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                frame_id,
                channel_name,
                observed_value,
                severity,
                detection_type,
                reason,
                timestamp,
            ))
            self._conn.commit()
            return cursor.lastrowid

    def get_recent_valid_readings(
        self,
        channel_name: str,
        limit: int = 10,
        exclude_frame_id: Optional[int] = None,
    ) -> List[float]:
        """
        Retrieve up to `limit` most recent valid (non-null) readings for a channel.
        Optionally excludes `exclude_frame_id` so the current reading is not included
        in its own baseline calculation.

        Returns:
            List of floats in chronological order (oldest to newest).
        """
        with self._lock:
            cursor = self._conn.cursor()
            if exclude_frame_id is not None:
                cursor.execute("""
                    SELECT value FROM channel_readings
                    WHERE channel_name = ? AND value IS NOT NULL AND frame_id != ?
                    ORDER BY id DESC
                    LIMIT ?
                """, (channel_name, exclude_frame_id, limit))
            else:
                cursor.execute("""
                    SELECT value FROM channel_readings
                    WHERE channel_name = ? AND value IS NOT NULL
                    ORDER BY id DESC
                    LIMIT ?
                """, (channel_name, limit))

            rows = cursor.fetchall()
            # Rows are retrieved newest-first; reverse to chronological order
            return [float(row["value"]) for row in reversed(rows)]

    def get_recent_anomalies(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve recent anomaly log records in reverse chronological order."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                SELECT id, frame_id, channel_name, observed_value,
                       severity, detection_type, reason, timestamp
                FROM anomalies
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_channel_history(self, channel_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Retrieve timestamped values for a channel to render historical trend charts.
        Returns records in chronological order (oldest to newest).
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute("""
                SELECT timestamp, value
                FROM channel_readings
                WHERE channel_name = ? AND value IS NOT NULL
                ORDER BY id DESC
                LIMIT ?
            """, (channel_name, limit))
            rows = cursor.fetchall()
            return [dict(row) for row in reversed(rows)]

    def get_summary_stats(self) -> Dict[str, int]:
        """
        Compute dashboard aggregate statistics.

        Returns:
            Dictionary with total_frames, warning_count, critical_count,
            historical_anomaly_count, and total_anomalies.
        """
        with self._lock:
            cursor = self._conn.cursor()

            cursor.execute("SELECT COUNT(*) AS total FROM telemetry_frames")
            total_frames = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) AS count FROM anomalies WHERE severity = 'WARNING'")
            warning_count = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(*) AS count FROM anomalies WHERE severity = 'CRITICAL'")
            critical_count = cursor.fetchone()["count"]

            cursor.execute("""
                SELECT COUNT(*) AS count FROM anomalies 
                WHERE detection_type = 'HISTORICAL' OR detection_type = 'COMBINED'
            """)
            historical_anomaly_count = cursor.fetchone()["count"]

            return {
                "total_frames": total_frames,
                "warning_count": warning_count,
                "critical_count": critical_count,
                "historical_anomaly_count": historical_anomaly_count,
                "total_anomalies": warning_count + critical_count,
            }
