"""
test_networking.py - Unit tests for TCP Ground Station server and Spacecraft sender.
"""

import socket
import threading
import time
import unittest

from config import CHANNEL_CONFIGS
from fault_injector import FaultInjector
from ground_station import GroundStationServer
from sensor_simulator import SensorSimulator
from spacecraft_sender import SpacecraftSender
from telemetry import TelemetryFrame


def find_free_port() -> int:
    """Helper to find an unused local port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class TestNetworking(unittest.TestCase):
    def setUp(self):
        self.port = find_free_port()
        self.received_frames = []
        self.reported_errors = []
        self.frame_event = threading.Event()

        def on_frame(frame):
            self.received_frames.append(frame)
            self.frame_event.set()

        def on_error(err):
            self.reported_errors.append(err)

        self.server = GroundStationServer(
            host="127.0.0.1",
            port=self.port,
            on_frame_received=on_frame,
            on_error=on_error,
        )
        self.server.start()
        time.sleep(0.05)  # Allow socket to bind

    def tearDown(self):
        self.server.stop()

    def test_live_tcp_frame_exchange(self):
        sim = SensorSimulator(seed=101)
        injector = FaultInjector()
        sender = SpacecraftSender(
            simulator=sim,
            fault_injector=injector,
            host="127.0.0.1",
            port=self.port,
            interval=0.05,
        )

        sender.start()
        # Wait until at least 2 frames are received
        for _ in range(30):
            if len(self.received_frames) >= 2:
                break
            time.sleep(0.1)

        sender.stop()

        self.assertGreaterEqual(len(self.received_frames), 2)
        f1 = self.received_frames[0]
        self.assertEqual(f1.sequence_number, 1)
        self.assertEqual(f1.spacecraft_id, "Astraea-1")

    def test_partial_and_concatenated_stream_chunks(self):
        # Connect raw socket to test stream chunking directly
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(("127.0.0.1", self.port))

        frame1 = TelemetryFrame(
            spacecraft_id="Astraea-1",
            sequence_number=101,
            timestamp="2026-10-18T12:00:00Z",
            readings={name: ch.nominal_center for name, ch in CHANNEL_CONFIGS.items()},
        )
        frame2 = TelemetryFrame(
            spacecraft_id="Astraea-1",
            sequence_number=102,
            timestamp="2026-10-18T12:00:01Z",
            readings={name: ch.nominal_center for name, ch in CHANNEL_CONFIGS.items()},
        )

        b1 = frame1.to_bytes()
        b2 = frame2.to_bytes()

        # 1. Send first half of frame1
        half = len(b1) // 2
        client_sock.sendall(b1[:half])
        time.sleep(0.05)
        # Should not have received full frame yet
        self.assertEqual(len(self.received_frames), 0)

        # 2. Send second half of frame1 PLUS all of frame2 in single burst
        client_sock.sendall(b1[half:] + b2)
        time.sleep(0.1)

        client_sock.close()

        # Both frames should be assembled and parsed
        self.assertEqual(len(self.received_frames), 2)
        self.assertEqual(self.received_frames[0].sequence_number, 101)
        self.assertEqual(self.received_frames[1].sequence_number, 102)

    def test_corrupted_frame_does_not_crash_server(self):
        client_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client_sock.connect(("127.0.0.1", self.port))

        # Send corrupted JSON line
        client_sock.sendall(b'{"corrupted": json without close\n')
        time.sleep(0.05)

        # Send valid frame afterwards
        valid_frame = TelemetryFrame(
            spacecraft_id="Astraea-1",
            sequence_number=201,
            timestamp="2026-10-18T12:00:00Z",
            readings={name: ch.nominal_center for name, ch in CHANNEL_CONFIGS.items()},
        )
        client_sock.sendall(valid_frame.to_bytes())
        time.sleep(0.1)

        client_sock.close()

        # Server should report the error and successfully process the valid frame
        self.assertGreaterEqual(len(self.reported_errors), 1)
        self.assertIn("Malformed JSON", self.reported_errors[0])
        self.assertEqual(len(self.received_frames), 1)
        self.assertEqual(self.received_frames[0].sequence_number, 201)


if __name__ == "__main__":
    unittest.main()
