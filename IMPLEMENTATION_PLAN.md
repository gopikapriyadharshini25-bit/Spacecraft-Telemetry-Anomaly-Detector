# Implementation Plan: Spacecraft Telemetry and Anomaly Detector (Astraea-1)

This document outlines the technical design, module structure, and step-by-step implementation phases for **Astraea-1**, an educational, explainable spacecraft telemetry simulation and anomaly detection system.

---

## 1. System Overview & Technology Stack

The project models an end-to-end spacecraft telemetry downlink:
1. **Spacecraft Simulator (`Astraea-1`)**: Generates 9 fictional sensor readings within documented nominal boundaries.
2. **Fault Injector**: Selectively injects Spike, Drift, Stuck, or Missing data faults into any sensor channel.
3. **Telemetry Encoder**: Packages readings into versioned, timestamped JSON frames with sequence numbers.
4. **TCP Uplink/Downlink**: Transmits newline-delimited JSON (NDJSON) over a local TCP socket connection (`127.0.0.1:8765`).
5. **Ground Station Receiver**: Reconstructs frames from raw byte streams, parses NDJSON, and validates data integrity.
6. **Rule-Based Anomaly Detector**:
   - **Threshold Detection**: Compares readings against nominal, warning, and critical ranges.
   - **Historical Detection**: Compares readings against an $N$-frame rolling mean computed from persistent SQLite history.
   - **Severity Classifier**: Merges findings into `NOMINAL`, `WARNING`, or `CRITICAL` with human-readable explanations.
7. **SQLite Database**: Persists all incoming telemetry frames and detected anomaly records.
8. **Tkinter Ground Control Dashboard**: A desktop GUI displaying real-time telemetry tables, anomaly logs, status cards, simulation controls, and embedded historical Matplotlib trend charts.

### Technology Stack
- **Language**: Python 3.14 (Standard library focus: `socket`, `threading`, `queue`, `sqlite3`, `json`, `dataclasses`, `enum`, `datetime`, `random`, `tkinter`).
- **Visualization**: `matplotlib` (embedded in Tkinter via `FigureCanvasTkAgg`).
- **Testing**: `unittest` with 100% automated test coverage across all subsystems.

---

## 2. Target File Structure

```text
Spacecraft Telemetry and Anomaly Detector/
├── config.py                 # Sensor channel ranges, limits, units, network & DB configurations
├── telemetry.py              # TelemetryFrame dataclass, JSON serialization, and stream validation
├── sensor_simulator.py       # Nominal telemetry generator for Astraea-1
├── fault_injector.py         # Fault injection engine (Spike, Drift, Stuck, Missing)
├── spacecraft_sender.py      # TCP client transmitting telemetry frames
├── ground_station.py         # TCP server buffering, assembling, and validating frames
├── database.py               # SQLite schema creation, inserts, and historical queries
├── anomaly_detector.py       # Threshold, historical rolling average, and severity classification
├── dashboard.py              # Tkinter GUI ground control station (live tables, controls, charts)
├── main.py                   # Unified application entry point (GUI & Headless demo modes)
│
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_sensor_simulator.py
│   ├── test_fault_injector.py
│   ├── test_telemetry.py
│   ├── test_detector.py
│   ├── test_database.py
│   ├── test_historical_detector.py
│   ├── test_networking.py
│   └── test_integration.py
│
├── docs/
│   ├── architecture.md       # Detailed system design, data flow, threading, protocol, DB schema
│   └── viva_guide.md         # Comprehensive college viva prep, FAQs, algorithm walkthroughs
│
└── README.md                 # Complete setup, execution, demonstration guide, and troubleshooting
```

---

## 3. Sensor Channels & Limits Specification

The system simulates 9 spacecraft subsystems with documented physical ranges:

| Channel Name | Display Name | Unit | Nominal Range | Warning Range | Critical Range |
| :--- | :--- | :---: | :---: | :---: | :---: |
| `battery_voltage` | Battery Voltage | V | [34.0, 38.0] | [32.0, 40.0] | [30.0, 42.0] |
| `battery_temp` | Battery Temperature | °C | [15.0, 30.0] | [5.0, 40.0] | [0.0, 50.0] |
| `battery_charge` | State of Charge | % | [60.0, 95.0] | [40.0, 100.0] | [20.0, 100.0] |
| `solar_panel_current` | Solar Array Current | A | [8.0, 12.0] | [5.0, 14.0] | [2.0, 16.0] |
| `power_bus_consumption`| Power Bus Load | W | [250.0, 350.0] | [200.0, 420.0] | [150.0, 500.0] |
| `comm_signal_strength`| Comm Signal (RSSI) | dBm | [-80.0, -50.0] | [-95.0, -40.0] | [-110.0, -30.0] |
| `internal_temp` | Avionics Internal Temp | °C | [18.0, 24.0] | [10.0, 32.0] | [5.0, 40.0] |
| `fuel_pressure` | RCS Thruster Fuel Press| psi | [280.0, 320.0] | [240.0, 350.0] | [200.0, 380.0] |
| `reaction_wheel_rpm` | Reaction Wheel Speed | RPM | [1500, 3500] | [800, 4200] | [200, 5000] |

---

## 4. Phased Implementation Roadmap

- **Phase 1**: Core Configuration & Telemetry Format (`config.py`, `telemetry.py`, unit tests)
- **Phase 2**: Sensor Simulation & Fault Injection (`sensor_simulator.py`, `fault_injector.py`, unit tests)
- **Phase 3**: SQLite Persistence Layer (`database.py`, unit tests)
- **Phase 4**: Anomaly Detection Engine (`anomaly_detector.py`, threshold & rolling history detection, unit tests)
- **Phase 5**: TCP Networking (`spacecraft_sender.py`, `ground_station.py`, stream buffering, unit & socket tests)
- **Phase 6**: Ground Station Dashboard (`dashboard.py`, `main.py`, Tkinter GUI + thread-safe queue + Matplotlib)
- **Phase 7**: Comprehensive Integration Testing (`tests/test_integration.py`)
- **Phase 8**: Documentation & College Viva Guide (`README.md`, `docs/architecture.md`, `docs/viva_guide.md`)
