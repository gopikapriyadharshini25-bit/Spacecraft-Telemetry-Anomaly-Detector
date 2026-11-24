# Astraea-1 Ground Station — System Architecture & Design Specification

This document provides a comprehensive technical breakdown of the **Spacecraft Telemetry and Anomaly Detector** system for **Astraea-1**. It is written to be accessible and transparent for computer science students, project reviewers, and software mentors.

---

## 1. End-to-End Data Flow

The application models a genuine aerospace telemetry downlink across 11 discrete stages:

```
[ Sensor Simulator ]  (Astraea-1: 9 telemetry channels generated nominally)
         │
         ▼
[ Fault Injector ]    (Optional: Spike, Drift, Stuck, Missing injected)
         │
         ▼
[ Telemetry Encoder ] (JSON serialization, timestamping, sequence numbering)
         │
         ▼
[ Spacecraft Sender ] (TCP Client transmits NDJSON over 127.0.0.1:8765)
         │
         ▼ ~~~~~~ Local TCP Socket Link ~~~~~~
         │
         ▼
[ Ground Station ]    (TCP Server buffers stream, reconstructs lines, validates JSON)
         │
         ▼
[ SQLite Database ]   (Inserts raw frame and channel values into relational tables)
         │
         ▼
[ Anomaly Detector ]  (Compares against static thresholds & rolling SQLite historical baseline)
         │
         ▼
[ Severity Classifier ] (Merges into NOMINAL, WARNING, or CRITICAL with explanations)
         │
         ▼
[ Thread-Safe Queue ] (Transfers evaluation event to GUI main thread)
         │
         ▼
[ Tkinter Dashboard ] (Updates sensor table, status badges, anomaly log, and Matplotlib trend)
```

---

## 2. Module Responsibilities

The codebase follows the **Single Responsibility Principle**. Each file encapsulates one clear functional domain:

| Module | Responsibility | Key Classes / Functions |
| :--- | :--- | :--- |
| `config.py` | Central configuration, 9 sensor channel definitions, threshold boundaries, network defaults, and severity enumerations. | `SensorChannel`, `Severity`, `FaultType`, `CHANNEL_CONFIGS` |
| `telemetry.py` | Data structure representation of downlink packets, JSON serialization, NDJSON encoding, and schema validation. | `TelemetryFrame`, `validate_telemetry_dict()`, `parse_and_validate_raw_line()` |
| `sensor_simulator.py` | Generates nominal synthetic telemetry for Astraea-1 with Gaussian noise and seed reproducibility. | `SensorSimulator` |
| `fault_injector.py` | Non-destructively alters sensor readings to introduce Spikes, Drifts, Stuck values, or Missing telemetry. | `FaultInjector` |
| `spacecraft_sender.py` | TCP client worker thread that samples telemetry, applies faults, and transmits NDJSON packets at a fixed interval. | `SpacecraftSender` |
| `ground_station.py` | TCP server worker thread that listens on a local socket, buffers stream chunks, reconstructs messages, and handles disconnections. | `GroundStationServer` |
| `database.py` | Thread-safe SQLite persistence layer for raw frames, per-channel sensor values, and detected anomaly records. | `DatabaseManager` |
| `anomaly_detector.py` | Rule-based threshold checking, SQLite rolling-mean historical deviation checking, and combined severity classification. | `AnomalyDetector`, `evaluate_threshold()`, `evaluate_historical_deviation()` |
| `dashboard.py` | Tkinter desktop GUI with custom ttk widgets, thread-safe queue polling, live sensor grid, anomaly log, and embedded Matplotlib trend plot. | `GroundStationDashboard` |
| `main.py` | Unified application launch script supporting desktop GUI mode and headless automated demonstration mode (`--demo`). | `main()`, `run_gui()`, `run_headless_demo()` |

---

## 3. Telemetry Stream Protocol (NDJSON over TCP)

### Stream Framing & Buffer Management
TCP is a byte-stream protocol, not a message-oriented protocol. A single call to `recv()` may contain:
- A partial JSON packet (if fragmented across TCP segments).
- Exactly one complete JSON packet.
- Multiple concatenated JSON packets (during network bursts).

To handle this cleanly, the system uses **Newline-Delimited JSON (NDJSON)**:
1. The sender terminates every JSON string with a newline byte (`\n` or `0x0A`).
2. The ground station accumulates incoming chunks into an internal string buffer.
3. When `\n` is detected, the buffer splits into the complete line and the remaining fragment:
   ```python
   while "\n" in buffer:
       line, buffer = buffer.split("\n", 1)
       process_line(line)
   ```
4. A safety limit (`MAX_BUFFER_BYTES = 65536`) discards corrupt or overflowing streams to prevent memory exhaustion.

### Telemetry Packet JSON Schema
```json
{
  "spacecraft_id": "Astraea-1",
  "sequence_number": 42,
  "timestamp": "2026-10-18T17:15:00.123456+00:00",
  "readings": {
    "battery_voltage": 36.42,
    "battery_temp": 22.10,
    "battery_charge": 84.50,
    "solar_panel_current": 10.15,
    "power_bus_consumption": 298.40,
    "comm_signal_strength": -64.80,
    "internal_temp": 21.05,
    "fuel_pressure": 299.70,
    "reaction_wheel_rpm": 2510.00
  }
}
```

---

## 4. SQLite Database Schema & Concurrency

The SQLite database (`spacecraft_telemetry.db`) uses three relational tables with Foreign Keys and indexes:

```sql
-- 1. Raw Telemetry Frames
CREATE TABLE telemetry_frames (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    spacecraft_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL UNIQUE,
    timestamp TEXT NOT NULL,
    readings_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 2. Indexed Per-Channel Readings (Chronological Time Series)
CREATE TABLE channel_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_id INTEGER NOT NULL REFERENCES telemetry_frames(id) ON DELETE CASCADE,
    channel_name TEXT NOT NULL,
    value REAL,
    timestamp TEXT NOT NULL
);
CREATE INDEX idx_channel_readings_query ON channel_readings (channel_name, id DESC);

-- 3. Anomaly Audit Log
CREATE TABLE anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_id INTEGER NOT NULL REFERENCES telemetry_frames(id) ON DELETE CASCADE,
    channel_name TEXT NOT NULL,
    observed_value REAL,
    severity TEXT NOT NULL,
    detection_type TEXT NOT NULL,
    reason TEXT NOT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX idx_anomalies_timestamp ON anomalies (id DESC);
```

### Thread Safety & Concurrency
- `sqlite3` connections are wrapped inside `DatabaseManager` using a `threading.Lock()` mutex.
- SQLite runs with `PRAGMA journal_mode=WAL;` (Write-Ahead Logging), allowing concurrent reads and writes without file locks.
- `check_same_thread=False` allows the TCP receiver thread and the GUI main thread to query the same manager safely under lock.

---

## 5. Anomaly Detection Algorithms

### 5.1. Threshold-Based Detection
Compares the current reading $x$ against physical safety limits:
- If $x$ is missing (`None` / `null`): Status $\rightarrow$ `WARNING` (`MISSING_DATA`).
- If $x < \text{critical\_min}$ or $x > \text{critical\_max}$: Status $\rightarrow$ `CRITICAL`.
- If $x < \text{warning\_min}$ or $x > \text{warning\_max}$: Status $\rightarrow$ `WARNING`.
- Otherwise: Status $\rightarrow$ `NOMINAL`.

*Critical limits always supersede warning limits.*

### 5.2. Historical Rolling-Average Deviation Detection
Physical thresholds cannot catch subtle sensor drift that remains within wide nominal boundaries. The historical detector retrieves the last $N=10$ valid historical readings $h_1, h_2, \dots, h_k$ from SQLite (excluding the current frame):

1. **Sample Sufficiency Check**: Requires at least $k \ge 3$ prior samples to prevent false alarms during startup.
2. **Rolling Mean**:
   $$\mu_{\text{hist}} = \frac{1}{k} \sum_{i=1}^{k} h_i$$
3. **Absolute Deviation**:
   $$\Delta = |x - \mu_{\text{hist}}|$$
4. **Trigger Condition**:
   $$\Delta > \tau_{\text{hist}}$$
   If exceeded, flags `WARNING` with reason detailing current reading, historical average, and threshold tolerance $\tau_{\text{hist}}$.

### 5.3. Final Severity Fusion Matrix
Threshold and historical results are merged deterministically:

| Threshold Result | Historical Result | Combined Severity | Detection Type |
| :---: | :---: | :---: | :---: |
| `CRITICAL` | Any | `CRITICAL` | `COMBINED` if both abnormal, else `THRESHOLD` |
| `WARNING` | `WARNING` | `WARNING` | `COMBINED` |
| `WARNING` | `NOMINAL` | `WARNING` | `THRESHOLD` |
| `NOMINAL` | `WARNING` | `WARNING` | `HISTORICAL` |
| `NOMINAL` | `NOMINAL` | `NOMINAL` | `NONE` |
| Missing (`None`) | Skipped | `WARNING` | `MISSING_DATA` |

---

## 6. Threading Model and GUI Safety

Tkinter is **not thread-safe**. Modifying widgets from background threads causes race conditions and UI crashes.

### Concurrency Architecture
```
[ SpacecraftSender Thread ] ──────> [ GroundStationServer Thread ]
                                                │
                                                ▼
                                   [ SQLite DB & AnomalyDetector ]
                                                │
                                                ▼
                                      [ queue.Queue ] (Thread-Safe FIFO)
                                                │
                                                ▼
[ Main Thread (Tkinter root.mainloop) ] <───────┘
  └─ root.after(80ms, _poll_gui_queue)
```

1. **Background Sender Thread**: Sleeps on non-blocking tick interval, constructs packets, transmits bytes.
2. **Background Receiver Thread**: Accepts TCP connections, reads socket buffer, reconstructs NDJSON frames.
3. **Processing Pipeline**: Stores frame in SQLite, runs AnomalyDetector, queries fresh aggregate stats.
4. **Message Queue**: Thread-safe `queue.Queue` receives `('FRAME_EVALUATED', eval_result, stats)`.
5. **Main Thread GUI Polling**: `root.after(80, self._poll_gui_queue)` dequeues events and executes UI updates strictly on the main thread.

---

## 7. Lifecycle and Shutdown

1. **Startup**:
   - `DatabaseManager` connects to SQLite and executes `CREATE TABLE IF NOT EXISTS`.
   - `GroundStationServer` binds local TCP socket `127.0.0.1:8765` and begins listening in background thread.
   - GUI displays loaded historical counts and previous session anomaly logs.

2. **Simulation Start**:
   - Operator clicks "Start Simulation".
   - `SpacecraftSender` worker thread spawns, connects to server socket, and begins streaming frames.

3. **Simulation Stop**:
   - Operator clicks "Stop Simulation".
   - Sender sets internal `threading.Event`, safely shuts down socket, and worker thread terminates cleanly within 200ms.

4. **Application Exit**:
   - Window close button triggers `WM_DELETE_WINDOW` handler:
     1. `sender.stop()` terminates spacecraft transmitter.
     2. `server.stop()` closes server socket and drops client connections.
     3. `db.close()` commits transactions and closes SQLite handle.
     4. `root.destroy()` closes Tkinter window cleanly without orphaned background threads.
