"""
telemetry.py - Telemetry Frame Structure, Serialization, and Stream Validation

This module handles:
1. The TelemetryFrame dataclass representing a discrete downlink packet.
2. JSON serialization and newline-delimited JSON (NDJSON) formatting for TCP.
3. Strict frame validation: verifying schema, data types, numbers (rejecting
   NaN and Inf), timestamps, and spacecraft identity.
"""

from dataclasses import dataclass, asdict
from datetime import datetime
import json
import math
from typing import Any, Dict, Optional, Tuple

from config import CHANNEL_CONFIGS, SPACECRAFT_ID


@dataclass
class TelemetryFrame:
    """
    Represents a single telemetry packet transmitted by Astraea-1.

    Attributes:
        spacecraft_id: Name/callsign of the transmitting spacecraft.
        sequence_number: Monotonically increasing packet sequence counter.
        timestamp: ISO 8601 formatted UTC timestamp string.
        readings: Dictionary mapping channel names to sensor values (or None if missing).
    """
    spacecraft_id: str
    sequence_number: int
    timestamp: str
    readings: Dict[str, Optional[float]]

    def to_dict(self) -> Dict[str, Any]:
        """Convert the frame to a standard Python dictionary."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert the frame into a JSON formatted string."""
        return json.dumps(self.to_dict())

    def to_bytes(self) -> bytes:
        """
        Encode frame as newline-delimited JSON (NDJSON) bytes for TCP transport.
        Trailing newline is used by the receiver as a message frame delimiter.
        """
        return (self.to_json() + "\n").encode("utf-8")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TelemetryFrame":
        """Reconstruct a TelemetryFrame instance from a validated dictionary."""
        return cls(
            spacecraft_id=str(data["spacecraft_id"]),
            sequence_number=int(data["sequence_number"]),
            timestamp=str(data["timestamp"]),
            readings=dict(data["readings"]),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "TelemetryFrame":
        """Parse a JSON string into a TelemetryFrame."""
        data = json.loads(json_str)
        return cls.from_dict(data)


def validate_telemetry_dict(data: Any) -> Tuple[bool, str]:
    """
    Validate raw dictionary structure and values against spacecraft protocol rules.

    Returns:
        (is_valid, error_reason)
        If valid, returns (True, "").
        If invalid, returns (False, descriptive_reason).
    """
    if not isinstance(data, dict):
        return False, "Telemetry frame root must be a JSON object (dictionary)."

    required_keys = {"spacecraft_id", "sequence_number", "timestamp", "readings"}
    missing_keys = required_keys - set(data.keys())
    if missing_keys:
        return False, f"Missing required fields: {', '.join(sorted(missing_keys))}."

    # 1. Validate spacecraft_id
    spacecraft_id = data.get("spacecraft_id")
    if not isinstance(spacecraft_id, str) or not spacecraft_id.strip():
        return False, "spacecraft_id must be a non-empty string."

    # 2. Validate sequence_number
    seq = data.get("sequence_number")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 0:
        return False, f"sequence_number must be a non-negative integer; got {seq!r}."

    # 3. Validate timestamp (ISO 8601 format)
    timestamp_str = data.get("timestamp")
    if not isinstance(timestamp_str, str):
        return False, "timestamp must be a string."
    try:
        datetime.fromisoformat(timestamp_str)
    except (ValueError, TypeError):
        return False, f"timestamp is not a valid ISO 8601 string: {timestamp_str!r}."

    # 4. Validate readings dictionary
    readings = data.get("readings")
    if not isinstance(readings, dict):
        return False, "readings must be a dictionary of sensor channels."

    # Ensure recognized channels and safe numeric values
    for channel_name, val in readings.items():
        if channel_name not in CHANNEL_CONFIGS:
            return False, f"Unrecognized sensor channel name: {channel_name!r}."

        if val is None:
            # Explicitly allowed (simulates missing sensor data)
            continue

        if not isinstance(val, (int, float)) or isinstance(val, bool):
            return False, f"Reading for '{channel_name}' must be numeric or null; got {val!r}."

        # Reject NaN and Infinity
        if math.isnan(val) or math.isinf(val):
            return False, f"Reading for '{channel_name}' contains illegal numeric value: {val}."

    return True, ""


def parse_and_validate_raw_line(raw_line: str) -> Tuple[Optional[TelemetryFrame], str]:
    """
    Parse a single raw string line from TCP stream, deserialize JSON, and validate.

    Returns:
        (frame, error_message)
        If successful: (TelemetryFrame, "")
        If malformed: (None, error_message)
    """
    clean_line = raw_line.strip()
    if not clean_line:
        return None, "Empty telemetry line received."

    try:
        payload = json.loads(clean_line)
    except json.JSONDecodeError as err:
        return None, f"Malformed JSON syntax: {err.msg} at line {err.lineno} col {err.colno}."

    is_valid, reason = validate_telemetry_dict(payload)
    if not is_valid:
        return None, f"Telemetry validation failed: {reason}"

    frame = TelemetryFrame.from_dict(payload)
    return frame, ""
