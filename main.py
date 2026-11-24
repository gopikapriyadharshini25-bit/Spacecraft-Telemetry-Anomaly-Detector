"""
main.py - Spacecraft Telemetry and Anomaly Detector Entry Point

This is the primary launch script for Astraea-1 Ground Operations:
1. Desktop Mode (Default): Launches the full Tkinter Ground Station GUI.
   Command: python main.py

2. Headless Demonstration Mode: Runs an automated end-to-end terminal demonstration
   exercising normal telemetry, fault injection (Spike, Drift, Missing), detection,
   and SQLite persistence without opening the Tkinter window.
   Command: python main.py --demo
"""

import argparse
import sys
import time
import tkinter as tk

# Ensure Windows terminal handles UTF-8 gracefully if possible
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from anomaly_detector import AnomalyDetector
from config import (
    DEFAULT_DB_PATH,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SIMULATION_INTERVAL_SEC,
    FaultType,
)
from database import DatabaseManager
from fault_injector import FaultInjector
from ground_station import GroundStationServer
from sensor_simulator import SensorSimulator
from spacecraft_sender import SpacecraftSender


def run_headless_demo(host: str, port: int, db_path: str) -> None:
    """
    Run an automated end-to-end demonstration in terminal mode.
    Exercises TCP networking, nominal flow, fault injection, detection, and database.
    """
    print("\n" + "=" * 70)
    print("[ASTRAEA-1] SPACECRAFT TELEMETRY & ANOMALY DETECTOR - AUTOMATED DEMO")
    print("=" * 70)

    # 1. Initialize Subsystems
    print("\n[1/5] Initializing Database, Detector, and Fault Injector...")
    db = DatabaseManager(db_path=db_path)
    detector = AnomalyDetector(db)
    fault_injector = FaultInjector()
    simulator = SensorSimulator(seed=42)

    frames_processed = []

    def on_frame_received(frame):
        frame_id = db.insert_telemetry_frame(frame)
        eval_result = detector.process_frame(frame, frame_id=frame_id, save_anomalies=True)
        frames_processed.append(eval_result)
        status_tag = f"[{eval_result.overall_severity.value}]"
        print(f"  -> Frame #{frame.sequence_number:02d} received via TCP | Status: {status_tag:<10} | Anomalies: {len(eval_result.anomalies)}")

    # 2. Start TCP Ground Station Server
    print(f"\n[2/5] Starting Ground Station TCP Server on {host}:{port}...")
    server = GroundStationServer(
        host=host,
        port=port,
        on_frame_received=on_frame_received,
        on_error=lambda err: print(f"  [ERROR] Receiver stream error: {err}"),
    )
    server.start()
    time.sleep(0.1)

    # 3. Start Spacecraft Sender
    print("[3/5] Starting Astraea-1 Spacecraft Telemetry Transmitter...")
    sender = SpacecraftSender(
        simulator=simulator,
        fault_injector=fault_injector,
        host=host,
        port=port,
        interval=0.2,  # Rapid interval for demo
    )
    sender.start()

    try:
        # Phase A: Nominal Operation (Frames 1-4)
        print("\n--- Phase A: Generating Nominal Telemetry (Frames 1-4) ---")
        time.sleep(0.9)

        # Phase B: Inject SPIKE Fault on battery_voltage (Frame 5)
        print("\n--- Phase B: Injecting SPIKE fault on battery_voltage ---")
        fault_injector.set_fault("battery_voltage", FaultType.SPIKE)
        time.sleep(0.5)

        # Phase C: Inject DRIFT Fault on power_bus_consumption (Frames 6-8)
        print("\n--- Phase C: Injecting progressive DRIFT fault on power_bus_consumption ---")
        fault_injector.set_fault("power_bus_consumption", FaultType.DRIFT)
        time.sleep(0.7)

        # Phase D: Inject MISSING Sensor Telemetry (Frame 9)
        print("\n--- Phase D: Injecting MISSING telemetry on internal_temp ---")
        fault_injector.set_fault("internal_temp", FaultType.MISSING)
        time.sleep(0.5)

        # Phase E: Clear Faults and return to Nominal
        print("\n--- Phase E: Clearing all faults (Return to Nominal) ---")
        fault_injector.clear_fault()
        time.sleep(0.6)

    finally:
        print("\n[4/5] Halting Spacecraft Transmitter & Ground Station Server...")
        sender.stop()
        server.stop()

    # 4. Verification and Summary
    print("\n[5/5] Querying SQLite Database for Mission Results:")
    stats = db.get_summary_stats()
    print("-" * 50)
    print(f"  Total Frames Stored:      {stats['total_frames']}")
    print(f"  Warning Anomalies:        {stats['warning_count']}")
    print(f"  Critical Anomalies:       {stats['critical_count']}")
    print(f"  Historical Divergences:   {stats['historical_anomaly_count']}")
    print("-" * 50)

    recent_anomalies = db.get_recent_anomalies(limit=5)
    print("\nRecent Detected Anomaly Records in SQLite:")
    for a in recent_anomalies:
        print(f"  [{a['severity']:<8}] Channel: {a['channel_name']:<22} | Type: {a['detection_type']:<12} | Reason: {a['reason']}")

    db.close()
    print("\n" + "=" * 70)
    print("[SUCCESS] END-TO-END DEMONSTRATION COMPLETED SUCCESSFULLY")
    print("=" * 70 + "\n")


def run_gui(host: str, port: int, db_path: str, interval: float) -> None:
    """Launch the interactive Tkinter Ground Station Desktop GUI."""
    db = DatabaseManager(db_path=db_path)
    detector = AnomalyDetector(db)
    fault_injector = FaultInjector()
    simulator = SensorSimulator()

    server = GroundStationServer(host=host, port=port)
    sender = SpacecraftSender(
        simulator=simulator,
        fault_injector=fault_injector,
        host=host,
        port=port,
        interval=interval,
    )

    root = tk.Tk()
    from dashboard import GroundStationDashboard
    app = GroundStationDashboard(
        root=root,
        db=db,
        server=server,
        sender=sender,
        detector=detector,
        fault_injector=fault_injector,
    )
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Astraea-1 Spacecraft Telemetry Simulation & Anomaly Detector"
    )
    parser.add_argument("--demo", action="store_true", help="Run automated end-to-end terminal demo")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"TCP host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"TCP port (default: {DEFAULT_PORT})")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help=f"SQLite database file (default: {DEFAULT_DB_PATH})")
    parser.add_argument("--interval", type=float, default=DEFAULT_SIMULATION_INTERVAL_SEC, help="Simulation tick interval in seconds")

    args = parser.parse_args()

    if args.demo:
        run_headless_demo(host=args.host, port=args.port, db_path=args.db)
    else:
        run_gui(host=args.host, port=args.port, db_path=args.db, interval=args.interval)


if __name__ == "__main__":
    main()
