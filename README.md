# Spacecraft Telemetry and Anomaly Detector (Astraea-1)

A complete, educational, and explainable Python ground station monitoring system simulating the **Astraea-1** spacecraft. The system simulates 9 sensor telemetry channels, transmits data across an authentic local TCP link using Newline-Delimited JSON (NDJSON), injects artificial subsystem faults, detects anomalies using static thresholds and historical rolling-averages from SQLite, and displays live metrics in a responsive Tkinter desktop dashboard.



## 1. Project Objective

The primary objective of this project is to model an authentic aerospace telemetry downlink and ground control monitoring station. It demonstrates:
- How spacecraft sensor streams are formatted, packaged, and transmitted across TCP sockets.
- How ground systems handle stream fragmentation, validate schemas, and reject corrupted packets.
- How dual-layer anomaly detection combines physical safety thresholds with historical rolling-average baseline checks.
- How persistent telemetry is stored and audited using an SQLite relational database.
- How to build a responsive, multi-threaded desktop GUI in Python using `tkinter` and thread-safe queues.

---

## 2. Problem Statement

During space missions, spacecraft subsystems (electrical power, thermal management, propulsion, communication) operate in extreme environments. Sensors can suffer from sudden electrical spikes, sensor calibration drift, telemetry line dropouts, or data freezes. Relying only on static safety limits fails to catch progressive degradation before a critical failure occurs.

This project solves this by:
1. Monitoring 9 realistic spacecraft subsystem channels against hierarchical warning and critical limits.
2. Continually comparing incoming readings against an $N$-frame rolling mean stored in SQLite to detect abnormal divergence.
3. Classifying severity into `NOMINAL`, `WARNING`, or `CRITICAL` with human-readable causal explanations.

---

## 3. Project Scope and Limitations

### In Scope
- **9 Subsystems**: Battery Bus Voltage, Battery Cell Temperature, State of Charge, Solar Array Current, Power Bus Load, Comm Signal Strength (RSSI), Avionics Internal Temperature, RCS Fuel Pressure, and Reaction Wheel RPM.
- **4 Artificial Fault Modes**: `SPIKE`, `DRIFT`, `STUCK`, and `MISSING` data.
- **Authentic Local TCP Socket**: Client-server architecture over `127.0.0.1:8765` using NDJSON framing.
- **Dual-Layer Rule-Based Detection**: Threshold comparison + SQLite rolling average deviation.
- **SQLite Relational Persistence**: Complete frame history, individual channel readings, and anomaly log.
- **Tkinter Desktop Dashboard**: Live telemetry table with color-coded severity tags, anomaly log, simulation controls, summary cards, and embedded Matplotlib historical trend graphs.

### Limitations
- Runs on local loopback (`127.0.0.1`) rather than physical radio frequency hardware.
- Rule-based mathematical models are used instead of machine learning to ensure 100% explainability and transparency for college viva defense.
- Models a single spacecraft (**Astraea-1**) rather than an entire constellation.

---

## 4. Technologies Used and Why

| Technology | Purpose | Justification |
| :--- | :--- | :--- |
| **Python 3** | Core Programming Language | Clean syntax, rich standard library, beginner-friendly. |
| **`socket`** | TCP Client-Server Communication | Low-level networking demonstrating stream buffering and NDJSON framing. |
| **`sqlite3`** | Local Relational Database | Built-in, zero-setup, ACID-compliant, persists across application restarts. |
| **`tkinter` & `ttk`**| Desktop Dashboard GUI | Native standard library GUI toolkit; requires no heavy web frameworks. |
| **`matplotlib`** | Historical Trend Visualization | Embedded into Tkinter via `FigureCanvasTkAgg` to plot time-series data with safety bands. |
| **`threading` & `queue`**| Concurrency & Thread-Safety | Prevents network I/O from blocking the GUI event loop; queue ensures safe main-thread updates. |
| **`unittest`** | Automated Verification | Built-in testing framework covering 100% of subsystems (44 test cases). |

---

## 5. File Structure

```text
Spacecraft Telemetry and Anomaly Detector/
│
├── config.py                 # 9 sensor channels, limits, network defaults, and severity enums
├── telemetry.py              # TelemetryFrame dataclass, JSON serialization, NDJSON stream parsing
├── sensor_simulator.py       # Astraea-1 nominal telemetry generator with Gaussian noise
├── fault_injector.py         # Spike, Drift, Stuck, and Missing fault engine
├── spacecraft_sender.py      # TCP client transmitting telemetry frames
├── ground_station.py         # TCP server buffering, assembling, and validating frames
├── database.py               # SQLite schema creation, inserts, and historical rolling queries
├── anomaly_detector.py       # Threshold, historical rolling average, and severity fusion logic
├── dashboard.py              # Tkinter GUI Ground Control Station with embedded Matplotlib chart
├── main.py                   # Unified entry point (Desktop GUI mode and Headless Demo mode)
│
├── tests/                    # 44 Automated Unit & Integration Tests
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
│   ├── architecture.md       # Detailed data flow, threading model, and SQL schema
│   └── viva_guide.md         # College viva questions, answers, and algorithm walkthroughs
│
└── README.md                 # Complete project documentation and demonstration guide
```

---

## 6. Installation & Execution

### Prerequisites
- Python 3.10+ (tested on Python 3.14).
- Optional: `matplotlib` (already pre-installed or install via `pip install matplotlib`).

### Quick Start: Launch the Desktop GUI
Open a terminal in the project directory and run:

```bash
python main.py
```

### Automated Headless Demonstration Mode
To run an automated 15-second terminal demonstration that exercises TCP networking, nominal flow, all 4 fault types, anomaly detection, and database queries without opening the GUI window:

```bash
python main.py --demo
```

### Running the Full Automated Test Suite
Run all 44 unit and integration tests:

```bash
python -m unittest discover tests
```

---

## 7. Step-by-Step Demonstration Workflow

Follow these steps during a college demonstration or project review:

1. **Launch the Dashboard**:
   ```bash
   python main.py
   ```
2. **Start the Telemetry Link**:
   - Click the **"▶ Start Simulation"** button in the controls panel.
   - Observe the **TCP LINK** pill switch to `CONNECTED` (green) and the **SIMULATOR** status switch to `RUNNING`.
   - The 9 sensor channels will begin updating every second with nominal readings.
   - The overall mission health badge displays `NOMINAL` (emerald green).
3. **Inject an Abrupt SPIKE Fault**:
   - In the "Artificial Fault Injection" box:
     - Target Channel: `Battery Bus Voltage (battery_voltage)`
     - Fault Type: `SPIKE`
     - Click **"⚡ Inject Fault"**.
   - Observe:
     - Voltage immediately spikes to ~48.0 V.
     - Row turns red (`CRITICAL`).
     - Mission Health badge changes to `CRITICAL`.
     - Anomaly Log records: *"Battery Bus Voltage is 48.00 V, above critical upper limit of 42.00 V."*
4. **Inject a Progressive DRIFT Fault**:
   - Target Channel: `Power Bus Load (power_bus_consumption)`
   - Fault Type: `DRIFT`
   - Click **"⚡ Inject Fault"**.
   - Observe the reading gradually climb with each frame. Once it diverges from the 10-frame rolling average by >45 W, a `HISTORICAL` anomaly warning triggers before critical limits are breached!
5. **Inject a MISSING Telemetry Fault**:
   - Target Channel: `Avionics Internal Temp (internal_temp)`
   - Fault Type: `MISSING`
   - Click **"⚡ Inject Fault"**.
   - Observe reading display `NULL (MISSING)` in amber text, logging a `MISSING_DATA` warning.
6. **Clear Faults & Return to Nominal**:
   - Click **"🔄 Clear Faults"**.
   - Sensors return to nominal boundaries and system health restores to `NOMINAL`.
7. **Inspect Historical Trend Chart**:
   - Click the bottom tab: **"📈 Historical Telemetry Visualizer"**.
   - Select `Battery Bus Voltage (battery_voltage)` and click **"🔄 Render Historical Trend"**.
   - View the plotted time-series curve showing nominal boundaries (dashed green), warning limits (dotted yellow), and critical limits (dash-dot red).
8. **Stop Simulation & Exit**:
   - Click **"⏹ Stop Simulation"**.
   - Close the window. All background threads and database locks terminate cleanly.

---

## 8. Database Location & Reset Instructions

- **Database File**: Stored in the root project directory as `spacecraft_telemetry.db`.
- **Inspecting with SQLite CLI**:
  ```bash
  sqlite3 spacecraft_telemetry.db "SELECT * FROM anomalies ORDER BY id DESC LIMIT 5;"
  ```
- **Resetting the Database**:
  Simply delete or rename `spacecraft_telemetry.db`:
  ```bash
  # Windows PowerShell:
  Remove-Item spacecraft_telemetry.db
  # Linux / macOS:
  rm spacecraft_telemetry.db
  ```
  The application will automatically recreate fresh, clean tables upon the next startup.

---

## 9. Troubleshooting

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| `Address already in use` error on port 8765 | A previous run or zombie process holds the port. | Run `python main.py --port 8790` to use an alternate port. |
| Tkinter window does not open | Running in a headless SSH session without X11. | Run `python main.py --demo` for terminal demonstration mode. |
| Matplotlib import warning | Matplotlib not installed in virtual environment. | Run `pip install matplotlib` or view historical data in SQLite directly. |

---

## 10. Educational & Viva Resources

For detailed architecture diagrams, database schemas, and answers to common examiner questions, review the included documents in `docs/`:
- **[System Architecture Guide](docs/architecture.md)**: Concurrency model, NDJSON protocol, SQL tables, and data flow.
- **[College Viva Defense Guide](docs/viva_guide.md)**: 7 key viva questions with detailed answers, worked anomaly examples, and algorithm breakdowns.
