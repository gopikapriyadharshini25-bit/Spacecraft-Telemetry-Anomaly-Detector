# Astraea-1 Ground Station — College Viva & Project Defense Guide

This guide is prepared for a third-semester B.Tech Computer Science student preparing to defend the **Spacecraft Telemetry and Anomaly Detector** project during practical exams, project evaluations, and viva voce.

---

## 1. Project Synopsis

### Problem Statement
Modern spacecraft transmit thousands of continuous telemetry parameters back to ground control. Due to communication noise, radiation upsets, or hardware degradation, sensors can experience sudden voltage spikes, thermal drift, sensor freezes, or telemetry dropouts. If ground operators rely solely on static safety limits, gradual component degradation (such as progressive battery heating or thruster line depressurization) goes unnoticed until critical limits are breached.

### Project Objective
To build an explainable, modular, and fully integrated Python system that:
1. Simulates realistic aerospace telemetry for the fictional **Astraea-1** spacecraft across 9 subsystems.
2. Injects artificial faults (Spike, Drift, Stuck, Missing) to simulate in-flight anomalies.
3. Transmits telemetry across an authentic local TCP network link using Newline-Delimited JSON (NDJSON).
4. Reconstructs, validates, and stores telemetry in an SQLite database.
5. Runs dual-layer anomaly detection: static threshold limits and rolling-average historical deviations.
6. Presents real-time health, anomaly logs, summary counters, and historical trends in a responsive Tkinter desktop dashboard.

### Scope & Limitations
- **Scope**: Local simulation and monitoring of 9 spacecraft subsystems, TCP socket transport, rule-based dual-layer detection, SQLite persistence, and GUI visualization.
- **Limitations**: Simulates on a single host (`127.0.0.1`), uses rule-based heuristics rather than AI/ML, and models a single spacecraft rather than a constellation.

---

## 2. Key Technical Concepts & Answers

### Q1: Why did you choose TCP over UDP for telemetry?
> **Answer**: Telemetry packets contain mission-critical diagnostics and sequential health data. TCP provides:
> 1. **Reliability**: Guarantees delivery via ACKs and retransmissions.
> 2. **Ordered Delivery**: Sequence numbers and timestamps must be analyzed chronologically for historical rolling averages.
> 3. **Connection State**: Ground control needs to know whether the link to Astraea-1 is currently connected or dropped.

### Q2: What is Newline-Delimited JSON (NDJSON) and why is it needed over TCP?
> **Answer**: TCP is a byte-stream protocol without built-in message boundaries. If two JSON packets are sent rapidly, TCP may deliver them in a single `recv()` call (packet concatenation), or break one JSON packet across two calls (fragmentation). By appending a newline (`\n`) to each JSON message, the receiver can accumulate chunks in a buffer and reliably split complete JSON objects using `buffer.split("\n", 1)`.

### Q3: Why use SQLite instead of MySQL or PostgreSQL?
> **Answer**: SQLite is serverless, zero-configuration, and fully self-contained in a single local file (`spacecraft_telemetry.db`). It requires no separate database daemon or network credentials. It is part of Python's standard library (`sqlite3`), making the project completely portable across any computer.

### Q4: Why did you use rule-based detection instead of Machine Learning?
> **Answer**:
> 1. **Explainability**: In aerospace operations, operators need to know exactly *why* a warning occurred (e.g., "Battery voltage 48.0 V exceeds critical upper limit 42.0 V"). ML models (like neural networks) act as black boxes and can hallucinate or produce false positives.
> 2. **Deterministic Safety**: Safety standards require explicit threshold rules.
> 3. **Educational Transparency**: Rule-based logic with mathematical rolling means is completely understandable and testable for a third-semester CS student.

### Q5: How does your Historical Detection work? Give a worked example.
> **Answer**:
> - We query SQLite for the last $N=10$ valid historical readings for that channel, **explicitly excluding the current frame**.
> - Suppose for `battery_voltage`, the previous 5 readings were: `[36.0, 36.1, 35.9, 36.0, 36.0]`.
> - Historical mean: $\mu_{\text{hist}} = \frac{36.0+36.1+35.9+36.0+36.0}{5} = 36.0\text{ V}$.
> - Now, a drifting reading arrives: $x = 39.8\text{ V}$.
> - Physical warning limit is $40.0\text{ V}$, so static threshold detection thinks it is still acceptable (`WARNING` or borderline).
> - However, historical deviation: $\Delta = |39.8 - 36.0| = 3.8\text{ V}$.
> - The configured tolerance for battery voltage is $3.5\text{ V}$.
> - Since $3.8 > 3.5$, the historical detector flags an anomaly before the critical limit is breached.

### Q6: How did you ensure the Tkinter GUI does not freeze during networking?
> **Answer**:
> - Tkinter runs in a single-threaded event loop (`root.mainloop()`). Any blocking call (like `socket.recv()` or `time.sleep()`) will freeze the entire GUI window.
> - We solved this using a **Producer-Consumer Multi-Threading Model**:
>   - Background threads run the TCP receiver (`GroundStationServer`) and sender (`SpacecraftSender`).
>   - The receiver passes evaluated frames to a thread-safe `queue.Queue`.
>   - The main GUI thread runs a non-blocking timer (`root.after(80, self._poll_gui_queue)`), which drains the queue and updates Tkinter widgets safely on the main thread.

### Q7: How do you handle missing sensor values?
> **Answer**:
> When a sensor is disconnected or drops out, the simulator sends `None` in Python, which serializes to `null` in JSON. The validator accepts `None`, the database stores it as SQL `NULL`, the threshold detector flags it as `WARNING` (`MISSING_DATA`), and the historical detector safely ignores `None` values so the rolling average is never corrupted by zeros.

---

## 3. Module & Function Walkthrough

### 1. `config.py`
- Holds `SensorChannel` frozen dataclasses for all 9 subsystems.
- Sets physical boundaries: `critical_min <= warning_min <= nominal_min < nominal_max <= warning_max <= critical_max`.
- Holds network parameters (`127.0.0.1:8765`) and severity enumerations (`NOMINAL`, `WARNING`, `CRITICAL`).

### 2. `telemetry.py`
- `TelemetryFrame`: Dataclass containing `spacecraft_id`, `sequence_number`, `timestamp`, `readings`.
- `validate_telemetry_dict(data)`: Validates schema, types, rejects `NaN` and `Infinity`.
- `parse_and_validate_raw_line(line)`: Parses JSON string from TCP stream, returns `(TelemetryFrame, error_msg)`.

### 3. `sensor_simulator.py`
- `SensorSimulator(seed)`: Generates nominal telemetry centered on `nominal_center` with Gaussian noise `gauss()`. Clamps values strictly inside nominal range. Seed support guarantees repeatable tests.

### 4. `fault_injector.py`
- `FaultInjector`:
  - `SPIKE`: Pushes value abruptly beyond `critical_max`.
  - `DRIFT`: Adds incremental step offset each frame.
  - `STUCK`: Freezes value at first observed reading.
  - `MISSING`: Sets reading to `None`.
  - `clear_fault()`: Restores nominal behavior.

### 5. `database.py`
- `DatabaseManager`:
  - `create_tables()`: Creates `telemetry_frames`, `channel_readings`, `anomalies`.
  - `insert_telemetry_frame(frame)`: Inserts frame, enforces unique sequence numbers.
  - `get_recent_valid_readings(channel, limit, exclude_frame_id)`: Fetches historical non-null values chronologically.
  - `get_summary_stats()`: Computes total frames, warning counts, critical counts.

### 6. `anomaly_detector.py`
- `evaluate_threshold(channel, val)`: Compares reading against critical/warning bounds.
- `evaluate_historical_deviation(channel, val, history)`: Computes rolling mean and checks deviation tolerance.
- `combine_severities(...)`: Implements priority: CRITICAL > WARNING > NOMINAL.

### 7. `ground_station.py` & `spacecraft_sender.py`
- `GroundStationServer`: Multi-threaded TCP socket listener with stream buffering and parsing.
- `SpacecraftSender`: Multi-threaded TCP client streaming frames at fixed intervals with stop events.

### 8. `dashboard.py`
- `GroundStationDashboard`: Tkinter interface with live telemetry Treeview, fault controls, anomaly log, and Matplotlib historical chart.

---

## 4. Test Strategy Summary

The project includes 44 automated `unittest` test cases in `tests/`:
1. `test_config.py`: Verifies threshold hierarchy across all 9 channels.
2. `test_telemetry.py`: Tests JSON encoding/decoding, NaN/Inf rejection, and null handling.
3. `test_sensor_simulator.py`: Verifies seed reproducibility and nominal clamping.
4. `test_fault_injector.py`: Tests Spike, Drift, Stuck, Missing, and clearing.
5. `test_database.py`: Tests table schema, duplicate prevention, and historical queries.
6. `test_detector.py`: Tests threshold triggers, precedence, and missing data warnings.
7. `test_historical_detector.py`: Tests rolling mean calculation and deviation thresholding.
8. `test_networking.py`: Tests real local TCP sockets, chunking, concatenated bursts, and error recovery.
9. `test_integration.py`: End-to-end multi-threaded test across all subsystems.

*Run all tests with:* `python -m unittest discover tests`
