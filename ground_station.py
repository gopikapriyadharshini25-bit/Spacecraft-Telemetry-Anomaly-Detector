"""
ground_station.py - TCP Ground Station Telemetry Receiver Server

This module runs a local TCP server representing the ground telemetry receiver:
1. Listens on a local port (default 127.0.0.1:8765).
2. Buffers incoming stream bytes and reconstructs messages across newline boundaries
   (Newline-Delimited JSON / NDJSON stream protocol).
3. Safely parses and validates incoming telemetry frames against the spacecraft schema.
4. Forwards validated frames to a pipeline callback for database storage, anomaly
   detection, and dashboard dispatch.
5. Handles client disconnections, connection errors, and clean shutdown without hangs.
"""

import logging
import socket
import threading
from typing import Callable, Optional

from config import DEFAULT_HOST, DEFAULT_PORT, MAX_BUFFER_BYTES, SOCKET_TIMEOUT_SECONDS
from telemetry import TelemetryFrame, parse_and_validate_raw_line

logger = logging.getLogger(__name__)


class GroundStationServer:
    """
    TCP server that receives, reassembles, and validates Astraea-1 telemetry streams.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        on_frame_received: Optional[Callable[[TelemetryFrame], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_connection_change: Optional[Callable[[bool], None]] = None,
    ):
        self.host = host
        self.port = port
        self.on_frame_received = on_frame_received
        self.on_error = on_error
        self.on_connection_change = on_connection_change

        self._server_sock: Optional[socket.socket] = None
        self._stop_event = threading.Event()
        self._listen_thread: Optional[threading.Thread] = None

        self._is_running = False
        self._client_connected = False
        self.frames_received_count = 0
        self.errors_count = 0
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def client_connected(self) -> bool:
        return self._client_connected

    def start(self) -> None:
        """Start the TCP ground station server in a background worker thread."""
        with self._lock:
            if self._is_running:
                return

            self._stop_event.clear()
            self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_sock.settimeout(SOCKET_TIMEOUT_SECONDS)

            try:
                self._server_sock.bind((self.host, self.port))
                self._server_sock.listen(1)
            except Exception as err:
                self._server_sock.close()
                self._server_sock = None
                raise RuntimeError(f"Could not bind ground station server to {self.host}:{self.port}: {err}")

            self._is_running = True
            self._listen_thread = threading.Thread(
                target=self._server_loop,
                name="GroundStation-ListenerThread",
                daemon=True,
            )
            self._listen_thread.start()

    def stop(self) -> None:
        """Signal the server loop to stop and close all open sockets."""
        self._stop_event.set()
        with self._lock:
            self._is_running = False
            self._client_connected = False

            if self._server_sock:
                try:
                    self._server_sock.close()
                except Exception:
                    pass
                self._server_sock = None

        if self._listen_thread and self._listen_thread.is_alive():
            self._listen_thread.join(timeout=2.0)
            self._listen_thread = None

        if self.on_connection_change:
            try:
                self.on_connection_change(False)
            except Exception:
                pass

    def _server_loop(self) -> None:
        """Main listener loop waiting for spacecraft telemetry connections."""
        while not self._stop_event.is_set():
            try:
                client_sock, client_addr = self._server_sock.accept()
            except socket.timeout:
                continue
            except (socket.error, OSError):
                # Socket was closed during shutdown
                break

            with self._lock:
                self._client_connected = True
            if self.on_connection_change:
                self.on_connection_change(True)

            self._handle_client(client_sock)

            with self._lock:
                self._client_connected = False
            if self.on_connection_change:
                self.on_connection_change(False)

    def _handle_client(self, client_sock: socket.socket) -> None:
        """
        Handle a connected client stream. Reconstructs newline-delimited JSON frames
        handling partial packet chunks and multi-packet bursts gracefully.
        """
        client_sock.settimeout(SOCKET_TIMEOUT_SECONDS)
        buffer = ""

        try:
            while not self._stop_event.is_set():
                try:
                    chunk = client_sock.recv(4096)
                except socket.timeout:
                    continue
                except (socket.error, OSError):
                    break

                if not chunk:
                    # Client cleanly closed connection
                    break

                try:
                    decoded = chunk.decode("utf-8")
                except UnicodeDecodeError as err:
                    self._report_error(f"Stream encoding error: {err}")
                    continue

                buffer += decoded

                # Protect against excessive memory consumption
                if len(buffer) > MAX_BUFFER_BYTES:
                    self._report_error("Stream buffer overflow; clearing corrupted buffer.")
                    buffer = ""
                    continue

                # Process all complete lines delimited by newline '\n'
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    clean_line = line.strip()
                    if not clean_line:
                        continue

                    frame, err = parse_and_validate_raw_line(clean_line)
                    if err:
                        self._report_error(err)
                        continue

                    if frame and self.on_frame_received:
                        with self._lock:
                            self.frames_received_count += 1
                        try:
                            self.on_frame_received(frame)
                        except Exception as callback_err:
                            self._report_error(f"Pipeline processing error: {callback_err}")

        finally:
            try:
                client_sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            client_sock.close()

    def _report_error(self, message: str) -> None:
        """Record and dispatch telemetry stream error."""
        with self._lock:
            self.errors_count += 1
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                pass
