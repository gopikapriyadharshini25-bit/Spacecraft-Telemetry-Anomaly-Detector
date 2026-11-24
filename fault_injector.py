"""
fault_injector.py - Spacecraft Telemetry Fault Injection Engine

This module introduces controlled anomalies into Astraea-1's sensor stream:
1. SPIKE: Abrupt, sharp deviation exceeding critical limits.
2. DRIFT: Progressive divergence away from nominal across successive frames.
3. STUCK: Sensor value frozen at an unchanging reading over time.
4. MISSING: Sensor reading omitted (represented as None in Python, null in JSON).

Faults are applied non-destructively to generated telemetry readings, never
altering the baseline sensor limits or configuration.
"""

from typing import Dict, Optional
from config import CHANNEL_CONFIGS, FaultType


class FaultInjector:
    """
    Manages and applies artificial anomalies to telemetry readings.
    """

    def __init__(self):
        self.active_channel: Optional[str] = None
        self.active_fault: FaultType = FaultType.NONE
        self._drift_step: int = 0
        self._stuck_value: Optional[float] = None

    def set_fault(self, channel_name: str, fault_type: FaultType) -> None:
        """
        Arm a fault for a specific sensor channel.

        Args:
            channel_name: Name of the sensor channel (must exist in CHANNEL_CONFIGS).
            fault_type: Type of anomaly (SPIKE, DRIFT, STUCK, MISSING).
        """
        if channel_name not in CHANNEL_CONFIGS:
            raise ValueError(f"Unknown sensor channel '{channel_name}'")

        self.active_channel = channel_name
        self.active_fault = fault_type
        self._drift_step = 0
        self._stuck_value = None

    def clear_fault(self) -> None:
        """Clear any active fault and return telemetry to nominal generation."""
        self.active_channel = None
        self.active_fault = FaultType.NONE
        self._drift_step = 0
        self._stuck_value = None

    def is_fault_active(self) -> bool:
        """Return True if an artificial fault is currently armed."""
        return self.active_fault != FaultType.NONE and self.active_channel is not None

    def get_status_summary(self) -> str:
        """Return a human-readable description of current fault status."""
        if not self.is_fault_active():
            return "No active faults (Nominal)"
        channel_name = self.active_channel
        channel_desc = CHANNEL_CONFIGS[channel_name].display_name if channel_name else "Unknown"
        return f"{self.active_fault.value} active on {channel_desc} ({channel_name})"

    def apply_fault(self, readings: Dict[str, Optional[float]]) -> Dict[str, Optional[float]]:
        """
        Return a new copy of the readings dictionary with the active fault applied.
        Non-targeted channels remain completely unaffected.
        """
        # Always work on a shallow copy so we do not mutate simulator input
        modified = dict(readings)

        if not self.is_fault_active():
            return modified

        channel_name = self.active_channel
        if channel_name not in modified or channel_name not in CHANNEL_CONFIGS:
            return modified

        channel = CHANNEL_CONFIGS[channel_name]
        current_val = modified[channel_name]

        if self.active_fault == FaultType.MISSING:
            # Nullify sensor value
            modified[channel_name] = None

        elif self.active_fault == FaultType.SPIKE:
            # Abruptly push the value well past the critical threshold
            # If current value is positive or near center, push above critical_max
            spike_offset = (channel.critical_max - channel.nominal_max) * 1.5
            if spike_offset <= 0:
                spike_offset = channel.nominal_center * 0.2
            modified[channel_name] = round(channel.critical_max + spike_offset, 2)

        elif self.active_fault == FaultType.DRIFT:
            # Gradually diverge further each frame
            self._drift_step += 1
            # Step offset scaled by the channel's allowed historical deviation
            drift_rate = max(0.2, channel.max_historical_deviation * 0.25)
            drift_delta = self._drift_step * drift_rate
            base_val = current_val if current_val is not None else channel.nominal_center
            modified[channel_name] = round(base_val + drift_delta, 2)

        elif self.active_fault == FaultType.STUCK:
            # Freeze the value at the first observed reading
            if self._stuck_value is None:
                self._stuck_value = current_val if current_val is not None else channel.nominal_center
            modified[channel_name] = self._stuck_value

        return modified
