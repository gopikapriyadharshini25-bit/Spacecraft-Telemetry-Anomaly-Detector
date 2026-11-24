"""
config.py - Spacecraft Telemetry and Ground Station Configuration

This module holds central configurations, sensor limit thresholds, networking
parameters, and severity definitions for the Astraea-1 spacecraft mission.
Keeping thresholds in one place ensures the detection rules are explainable,
maintainable, and consistent across simulation, detection, and GUI modules.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict


class Severity(str, Enum):
    """
    Standard severity levels for telemetry anomaly detection.
    Inherits from str for easy JSON serialization and Tkinter display.
    """
    NOMINAL = "NOMINAL"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class FaultType(str, Enum):
    """Supported fault injection modes."""
    NONE = "NONE"
    SPIKE = "SPIKE"
    DRIFT = "DRIFT"
    STUCK = "STUCK"
    MISSING = "MISSING"


class DetectionType(str, Enum):
    """Category of anomaly detection trigger."""
    NONE = "NONE"
    THRESHOLD = "THRESHOLD"
    HISTORICAL = "HISTORICAL"
    COMBINED = "COMBINED"
    MISSING_DATA = "MISSING_DATA"


@dataclass(frozen=True)
class SensorChannel:
    """
    Defines the engineering limits and operational parameters for a sensor.

    Attributes:
        name: Unique programmatic key for the sensor.
        display_name: Human-friendly label for dashboard presentation.
        unit: Physical unit of measurement (e.g., 'V', '°C', 'RPM').
        nominal_min: Lower bound of expected standard operations.
        nominal_max: Upper bound of expected standard operations.
        warning_min: Lower threshold; below this triggers a WARNING.
        warning_max: Upper threshold; above this triggers a WARNING.
        critical_min: Lower threshold; below this triggers a CRITICAL event.
        critical_max: Upper threshold; above this triggers a CRITICAL event.
        max_historical_deviation: Maximum allowable absolute difference from the
                                 historical rolling mean before flagging an anomaly.
        nominal_center: Center point for nominal synthetic value generation.
        nominal_noise_std: Standard deviation of normal white noise variation.
    """
    name: str
    display_name: str
    unit: str
    nominal_min: float
    nominal_max: float
    warning_min: float
    warning_max: float
    critical_min: float
    critical_max: float
    max_historical_deviation: float
    nominal_center: float
    nominal_noise_std: float


# Spacecraft & Mission Identity
SPACECRAFT_ID: str = "Astraea-1"

# Network Configuration for Local Ground Station Link
DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 8765
SOCKET_TIMEOUT_SECONDS: float = 2.0
MAX_BUFFER_BYTES: int = 65536  # 64 KB safety buffer limit

# Database Configuration
DEFAULT_DB_PATH: str = "spacecraft_telemetry.db"

# Historical Anomaly Detection Parameters
HISTORICAL_WINDOW_SIZE: int = 10  # Rolling window size of prior valid readings
MIN_HISTORY_SAMPLES: int = 3      # Minimum stored readings needed before checking deviation

# Simulation Timing
DEFAULT_SIMULATION_INTERVAL_SEC: float = 1.0


# 9 Fictional Spacecraft Telemetry Channels
# Limits follow standard aerospace hierarchical safety margins:
# Critical Lower < Warning Lower < Nominal Lower < Nominal Upper < Warning Upper < Critical Upper
CHANNEL_CONFIGS: Dict[str, SensorChannel] = {
    "battery_voltage": SensorChannel(
        name="battery_voltage",
        display_name="Battery Bus Voltage",
        unit="V",
        nominal_min=34.0,
        nominal_max=38.0,
        warning_min=32.0,
        warning_max=40.0,
        critical_min=30.0,
        critical_max=42.0,
        max_historical_deviation=3.5,
        nominal_center=36.0,
        nominal_noise_std=0.4,
    ),
    "battery_temp": SensorChannel(
        name="battery_temp",
        display_name="Battery Cell Temp",
        unit="°C",
        nominal_min=15.0,
        nominal_max=30.0,
        warning_min=5.0,
        warning_max=40.0,
        critical_min=0.0,
        critical_max=50.0,
        max_historical_deviation=7.0,
        nominal_center=22.5,
        nominal_noise_std=1.2,
    ),
    "battery_charge": SensorChannel(
        name="battery_charge",
        display_name="State of Charge",
        unit="%",
        nominal_min=60.0,
        nominal_max=95.0,
        warning_min=40.0,
        warning_max=100.0,
        critical_min=20.0,
        critical_max=100.0,
        max_historical_deviation=10.0,
        nominal_center=82.0,
        nominal_noise_std=1.5,
    ),
    "solar_panel_current": SensorChannel(
        name="solar_panel_current",
        display_name="Solar Array Current",
        unit="A",
        nominal_min=8.0,
        nominal_max=12.0,
        warning_min=5.0,
        warning_max=14.0,
        critical_min=2.0,
        critical_max=16.0,
        max_historical_deviation=2.5,
        nominal_center=10.0,
        nominal_noise_std=0.5,
    ),
    "power_bus_consumption": SensorChannel(
        name="power_bus_consumption",
        display_name="Power Bus Load",
        unit="W",
        nominal_min=250.0,
        nominal_max=350.0,
        warning_min=200.0,
        warning_max=420.0,
        critical_min=150.0,
        critical_max=500.0,
        max_historical_deviation=45.0,
        nominal_center=300.0,
        nominal_noise_std=8.0,
    ),
    "comm_signal_strength": SensorChannel(
        name="comm_signal_strength",
        display_name="Comm Signal (RSSI)",
        unit="dBm",
        nominal_min=-80.0,
        nominal_max=-50.0,
        warning_min=-95.0,
        warning_max=-40.0,
        critical_min=-110.0,
        critical_max=-30.0,
        max_historical_deviation=12.0,
        nominal_center=-65.0,
        nominal_noise_std=2.0,
    ),
    "internal_temp": SensorChannel(
        name="internal_temp",
        display_name="Avionics Internal Temp",
        unit="°C",
        nominal_min=18.0,
        nominal_max=24.0,
        warning_min=10.0,
        warning_max=32.0,
        critical_min=5.0,
        critical_max=40.0,
        max_historical_deviation=4.0,
        nominal_center=21.0,
        nominal_noise_std=0.6,
    ),
    "fuel_pressure": SensorChannel(
        name="fuel_pressure",
        display_name="RCS Fuel Pressure",
        unit="psi",
        nominal_min=280.0,
        nominal_max=320.0,
        warning_min=240.0,
        warning_max=350.0,
        critical_min=200.0,
        critical_max=380.0,
        max_historical_deviation=25.0,
        nominal_center=300.0,
        nominal_noise_std=3.0,
    ),
    "reaction_wheel_rpm": SensorChannel(
        name="reaction_wheel_rpm",
        display_name="Reaction Wheel Speed",
        unit="RPM",
        nominal_min=1500.0,
        nominal_max=3500.0,
        warning_min=800.0,
        warning_max=4200.0,
        critical_min=200.0,
        critical_max=5000.0,
        max_historical_deviation=600.0,
        nominal_center=2500.0,
        nominal_noise_std=60.0,
    ),
}
