"""
sensor_simulator.py - Astraea-1 Sensor Simulation Engine

This module generates realistic fictional telemetry readings for the Astraea-1
spacecraft. Readings are centered on nominal operating values with controlled,
natural Gaussian perturbations. A random seed is supported to enable fully
reproducible unit and integration tests.
"""

from datetime import datetime, timezone
import random
from typing import Dict, Optional

from config import CHANNEL_CONFIGS, SPACECRAFT_ID, SensorChannel
from telemetry import TelemetryFrame


class SensorSimulator:
    """
    Simulates operational telemetry readings for Astraea-1.

    Each sensor channel produces values within its nominal limits using
    a normal (Gaussian) distribution around its nominal center.
    """

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize simulator with an optional random seed for reproducibility.
        """
        self._rng = random.Random(seed)

    def set_seed(self, seed: int) -> None:
        """Reset the internal pseudo-random generator with a fixed seed."""
        self._rng = random.Random(seed)

    def generate_channel_reading(self, channel: SensorChannel) -> float:
        """
        Generate a single nominal reading for the given channel.
        Values are clamped between nominal_min and nominal_max to ensure
        unfaulted sensors stay reliably within nominal bounds.
        """
        raw_val = self._rng.gauss(channel.nominal_center, channel.nominal_noise_std)
        # Clamp strictly inside nominal bounds
        clamped_val = max(channel.nominal_min, min(channel.nominal_max, raw_val))
        return round(clamped_val, 2)

    def generate_nominal_readings(self) -> Dict[str, float]:
        """Generate a complete dictionary of nominal readings for all 9 channels."""
        return {
            name: self.generate_channel_reading(ch)
            for name, ch in CHANNEL_CONFIGS.items()
        }

    def generate_frame(self, sequence_number: int) -> TelemetryFrame:
        """
        Construct a complete TelemetryFrame with a fresh UTC timestamp
        and nominal readings for Astraea-1.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        readings = self.generate_nominal_readings()
        return TelemetryFrame(
            spacecraft_id=SPACECRAFT_ID,
            sequence_number=sequence_number,
            timestamp=timestamp,
            readings=readings,
        )
