"""
test_historical_detector.py - Unit tests for rolling average historical anomaly detection.
"""

from datetime import datetime, timezone
import os
import tempfile
import unittest

from config import CHANNEL_CONFIGS, MIN_HISTORY_SAMPLES, SPACECRAFT_ID, Severity, DetectionType
from database import DatabaseManager
from anomaly_detector import AnomalyDetector, evaluate_historical_deviation
from telemetry import TelemetryFrame


class TestHistoricalDetector(unittest.TestCase):
    def setUp(self):
        self.channel = CHANNEL_CONFIGS["battery_voltage"]
        # nominal center: 36.0, max_historical_deviation: 3.5

        # Create temporary database for historical tests
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db_path = self.temp_file.name
        self.temp_file.close()
        self.db = DatabaseManager(db_path=self.db_path)
        self.detector = AnomalyDetector(self.db)

    def tearDown(self):
        self.db.close()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def test_insufficient_samples_does_not_flag(self):
        # Fewer than MIN_HISTORY_SAMPLES should never trigger an anomaly
        history = [36.0]  # Only 1 sample
        sev, reason, mean = evaluate_historical_deviation(self.channel, 39.0, history)
        self.assertEqual(sev, Severity.NOMINAL)
        self.assertIn("Insufficient historical data", reason)
        self.assertIsNone(mean)

    def test_normal_fluctuation_within_tolerance(self):
        # Baseline around 36.0; current reading is 36.8 (deviation 0.8 <= 3.5)
        history = [35.9, 36.1, 36.0, 36.2, 35.8]
        sev, reason, mean = evaluate_historical_deviation(self.channel, 36.8, history)
        self.assertEqual(sev, Severity.NOMINAL)
        self.assertIn("Within historical baseline limits", reason)
        self.assertAlmostEqual(mean, 36.0, places=1)

    def test_sharp_historical_deviation_flagged(self):
        # Baseline around 35.0; current reading is 39.5 (deviation 4.5 > 3.5 limit)
        # Note: 39.5 is still within physical warning limit (< 40.0), so threshold detector
        # would say NOMINAL or low warning, but historical detector correctly detects the anomaly!
        history = [35.0, 35.1, 34.9, 35.0, 35.0]
        sev, reason, mean = evaluate_historical_deviation(self.channel, 39.5, history)
        self.assertEqual(sev, Severity.WARNING)
        self.assertIn("diverges by", reason)
        self.assertAlmostEqual(mean, 35.0, places=1)

    def test_historical_detector_end_to_end_with_database(self):
        # 1. Populate database with 5 baseline frames of battery_voltage = 36.0
        for seq in range(1, 6):
            frame = TelemetryFrame(
                spacecraft_id=SPACECRAFT_ID,
                sequence_number=seq,
                timestamp=datetime.now(timezone.utc).isoformat(),
                readings={name: (36.0 if name == "battery_voltage" else ch.nominal_center)
                          for name, ch in CHANNEL_CONFIGS.items()},
            )
            fid = self.db.insert_telemetry_frame(frame)
            self.detector.process_frame(frame, frame_id=fid)

        # 2. Process 6th frame with battery_voltage = 39.8 (deviation 3.8 > 3.5)
        # 39.8 is within warning threshold (nominal_max is 38.0, warning_max is 40.0)
        abnormal_frame = TelemetryFrame(
            spacecraft_id=SPACECRAFT_ID,
            sequence_number=6,
            timestamp=datetime.now(timezone.utc).isoformat(),
            readings={name: (39.8 if name == "battery_voltage" else ch.nominal_center)
                      for name, ch in CHANNEL_CONFIGS.items()},
        )
        fid6 = self.db.insert_telemetry_frame(abnormal_frame)
        eval_result = self.detector.process_frame(abnormal_frame, frame_id=fid6)

        bv_eval = eval_result.channel_results["battery_voltage"]
        self.assertEqual(bv_eval.severity, Severity.WARNING)
        self.assertEqual(bv_eval.historical_severity, Severity.WARNING)
        # Historical average was computed without frame 6
        self.assertAlmostEqual(bv_eval.historical_average, 36.0, places=1)

        # Verify anomaly was recorded in SQLite
        anomalies = self.db.get_recent_anomalies(limit=10)
        self.assertGreaterEqual(len(anomalies), 1)
        self.assertEqual(anomalies[0]["channel_name"], "battery_voltage")


if __name__ == "__main__":
    unittest.main()
