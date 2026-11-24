"""
test_telemetry.py - Unit tests for TelemetryFrame serialization and validation.
"""

from datetime import datetime, timezone
import json
import unittest

from config import CHANNEL_CONFIGS, SPACECRAFT_ID
from telemetry import (
    TelemetryFrame,
    validate_telemetry_dict,
    parse_and_validate_raw_line,
)


class TestTelemetry(unittest.TestCase):
    def setUp(self):
        self.valid_readings = {
            name: ch.nominal_center for name, ch in CHANNEL_CONFIGS.items()
        }
        self.valid_timestamp = datetime.now(timezone.utc).isoformat()
        self.valid_dict = {
            "spacecraft_id": SPACECRAFT_ID,
            "sequence_number": 1,
            "timestamp": self.valid_timestamp,
            "readings": self.valid_readings,
        }

    def test_telemetry_frame_roundtrip(self):
        frame = TelemetryFrame(
            spacecraft_id=SPACECRAFT_ID,
            sequence_number=42,
            timestamp=self.valid_timestamp,
            readings=self.valid_readings,
        )
        as_dict = frame.to_dict()
        self.assertEqual(as_dict["sequence_number"], 42)
        self.assertEqual(as_dict["spacecraft_id"], SPACECRAFT_ID)

        # JSON roundtrip
        json_str = frame.to_json()
        reconstructed = TelemetryFrame.from_json(json_str)
        self.assertEqual(reconstructed.sequence_number, 42)
        self.assertEqual(reconstructed.readings["battery_voltage"], self.valid_readings["battery_voltage"])

        # Byte roundtrip (NDJSON ends with newline)
        raw_bytes = frame.to_bytes()
        self.assertTrue(raw_bytes.endswith(b"\n"))

    def test_validate_valid_dict(self):
        is_valid, reason = validate_telemetry_dict(self.valid_dict)
        self.assertTrue(is_valid)
        self.assertEqual(reason, "")

    def test_validate_missing_channel_allowed_as_null(self):
        # A channel with value None (null in JSON) simulates missing sensor data
        modified = dict(self.valid_dict)
        modified["readings"] = dict(self.valid_readings)
        modified["readings"]["battery_voltage"] = None
        is_valid, reason = validate_telemetry_dict(modified)
        self.assertTrue(is_valid, f"Expected None to be valid for missing sensor, got: {reason}")

    def test_validate_missing_required_field(self):
        bad_dict = dict(self.valid_dict)
        del bad_dict["sequence_number"]
        is_valid, reason = validate_telemetry_dict(bad_dict)
        self.assertFalse(is_valid)
        self.assertIn("Missing required fields", reason)

    def test_validate_invalid_sequence_number(self):
        bad_dict = dict(self.valid_dict)
        bad_dict["sequence_number"] = -5
        is_valid, reason = validate_telemetry_dict(bad_dict)
        self.assertFalse(is_valid)

        bad_dict["sequence_number"] = "not_an_int"
        is_valid, reason = validate_telemetry_dict(bad_dict)
        self.assertFalse(is_valid)

    def test_validate_invalid_timestamp(self):
        bad_dict = dict(self.valid_dict)
        bad_dict["timestamp"] = "yesterday at five"
        is_valid, reason = validate_telemetry_dict(bad_dict)
        self.assertFalse(is_valid)
        self.assertIn("timestamp is not a valid ISO 8601 string", reason)

    def test_validate_nan_and_inf_rejected(self):
        bad_dict = dict(self.valid_dict)
        bad_dict["readings"] = dict(self.valid_readings)
        bad_dict["readings"]["battery_voltage"] = float("nan")
        is_valid, reason = validate_telemetry_dict(bad_dict)
        self.assertFalse(is_valid)
        self.assertIn("illegal numeric value", reason)

        bad_dict["readings"]["battery_voltage"] = float("inf")
        is_valid, reason = validate_telemetry_dict(bad_dict)
        self.assertFalse(is_valid)

    def test_parse_and_validate_raw_line_success(self):
        raw_line = json.dumps(self.valid_dict) + "\n"
        frame, err = parse_and_validate_raw_line(raw_line)
        self.assertIsNotNone(frame)
        self.assertEqual(err, "")
        self.assertEqual(frame.sequence_number, 1)

    def test_parse_and_validate_raw_line_malformed_json(self):
        raw_line = '{"spacecraft_id": "Astraea-1", incomplete\n'
        frame, err = parse_and_validate_raw_line(raw_line)
        self.assertIsNone(frame)
        self.assertIn("Malformed JSON syntax", err)


if __name__ == "__main__":
    unittest.main()
