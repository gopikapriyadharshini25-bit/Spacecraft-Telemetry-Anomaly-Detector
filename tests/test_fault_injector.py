"""
test_fault_injector.py - Unit tests for fault injection engine.
"""

import unittest
from config import CHANNEL_CONFIGS, FaultType
from sensor_simulator import SensorSimulator
from fault_injector import FaultInjector


class TestFaultInjector(unittest.TestCase):
    def setUp(self):
        self.sim = SensorSimulator(seed=999)
        self.injector = FaultInjector()
        self.base_readings = self.sim.generate_nominal_readings()

    def test_default_state_inactive(self):
        self.assertFalse(self.injector.is_fault_active())
        modified = self.injector.apply_fault(self.base_readings)
        self.assertEqual(modified, self.base_readings)

    def test_missing_fault(self):
        target = "battery_voltage"
        self.injector.set_fault(target, FaultType.MISSING)
        self.assertTrue(self.injector.is_fault_active())

        modified = self.injector.apply_fault(self.base_readings)
        self.assertIsNone(modified[target])

        # Other channels must remain unchanged
        for name, val in modified.items():
            if name != target:
                self.assertEqual(val, self.base_readings[name])

    def test_spike_fault(self):
        target = "battery_temp"
        ch = CHANNEL_CONFIGS[target]
        self.injector.set_fault(target, FaultType.SPIKE)

        modified = self.injector.apply_fault(self.base_readings)
        self.assertGreater(modified[target], ch.critical_max)

    def test_drift_fault(self):
        target = "power_bus_consumption"
        self.injector.set_fault(target, FaultType.DRIFT)

        # Apply across multiple frames and verify monotonic increase
        frame1 = self.injector.apply_fault(self.base_readings)
        frame2 = self.injector.apply_fault(self.base_readings)
        frame3 = self.injector.apply_fault(self.base_readings)

        self.assertGreater(frame1[target], self.base_readings[target])
        self.assertGreater(frame2[target], frame1[target])
        self.assertGreater(frame3[target], frame2[target])

    def test_stuck_fault(self):
        target = "fuel_pressure"
        self.injector.set_fault(target, FaultType.STUCK)

        first_modified = self.injector.apply_fault(self.base_readings)
        frozen_val = first_modified[target]

        # Generate different readings from simulator
        for _ in range(5):
            new_readings = self.sim.generate_nominal_readings()
            result = self.injector.apply_fault(new_readings)
            self.assertEqual(result[target], frozen_val)

    def test_clear_fault(self):
        target = "battery_voltage"
        self.injector.set_fault(target, FaultType.SPIKE)
        self.assertTrue(self.injector.is_fault_active())

        self.injector.clear_fault()
        self.assertFalse(self.injector.is_fault_active())

        result = self.injector.apply_fault(self.base_readings)
        self.assertEqual(result[target], self.base_readings[target])


if __name__ == "__main__":
    unittest.main()
