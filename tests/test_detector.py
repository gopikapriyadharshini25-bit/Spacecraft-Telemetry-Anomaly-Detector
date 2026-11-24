"""
test_detector.py - Unit tests for threshold detection and severity combination.
"""

import unittest
from config import CHANNEL_CONFIGS, Severity, DetectionType
from anomaly_detector import evaluate_threshold, combine_severities


class TestThresholdDetector(unittest.TestCase):
    def setUp(self):
        self.channel = CHANNEL_CONFIGS["battery_voltage"]
        # Limits: nominal [34, 38], warning [32, 40], critical [30, 42]

    def test_nominal_reading(self):
        sev, reason = evaluate_threshold(self.channel, 36.0)
        self.assertEqual(sev, Severity.NOMINAL)
        self.assertIn("operates nominally", reason)

    def test_warning_upper_boundary(self):
        # 40.5 is between warning_max (40) and critical_max (42)
        sev, reason = evaluate_threshold(self.channel, 40.5)
        self.assertEqual(sev, Severity.WARNING)
        self.assertIn("above warning upper limit", reason)

    def test_warning_lower_boundary(self):
        # 31.5 is between critical_min (30) and warning_min (32)
        sev, reason = evaluate_threshold(self.channel, 31.5)
        self.assertEqual(sev, Severity.WARNING)
        self.assertIn("below warning lower limit", reason)

    def test_critical_upper_boundary(self):
        # 43.0 exceeds critical_max (42)
        sev, reason = evaluate_threshold(self.channel, 43.0)
        self.assertEqual(sev, Severity.CRITICAL)
        self.assertIn("above critical upper limit", reason)

    def test_critical_lower_boundary(self):
        # 28.0 is below critical_min (30)
        sev, reason = evaluate_threshold(self.channel, 28.0)
        self.assertEqual(sev, Severity.CRITICAL)
        self.assertIn("below critical lower limit", reason)

    def test_missing_reading_is_warning(self):
        sev, reason = evaluate_threshold(self.channel, None)
        self.assertEqual(sev, Severity.WARNING)
        self.assertIn("Missing telemetry", reason)

    def test_combine_severities_critical_precedence(self):
        # Critical threshold + Nominal historical -> Critical
        eval_res = combine_severities(
            channel=self.channel,
            observed_value=45.0,
            threshold_severity=Severity.CRITICAL,
            threshold_reason="Over voltage",
            historical_severity=Severity.NOMINAL,
            historical_reason="Normal",
            historical_average=36.0,
        )
        self.assertEqual(eval_res.severity, Severity.CRITICAL)
        self.assertEqual(eval_res.detection_type, DetectionType.THRESHOLD)

    def test_combine_severities_combined_detection(self):
        # Warning threshold + Warning historical -> Warning, COMBINED detection type
        eval_res = combine_severities(
            channel=self.channel,
            observed_value=40.5,
            threshold_severity=Severity.WARNING,
            threshold_reason="High voltage warning",
            historical_severity=Severity.WARNING,
            historical_reason="Diverged from historical mean",
            historical_average=36.0,
        )
        self.assertEqual(eval_res.severity, Severity.WARNING)
        self.assertEqual(eval_res.detection_type, DetectionType.COMBINED)


if __name__ == "__main__":
    unittest.main()
