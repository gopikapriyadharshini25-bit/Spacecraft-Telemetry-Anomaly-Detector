"""
spacecraft_sender.py - TCP Telemetry Transmitter for Astraea-1

This module simulates the onboard transmitter for the Astraea-1 spacecraft:
1. Connects via TCP client socket to the Ground Station receiver.
2. Periodically samples sensor readings from the SensorSimulator.
3. Applies any active faults from the FaultInjector.
4. Serializes the telemetry packet to Newline-Delimited JSON (NDJSON).
5. Transmits frames across the network link at a configurable telemetry rate.
6. Handles connection retries, disconnections, and safe stop events.
"""

import logging
import socket
import threading
import time
from typing import Callable, Optional

from config import DEFAULT_HOST, DEFAULT_PORT, DEFAULT_SIMULATION_INTERVAL_SEC
from fault_injector import FaultInjector
from sensor_simulator import SensorSimulator
from telemetry import TelemetryFrame

logger = logging.getLogger(__name__)


class SpacecraftSender:
    """
    Simulates onboard telemetry packaging and transmission over TCP.
    """

    def __init__(
        self,
        simulator: SensorSimulator,
        fault_injector: FaultInjector,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        interval: float = DEFAULT_SIMULATION_INTERVAL_SEC,
        on_frame_sent: Optional[Callable[[TelemetryFrame], None]] = None,
        on_status_change: Optional[Callable[[str], None]] = None,
    ):
        self.simulator = simulator
        self.fault_injector = fault_injector
        self.host = host
        self.port = port
        self.interval = interval
        self.on_frame_sent = on_frame_sent
        self.on_status_change = on_status_change

        self._stop_event = threading.Event()
        self._send_thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

        self._is_running = False
        self.sequence_number = 0
        self.frames_sent_count = 0
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> None:
        """Start the periodic telemetry transmission thread."""
        with self._lock:
            if self._is_running:
                return
            self._stop_event.clear()
            self._is_running = True
            self._send_thread = threading.Thread(
                target=self._transmit_loop,
                name="SpacecraftSender-WorkerThread",
                daemon=True,
            )
            self._send_thread.start()

    def stop(self) -> None:
        """Signal transmitter to halt and close connection."""
        self._stop_event.set()
        with self._lock:
            self._is_running = False
            if self._sock:
                try:
                    self._sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None

        if self._send_thread and self._send_thread.is_alive():
            self._send_thread.join(timeout=2.0)
            self._send_thread = None

        self._notify_status("Transmitter stopped")

    def reset_sequence(self) -> None:
        """Reset packet sequence counter and counters."""
        with self._lock:
            self.sequence_number = 0
            self.frames_sent_count = 0

    def generate_next_frame(self) -> TelemetryFrame:
        """Generate and package the next sequential telemetry frame with fault injection."""
        with self._lock:
            self.sequence_number += 1
            seq = self.sequence_number

        base_frame = self.simulator.generate_frame(sequence_number=seq)
        # Apply fault injection non-destructively
        modified_readings = self.fault_injector.apply_fault(base_frame.readings)
        base_frame.readings = modified_readings
        return base_frame

    def _transmit_loop(self) -> None:
        """Main periodic transmission loop."""
        self._notify_status("Connecting to Ground Station...")

        while not self._stop_event.is_set():
            # 1. Establish connection if not already connected
            if not self._sock:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2.0)
                    sock.connect((self.host, self.port))
                    with self._lock:
                        self._sock = sock
                    self._notify_status("Connected and transmitting")
                except (socket.error, ConnectionRefusedError):
                    self._notify_status(f"Waiting for Ground Station at {self.host}:{self.port}...")
                    # Backoff sleep checking stop_event
                    for _ in range(10):
                        if self._stop_event.is_set():
                            return
                        time.sleep(0.1)
                    continue

            # 2. Generate and transmit next frame
            frame = self.generate_next_frame()
            payload = frame.to_bytes()

            try:
                self._sock.sendall(payload)
                with self._lock:
                    self.frames_sent_count += 1
                if self.on_frame_sent:
                    try:
                        self.on_frame_sent(frame)
                    except Exception:
                        pass
            except (socket.error, BrokenPipeError, OSError) as err:
                self._notify_status(f"Transmission link lost: {err}")
                with self._lock:
                    if self._sock:
                        try:
                            self._sock.close()
                        except Exception:
                            pass
                        self._sock = None
                time.sleep(0.5)
                continue

            # 3. Responsive sleep until next transmission tick
            elapsed = 0.0
            step = 0.05
            while elapsed < self.interval and not self._stop_event.is_set():
                time.sleep(step)
                elapsed += step

    def _notify_status(self, message: str) -> None:
        if self.on_status_change:
            try:
                self.on_status_change(message)
            except Exception:
                pass
