"""
test_config.py - Unit tests for configuration constants and channel definitions.
"""

import unittest
from config import CHANNEL_CONFIGS, SPACECRAFT_ID, Severity, FaultType, DetectionType


class TestConfig(unittest.TestCase):
    def test_spacecraft_id(self):
        self.assertEqual(SPACECRAFT_ID, "Astraea-1")

    def test_channel_count(self):
        # Exactly 9 channels are required
        self.assertEqual(len(CHANNEL_CONFIGS), 9)

    def test_channel_threshold_hierarchy(self):
        """
        Verify that for every channel, physical thresholds obey:
        critical_min <= warning_min <= nominal_min <= nominal_max <= warning_max <= critical_max
        """
        for name, ch in CHANNEL_CONFIGS.items():
            self.assertLessEqual(
                ch.critical_min, ch.warning_min,
                f"Channel {name}: critical_min ({ch.critical_min}) must be <= warning_min ({ch.warning_min})"
            )
            self.assertLessEqual(
                ch.warning_min, ch.nominal_min,
                f"Channel {name}: warning_min ({ch.warning_min}) must be <= nominal_min ({ch.nominal_min})"
            )
            self.assertLess(
                ch.nominal_min, ch.nominal_max,
                f"Channel {name}: nominal_min must be strictly < nominal_max"
            )
            self.assertLessEqual(
                ch.nominal_max, ch.warning_max,
                f"Channel {name}: nominal_max ({ch.nominal_max}) must be <= warning_max ({ch.warning_max})"
            )
            self.assertLessEqual(
                ch.warning_max, ch.critical_max,
                f"Channel {name}: warning_max ({ch.warning_max}) must be <= critical_max ({ch.critical_max})"
            )
            self.assertGreater(
                ch.max_historical_deviation, 0,
                f"Channel {name}: max_historical_deviation must be positive"
            )

    def test_enums(self):
        self.assertEqual(Severity.NOMINAL.value, "NOMINAL")
        self.assertEqual(Severity.WARNING.value, "WARNING")
        self.assertEqual(Severity.CRITICAL.value, "CRITICAL")
        self.assertIn("SPIKE", [f.value for f in FaultType])
        self.assertIn("THRESHOLD", [d.value for d in DetectionType])


if __name__ == "__main__":
    unittest.main()
