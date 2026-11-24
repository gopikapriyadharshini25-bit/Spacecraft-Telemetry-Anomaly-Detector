"""
test_sensor_simulator.py - Unit tests for Astraea-1 sensor simulator.
"""

import unittest
from config import CHANNEL_CONFIGS, SPACECRAFT_ID
from sensor_simulator import SensorSimulator


class TestSensorSimulator(unittest.TestCase):
    def setUp(self):
        self.sim = SensorSimulator(seed=12345)

    def test_seed_reproducibility(self):
        sim1 = SensorSimulator(seed=42)
        sim2 = SensorSimulator(seed=42)

        readings1 = sim1.generate_nominal_readings()
        readings2 = sim2.generate_nominal_readings()
        self.assertEqual(readings1, readings2)

    def test_all_9_channels_generated(self):
        readings = self.sim.generate_nominal_readings()
        self.assertEqual(len(readings), 9)
        for channel_name in CHANNEL_CONFIGS:
            self.assertIn(channel_name, readings)
            val = readings[channel_name]
            self.assertIsInstance(val, float)

    def test_nominal_values_within_bounds(self):
        # Generate multiple cycles to ensure all random perturbations stay clamped inside nominal
        for _ in range(50):
            readings = self.sim.generate_nominal_readings()
            for name, val in readings.items():
                ch = CHANNEL_CONFIGS[name]
                self.assertGreaterEqual(
                    val, ch.nominal_min,
                    f"{name} value {val} below nominal_min {ch.nominal_min}"
                )
                self.assertLessEqual(
                    val, ch.nominal_max,
                    f"{name} value {val} above nominal_max {ch.nominal_max}"
                )

    def test_generate_frame(self):
        frame = self.sim.generate_frame(sequence_number=10)
        self.assertEqual(frame.spacecraft_id, SPACECRAFT_ID)
        self.assertEqual(frame.sequence_number, 10)
        self.assertEqual(len(frame.readings), 9)
        self.assertTrue(len(frame.timestamp) > 0)


if __name__ == "__main__":
    unittest.main()
