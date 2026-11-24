"""
anomaly_detector.py - Spacecraft Telemetry Anomaly Detection Engine

This module implements:
1. Threshold-Based Detection: Compares sensor values against nominal, warning,
   and critical engineering bounds. Missing values (None) are flagged as warnings.
2. Historical Anomaly Detection: Compares the current reading against an N-point
   rolling average of prior valid readings retrieved from SQLite. Detects abrupt
   divergence even when within broad safety limits.
3. Severity Classification & Fusion: Combines threshold and historical findings
   using deterministic rules (CRITICAL > WARNING > NOMINAL) and generates
   human-readable explanations for viva and operational reviews.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from config import (
    CHANNEL_CONFIGS,
    HISTORICAL_WINDOW_SIZE,
    MIN_HISTORY_SAMPLES,
    DetectionType,
    SensorChannel,
    Severity,
)
from database import DatabaseManager
from telemetry import TelemetryFrame


@dataclass
class ChannelEvaluation:
    """
    Detailed anomaly detection results for an individual sensor channel.
    """
    channel_name: str
    observed_value: Optional[float]
    severity: Severity
    detection_type: DetectionType
    threshold_severity: Severity
    historical_severity: Severity
    threshold_reason: str
    historical_reason: str
    combined_reason: str
    historical_average: Optional[float] = None


@dataclass
class FrameEvaluation:
    """
    Consolidated anomaly evaluation for an entire telemetry frame.
    """
    frame: TelemetryFrame
    frame_id: Optional[int]
    overall_severity: Severity
    channel_results: Dict[str, ChannelEvaluation]
    anomalies: List[ChannelEvaluation]


def evaluate_threshold(channel: SensorChannel, value: Optional[float]) -> Tuple[Severity, str]:
    """
    Evaluate a sensor reading against configured threshold limits.

    Returns:
        (Severity, explanation_string)
    """
    # 1. Missing Data Handling
    if value is None:
        return Severity.WARNING, f"Missing telemetry for {channel.display_name} ({channel.name})."

    # 2. Critical Boundary Checks (Take Precedence)
    if value < channel.critical_min:
        return (
            Severity.CRITICAL,
            f"{channel.display_name} is {value:.2f} {channel.unit}, "
            f"below critical lower limit of {channel.critical_min:.2f} {channel.unit}."
        )
    if value > channel.critical_max:
        return (
            Severity.CRITICAL,
            f"{channel.display_name} is {value:.2f} {channel.unit}, "
            f"above critical upper limit of {channel.critical_max:.2f} {channel.unit}."
        )

    # 3. Warning Boundary Checks
    if value < channel.warning_min:
        return (
            Severity.WARNING,
            f"{channel.display_name} is {value:.2f} {channel.unit}, "
            f"below warning lower limit of {channel.warning_min:.2f} {channel.unit}."
        )
    if value > channel.warning_max:
        return (
            Severity.WARNING,
            f"{channel.display_name} is {value:.2f} {channel.unit}, "
            f"above warning upper limit of {channel.warning_max:.2f} {channel.unit}."
        )

    # 4. Standard Operational Bounds
    return Severity.NOMINAL, f"{channel.display_name} operates nominally ({value:.2f} {channel.unit})."


def evaluate_historical_deviation(
    channel: SensorChannel,
    current_value: Optional[float],
    historical_readings: List[float],
) -> Tuple[Severity, str, Optional[float]]:
    """
    Evaluate if the current reading sharply deviates from recent historical average.

    Requirements:
    - Excludes missing values (None).
    - Requires at least MIN_HISTORY_SAMPLES prior valid readings.
    - Evaluates absolute difference: |current_value - historical_mean| > threshold.

    Returns:
        (Severity, explanation_string, historical_mean_or_None)
    """
    if current_value is None:
        return Severity.NOMINAL, "Historical comparison skipped (missing reading).", None

    if len(historical_readings) < MIN_HISTORY_SAMPLES:
        return (
            Severity.NOMINAL,
            f"Insufficient historical data ({len(historical_readings)}/{MIN_HISTORY_SAMPLES} samples required).",
            None,
        )

    historical_mean = sum(historical_readings) / len(historical_readings)
    deviation = abs(current_value - historical_mean)

    if deviation > channel.max_historical_deviation:
        reason = (
            f"{channel.display_name} reading ({current_value:.2f} {channel.unit}) diverges by "
            f"{deviation:.2f} {channel.unit} from {len(historical_readings)}-frame historical average "
            f"({historical_mean:.2f} {channel.unit}), exceeding tolerance of {channel.max_historical_deviation:.2f} {channel.unit}."
        )
        return Severity.WARNING, reason, round(historical_mean, 2)

    return Severity.NOMINAL, "Within historical baseline limits.", round(historical_mean, 2)


def combine_severities(
    channel: SensorChannel,
    observed_value: Optional[float],
    threshold_severity: Severity,
    threshold_reason: str,
    historical_severity: Severity,
    historical_reason: str,
    historical_average: Optional[float],
) -> ChannelEvaluation:
    """
    Deterministically merge threshold and historical detection results.

    Precedence Hierarchy:
    - CRITICAL > WARNING > NOMINAL
    - If threshold is CRITICAL -> final is CRITICAL.
    - If either is WARNING -> final is WARNING.
    - If both are NOMINAL -> final is NOMINAL.
    """
    is_missing = observed_value is None

    # Determine final severity level
    if threshold_severity == Severity.CRITICAL or historical_severity == Severity.CRITICAL:
        final_severity = Severity.CRITICAL
    elif threshold_severity == Severity.WARNING or historical_severity == Severity.WARNING:
        final_severity = Severity.WARNING
    else:
        final_severity = Severity.NOMINAL

    # Determine detection category
    if is_missing:
        detection_type = DetectionType.MISSING_DATA
        combined_reason = threshold_reason
    elif threshold_severity != Severity.NOMINAL and historical_severity != Severity.NOMINAL:
        detection_type = DetectionType.COMBINED
        combined_reason = f"{threshold_reason} Additionally: {historical_reason}"
    elif threshold_severity != Severity.NOMINAL:
        detection_type = DetectionType.THRESHOLD
        combined_reason = threshold_reason
    elif historical_severity != Severity.NOMINAL:
        detection_type = DetectionType.HISTORICAL
        combined_reason = historical_reason
    else:
        detection_type = DetectionType.NONE
        combined_reason = "Nominal operations"

    return ChannelEvaluation(
        channel_name=channel.name,
        observed_value=observed_value,
        severity=final_severity,
        detection_type=detection_type,
        threshold_severity=threshold_severity,
        historical_severity=historical_severity,
        threshold_reason=threshold_reason,
        historical_reason=historical_reason,
        combined_reason=combined_reason,
        historical_average=historical_average,
    )


class AnomalyDetector:
    """
    Orchestrates threshold and historical telemetry anomaly detection.
    Interfaces with DatabaseManager to load historical baselines and record anomalies.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db

    def evaluate_channel(
        self,
        channel_name: str,
        value: Optional[float],
        exclude_frame_id: Optional[int] = None,
    ) -> ChannelEvaluation:
        """
        Perform complete threshold + historical analysis for a single channel.
        """
        channel = CHANNEL_CONFIGS[channel_name]

        # 1. Evaluate threshold limits
        t_sev, t_reason = evaluate_threshold(channel, value)

        # 2. Retrieve history from SQLite and evaluate historical deviation
        history = self.db.get_recent_valid_readings(
            channel_name=channel_name,
            limit=HISTORICAL_WINDOW_SIZE,
            exclude_frame_id=exclude_frame_id,
        )
        h_sev, h_reason, h_avg = evaluate_historical_deviation(channel, value, history)

        # 3. Combine results
        return combine_severities(
            channel=channel,
            observed_value=value,
            threshold_severity=t_sev,
            threshold_reason=t_reason,
            historical_severity=h_sev,
            historical_reason=h_reason,
            historical_average=h_avg,
        )

    def process_frame(
        self,
        frame: TelemetryFrame,
        frame_id: Optional[int] = None,
        save_anomalies: bool = True,
    ) -> FrameEvaluation:
        """
        Evaluate an entire TelemetryFrame across all channels.
        Optionally persists any detected anomalies to SQLite.

        Returns:
            FrameEvaluation with all channel details and overall spacecraft health.
        """
        channel_results: Dict[str, ChannelEvaluation] = {}
        anomalies: List[ChannelEvaluation] = []
        overall_severity = Severity.NOMINAL

        for channel_name, value in frame.readings.items():
            if channel_name not in CHANNEL_CONFIGS:
                continue

            eval_result = self.evaluate_channel(
                channel_name=channel_name,
                value=value,
                exclude_frame_id=frame_id,
            )
            channel_results[channel_name] = eval_result

            # Track highest overall severity
            if eval_result.severity == Severity.CRITICAL:
                overall_severity = Severity.CRITICAL
            elif eval_result.severity == Severity.WARNING and overall_severity != Severity.CRITICAL:
                overall_severity = Severity.WARNING

            # Record if abnormal
            if eval_result.severity != Severity.NOMINAL:
                anomalies.append(eval_result)
                if save_anomalies and frame_id is not None:
                    self.db.insert_anomaly(
                        frame_id=frame_id,
                        channel_name=channel_name,
                        observed_value=value,
                        severity=eval_result.severity.value,
                        detection_type=eval_result.detection_type.value,
                        reason=eval_result.combined_reason,
                        timestamp=frame.timestamp,
                    )

        return FrameEvaluation(
            frame=frame,
            frame_id=frame_id,
            overall_severity=overall_severity,
            channel_results=channel_results,
            anomalies=anomalies,
        )
