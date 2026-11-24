"""
test_integration.py - Full end-to-end integration test across all subsystems.

Validates the complete chain:
SensorSimulator -> FaultInjector -> TelemetryFrame (JSON) -> TCP Socket
-> GroundStationServer -> Telemetry Validation -> SQLite Database
-> AnomalyDetector (Threshold & Historical) -> Summary Metrics.
"""

from datetime import datetime, timezone
import os
import socket
import tempfile
import time
import unittest

from anomaly_detector import AnomalyDetector
from config import FaultType, Severity
from database import DatabaseManager
from fault_injector import FaultInjector
from ground_station import GroundStationServer
from sensor_simulator import SensorSimulator
from spacecraft_sender import SpacecraftSender


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestEndToEndIntegration(unittest.TestCase):
    def setUp(self):
        self.port = find_free_port()
        self.temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db_path = self.temp_file.name
        self.temp_file.close()

        self.db = DatabaseManager(db_path=self.db_path)
        self.detector = AnomalyDetector(self.db)
        self.fault_injector = FaultInjector()
        self.simulator = SensorSimulator(seed=777)

        self.processed_evaluations = []

        def on_frame(frame):
            frame_id = self.db.insert_telemetry_frame(frame)
            eval_res = self.detector.process_frame(frame, frame_id=frame_id, save_anomalies=True)
            self.processed_evaluations.append(eval_res)

        self.server = GroundStationServer(
            host="127.0.0.1",
            port=self.port,
            on_frame_received=on_frame,
        )
        self.server.start()

        self.sender = SpacecraftSender(
            simulator=self.simulator,
            fault_injector=self.fault_injector,
            host="127.0.0.1",
            port=self.port,
            interval=0.05,  # 50 ms tick for fast tests
        )

    def tearDown(self):
        self.sender.stop()
        self.server.stop()
        self.db.close()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except PermissionError:
                pass

    def test_complete_telemetry_pipeline(self):
        # 1. Start transmission with nominal telemetry
        self.sender.start()
        time.sleep(0.3)

        # 2. Inject critical spike fault on battery_voltage
        self.fault_injector.set_fault("battery_voltage", FaultType.SPIKE)
        time.sleep(0.2)

        # 3. Inject missing fault on internal_temp
        self.fault_injector.set_fault("internal_temp", FaultType.MISSING)
        time.sleep(0.2)

        # 4. Clear faults to return to nominal
        self.fault_injector.clear_fault()
        time.sleep(0.2)

        # 5. Stop pipeline
        self.sender.stop()
        self.server.stop()

        # Assertions
        # Total frames received over TCP and stored in SQLite
        self.assertGreaterEqual(len(self.processed_evaluations), 8)

        stats = self.db.get_summary_stats()
        self.assertGreaterEqual(stats["total_frames"], 8)
        self.assertGreaterEqual(stats["critical_count"], 1)
        self.assertGreaterEqual(stats["warning_count"], 1)

        # Verify that anomaly records in SQLite accurately reflect injected faults
        anomalies = self.db.get_recent_anomalies(limit=50)
        anomaly_channels = [a["channel_name"] for a in anomalies]
        self.assertIn("battery_voltage", anomaly_channels)
        self.assertIn("internal_temp", anomaly_channels)

        # Check critical voltage event record
        volt_anomalies = [a for a in anomalies if a["channel_name"] == "battery_voltage"]
        self.assertTrue(any(a["severity"] == "CRITICAL" for a in volt_anomalies))


if __name__ == "__main__":
    unittest.main()
