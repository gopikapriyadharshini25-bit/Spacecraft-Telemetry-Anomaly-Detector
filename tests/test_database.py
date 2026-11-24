"""
test_database.py - Unit tests for SQLite database manager.
"""

from datetime import datetime, timezone
import os
import tempfile
import unittest

from config import CHANNEL_CONFIGS, SPACECRAFT_ID
from database import DatabaseManager
from telemetry import TelemetryFrame


class TestDatabase(unittest.TestCase):
    def setUp(self):
        # Create temporary file for SQLite
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db_path = self.temp_file.name
        self.temp_file.close()
        self.db = DatabaseManager(db_path=self.db_path)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def test_tables_created(self):
        # Test inserting and reading frames
        frame = TelemetryFrame(
            spacecraft_id=SPACECRAFT_ID,
            sequence_number=1,
            timestamp=datetime.now(timezone.utc).isoformat(),
            readings={name: ch.nominal_center for name, ch in CHANNEL_CONFIGS.items()},
        )
        frame_id = self.db.insert_telemetry_frame(frame)
        self.assertIsNotNone(frame_id)
        self.assertGreater(frame_id, 0)

    def test_duplicate_sequence_number_rejected(self):
        frame1 = TelemetryFrame(
            spacecraft_id=SPACECRAFT_ID,
            sequence_number=100,
            timestamp=datetime.now(timezone.utc).isoformat(),
            readings={name: ch.nominal_center for name, ch in CHANNEL_CONFIGS.items()},
        )
        frame_id1 = self.db.insert_telemetry_frame(frame1)
        self.assertIsNotNone(frame_id1)

        # Same sequence number should be ignored/rejected
        frame_id2 = self.db.insert_telemetry_frame(frame1)
        self.assertIsNone(frame_id2)

    def test_historical_reading_retrieval(self):
        channel = "battery_voltage"
        # Insert 5 consecutive frames with known values
        values = [35.0, 35.5, 36.0, 36.5, 37.0]
        frame_ids = []
        for i, val in enumerate(values):
            frame = TelemetryFrame(
                spacecraft_id=SPACECRAFT_ID,
                sequence_number=i + 1,
                timestamp=datetime.now(timezone.utc).isoformat(),
                readings={name: (val if name == channel else ch.nominal_center)
                          for name, ch in CHANNEL_CONFIGS.items()},
            )
            fid = self.db.insert_telemetry_frame(frame)
            frame_ids.append(fid)

        # Retrieve last 3 readings excluding the 5th frame
        recent = self.db.get_recent_valid_readings(
            channel_name=channel,
            limit=3,
            exclude_frame_id=frame_ids[-1]
        )
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent, [35.5, 36.0, 36.5])

    def test_anomaly_insert_and_stats(self):
        frame = TelemetryFrame(
            spacecraft_id=SPACECRAFT_ID,
            sequence_number=1,
            timestamp=datetime.now(timezone.utc).isoformat(),
            readings={name: ch.nominal_center for name, ch in CHANNEL_CONFIGS.items()},
        )
        frame_id = self.db.insert_telemetry_frame(frame)

        self.db.insert_anomaly(
            frame_id=frame_id,
            channel_name="battery_temp",
            observed_value=45.0,
            severity="WARNING",
            detection_type="THRESHOLD",
            reason="High temperature",
            timestamp=frame.timestamp,
        )
        self.db.insert_anomaly(
            frame_id=frame_id,
            channel_name="battery_voltage",
            observed_value=28.0,
            severity="CRITICAL",
            detection_type="COMBINED",
            reason="Voltage collapse",
            timestamp=frame.timestamp,
        )

        stats = self.db.get_summary_stats()
        self.assertEqual(stats["total_frames"], 1)
        self.assertEqual(stats["warning_count"], 1)
        self.assertEqual(stats["critical_count"], 1)
        self.assertEqual(stats["historical_anomaly_count"], 1)
        self.assertEqual(stats["total_anomalies"], 2)

        anomalies = self.db.get_recent_anomalies(limit=10)
        self.assertEqual(len(anomalies), 2)

    def test_persistence_across_reconnect(self):
        frame = TelemetryFrame(
            spacecraft_id=SPACECRAFT_ID,
            sequence_number=50,
            timestamp=datetime.now(timezone.utc).isoformat(),
            readings={"battery_voltage": 36.2},
        )
        self.db.insert_telemetry_frame(frame)
        self.db.close()

        # Reopen with new manager instance pointing to same file
        reopened_db = DatabaseManager(db_path=self.db_path)
        stats = reopened_db.get_summary_stats()
        self.assertEqual(stats["total_frames"], 1)
        readings = reopened_db.get_recent_valid_readings("battery_voltage", limit=5)
        self.assertEqual(readings, [36.2])
        reopened_db.close()


if __name__ == "__main__":
    unittest.main()
