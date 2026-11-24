"""
dashboard.py - Tkinter Desktop Ground Control Station Dashboard for Astraea-1

This module implements the primary user interface for mission operators:
1. Spacecraft Telemetry Status: link status, simulation state, system health pill.
2. Real-Time Sensor Telemetry Table: 9 channels with live values, units, status,
   and color-coded severity tags (green NOMINAL, yellow WARNING, red CRITICAL).
3. Simulation & Fault Controls: Start, Stop, Reset, and interactive fault injection
   (Spike, Drift, Stuck, Missing) on any sensor channel.
4. Anomaly Event Log: Real-time record of threshold and historical deviations.
5. Historical Telemetry Visualizer: Embedded Matplotlib time-series plot with
   nominal band shading and warning/critical threshold guidelines.
6. Thread-Safe GUI Architecture: Decoupled via Python queue and root.after() polling.
"""

from datetime import datetime
import queue
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Dict, Optional

# Matplotlib integration for embedded historical charts
try:
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    import matplotlib.dates as mdates
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

from config import (
    CHANNEL_CONFIGS,
    DEFAULT_SIMULATION_INTERVAL_SEC,
    SPACECRAFT_ID,
    FaultType,
    Severity,
)
from database import DatabaseManager
from fault_injector import FaultInjector
from anomaly_detector import AnomalyDetector, FrameEvaluation
from ground_station import GroundStationServer
from spacecraft_sender import SpacecraftSender


class GroundStationDashboard:
    """
    Tkinter desktop dashboard for Astraea-1 ground control operations.
    All widget updates are scheduled strictly on the main thread via a thread-safe Queue.
    """

    def __init__(
        self,
        root: tk.Tk,
        db: DatabaseManager,
        server: GroundStationServer,
        sender: SpacecraftSender,
        detector: AnomalyDetector,
        fault_injector: FaultInjector,
    ):
        self.root = root
        self.db = db
        self.server = server
        self.sender = sender
        self.detector = detector
        self.fault_injector = fault_injector

        self.gui_queue = queue.Queue()

        self.root.title(f"Astraea-1 Ground Station — Telemetry & Anomaly Detector")
        self.root.geometry("1180x820")
        self.root.minsize(1000, 700)

        # Apply modern UI styling
        self._setup_styles()

        # Build UI layout
        self._build_header_panel()
        self._build_main_layout()

        # Wire server and sender callbacks to forward events into the queue
        self._wire_event_pipeline()

        # Start non-blocking GUI event polling loop
        self.root.after(100, self._poll_gui_queue)

        # Handle graceful shutdown on window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Load initial database stats
        self._refresh_summary_stats()

    def _setup_styles(self) -> None:
        """Configure ttk styles and color tags."""
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # Define color palette
        self.COLOR_BG = "#0f172a"          # Slate 900
        self.COLOR_PANEL = "#1e293b"       # Slate 800
        self.COLOR_TEXT = "#f8fafc"        # Slate 50
        self.COLOR_MUTED = "#94a3b8"       # Slate 400
        self.COLOR_BORDER = "#334155"      # Slate 700

        self.COLOR_NOMINAL = "#10b981"     # Emerald Green
        self.COLOR_WARNING = "#f59e0b"     # Amber Orange
        self.COLOR_CRITICAL = "#ef4444"    # Crimson Red

        self.root.configure(bg=self.COLOR_BG)

        # Frame styles
        self.style.configure("Dark.TFrame", background=self.COLOR_BG)
        self.style.configure("Card.TFrame", background=self.COLOR_PANEL, relief="flat")
        self.style.configure("Card.TLabelframe", background=self.COLOR_PANEL, foreground=self.COLOR_TEXT)
        self.style.configure("Card.TLabelframe.Label", background=self.COLOR_PANEL, foreground=self.COLOR_TEXT, font=("Segoe UI", 10, "bold"))

        # Label styles
        self.style.configure("Dark.TLabel", background=self.COLOR_BG, foreground=self.COLOR_TEXT, font=("Segoe UI", 10))
        self.style.configure("Panel.TLabel", background=self.COLOR_PANEL, foreground=self.COLOR_TEXT, font=("Segoe UI", 10))
        self.style.configure("PanelMuted.TLabel", background=self.COLOR_PANEL, foreground=self.COLOR_MUTED, font=("Segoe UI", 9))
        self.style.configure("HeaderTitle.TLabel", background=self.COLOR_PANEL, foreground="#38bdf8", font=("Segoe UI", 16, "bold"))
        self.style.configure("StatNum.TLabel", background=self.COLOR_PANEL, foreground=self.COLOR_TEXT, font=("Segoe UI", 16, "bold"))

        # Button styles
        self.style.configure("Action.TButton", font=("Segoe UI", 9, "bold"), padding=5)

        # Treeview styles
        self.style.configure(
            "Treeview",
            background="#1e293b",
            foreground="#f8fafc",
            fieldbackground="#1e293b",
            rowheight=26,
            font=("Consolas", 9),
        )
        self.style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#334155", foreground="#f8fafc")
        self.style.map("Treeview", background=[("selected", "#0284c7")])

    def _build_header_panel(self) -> None:
        """Build top status banner showing spacecraft identity and mission clock."""
        header_frame = ttk.Frame(self.root, style="Card.TFrame", padding=12)
        header_frame.pack(fill="x", padx=12, pady=(12, 6))

        # Title and identity
        title_box = ttk.Frame(header_frame, style="Card.TFrame")
        title_box.pack(side="left", fill="y")

        lbl_title = ttk.Label(title_box, text=f"🚀 {SPACECRAFT_ID} GROUND CONTROL", style="HeaderTitle.TLabel")
        lbl_title.pack(anchor="w")

        lbl_sub = ttk.Label(title_box, text="Spacecraft Telemetry & Real-Time Anomaly Detector", style="PanelMuted.TLabel")
        lbl_sub.pack(anchor="w")

        # Status Indicators (Pills)
        status_box = ttk.Frame(header_frame, style="Card.TFrame")
        status_box.pack(side="right", fill="y")

        # Telemetry Link Status
        ttk.Label(status_box, text="TCP LINK:", style="PanelMuted.TLabel").grid(row=0, column=0, padx=6, sticky="e")
        self.lbl_link_status = ttk.Label(status_box, text="LISTENING", style="Panel.TLabel", font=("Segoe UI", 9, "bold"), foreground="#38bdf8")
        self.lbl_link_status.grid(row=0, column=1, padx=6, sticky="w")

        # Simulation Status
        ttk.Label(status_box, text="SIMULATOR:", style="PanelMuted.TLabel").grid(row=0, column=2, padx=6, sticky="e")
        self.lbl_sim_status = ttk.Label(status_box, text="STOPPED", style="Panel.TLabel", font=("Segoe UI", 9, "bold"), foreground=self.COLOR_MUTED)
        self.lbl_sim_status.grid(row=0, column=3, padx=6, sticky="w")

        # Overall Spacecraft Health
        ttk.Label(status_box, text="MISSION HEALTH:", style="PanelMuted.TLabel").grid(row=0, column=4, padx=6, sticky="e")
        self.lbl_overall_severity = ttk.Label(
            status_box,
            text=" NOMINAL ",
            style="Panel.TLabel",
            font=("Segoe UI", 10, "bold"),
            foreground="#0f172a",
            background=self.COLOR_NOMINAL,
            padding=3,
        )
        self.lbl_overall_severity.grid(row=0, column=5, padx=8, sticky="w")

    def _build_main_layout(self) -> None:
        """Construct the two-column middle section and bottom notebook."""
        # Main split container
        main_split = ttk.Frame(self.root, style="Dark.TFrame")
        main_split.pack(fill="both", expand=True, padx=12, pady=6)

        # Left Column: Sensor Telemetry Table
        left_col = ttk.Frame(main_split, style="Dark.TFrame")
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 6))

        # Right Column: Controls and Summary Statistics
        right_col = ttk.Frame(main_split, style="Dark.TFrame", width=360)
        right_col.pack(side="right", fill="y", padx=(6, 0))
        right_col.pack_propagate(False)

        self._build_sensor_table(left_col)
        self._build_controls_panel(right_col)
        self._build_stats_panel(right_col)

        # Bottom Notebook: Anomaly Log & Historical Charts
        self._build_bottom_notebook(self.root)

    def _build_sensor_table(self, parent: ttk.Frame) -> None:
        """Construct the live sensor telemetry Treeview table."""
        frame = ttk.LabelFrame(parent, text=" Live Spacecraft Telemetry (9 Subsystems) ", style="Card.TLabelframe", padding=8)
        frame.pack(fill="both", expand=True)

        cols = ("channel", "value", "unit", "status", "reason")
        self.tree_sensors = ttk.Treeview(frame, columns=cols, show="headings", height=9, selectmode="browse")

        self.tree_sensors.heading("channel", text="Subsystem Channel")
        self.tree_sensors.heading("value", text="Latest Reading")
        self.tree_sensors.heading("unit", text="Unit")
        self.tree_sensors.heading("status", text="Health Status")
        self.tree_sensors.heading("reason", text="Detection Explanation / Range Details")

        self.tree_sensors.column("channel", width=180, anchor="w")
        self.tree_sensors.column("value", width=110, anchor="e")
        self.tree_sensors.column("unit", width=60, anchor="center")
        self.tree_sensors.column("status", width=100, anchor="center")
        self.tree_sensors.column("reason", width=280, anchor="w")

        # Define color tags for row highlights
        self.tree_sensors.tag_configure("tag_nominal", foreground=self.COLOR_NOMINAL)
        self.tree_sensors.tag_configure("tag_warning", foreground=self.COLOR_WARNING)
        self.tree_sensors.tag_configure("tag_critical", foreground=self.COLOR_CRITICAL, font=("Consolas", 9, "bold"))

        # Populate rows with initial placeholder entries
        for ch_key, ch in CHANNEL_CONFIGS.items():
            self.tree_sensors.insert(
                "",
                "end",
                iid=ch_key,
                values=(ch.display_name, "--", ch.unit, "WAITING", f"Nominal: [{ch.nominal_min}, {ch.nominal_max}]"),
                tags=("tag_nominal",),
            )

        self.tree_sensors.pack(fill="both", expand=True)

    def _build_controls_panel(self, parent: ttk.Frame) -> None:
        """Construct simulation start/stop and fault injection controls."""
        # Simulation Controls
        sim_box = ttk.LabelFrame(parent, text=" Simulation Controls ", style="Card.TLabelframe", padding=10)
        sim_box.pack(fill="x", pady=(0, 8))

        btn_box = ttk.Frame(sim_box, style="Card.TFrame")
        btn_box.pack(fill="x", pady=2)

        self.btn_start = ttk.Button(btn_box, text="▶ Start Simulation", style="Action.TButton", command=self.start_simulation)
        self.btn_start.pack(side="left", expand=True, fill="x", padx=2)

        self.btn_stop = ttk.Button(btn_box, text="⏹ Stop Simulation", style="Action.TButton", command=self.stop_simulation, state="disabled")
        self.btn_stop.pack(side="left", expand=True, fill="x", padx=2)

        # Fault Injection Controls
        fault_box = ttk.LabelFrame(parent, text=" Artificial Fault Injection ", style="Card.TLabelframe", padding=10)
        fault_box.pack(fill="x", pady=(0, 8))

        # Target Channel Dropdown
        ttk.Label(fault_box, text="Target Channel:", style="PanelMuted.TLabel").pack(anchor="w")
        self.combo_fault_channel = ttk.Combobox(
            fault_box,
            values=[f"{ch.display_name} ({name})" for name, ch in CHANNEL_CONFIGS.items()],
            state="readonly",
        )
        self.combo_fault_channel.current(0)
        self.combo_fault_channel.pack(fill="x", pady=(2, 6))

        # Fault Type Dropdown
        ttk.Label(fault_box, text="Fault Type:", style="PanelMuted.TLabel").pack(anchor="w")
        self.combo_fault_type = ttk.Combobox(
            fault_box,
            values=[FaultType.SPIKE.value, FaultType.DRIFT.value, FaultType.STUCK.value, FaultType.MISSING.value],
            state="readonly",
        )
        self.combo_fault_type.current(0)
        self.combo_fault_type.pack(fill="x", pady=(2, 8))

        fault_btn_box = ttk.Frame(fault_box, style="Card.TFrame")
        fault_btn_box.pack(fill="x", pady=2)

        self.btn_inject = ttk.Button(fault_btn_box, text="⚡ Inject Fault", style="Action.TButton", command=self.inject_fault)
        self.btn_inject.pack(side="left", expand=True, fill="x", padx=2)

        self.btn_clear_fault = ttk.Button(fault_btn_box, text="🔄 Clear Faults", style="Action.TButton", command=self.clear_faults)
        self.btn_clear_fault.pack(side="left", expand=True, fill="x", padx=2)

        self.lbl_active_fault = ttk.Label(
            fault_box,
            text="Active Fault: None (Nominal)",
            style="Panel.TLabel",
            foreground=self.COLOR_NOMINAL,
            wraplength=320,
        )
        self.lbl_active_fault.pack(anchor="w", pady=(6, 0))

    def _build_stats_panel(self, parent: ttk.Frame) -> None:
        """Construct summary metrics panel."""
        stats_box = ttk.LabelFrame(parent, text=" Ground Station Telemetry Metrics ", style="Card.TLabelframe", padding=10)
        stats_box.pack(fill="both", expand=True)

        grid = ttk.Frame(stats_box, style="Card.TFrame")
        grid.pack(fill="both", expand=True)

        # Metric cards
        self.lbl_total_frames = self._create_stat_card(grid, 0, 0, "Total Frames", "0", "#38bdf8")
        self.lbl_stat_warnings = self._create_stat_card(grid, 0, 1, "Warnings", "0", self.COLOR_WARNING)
        self.lbl_stat_criticals = self._create_stat_card(grid, 1, 0, "Critical Events", "0", self.COLOR_CRITICAL)
        self.lbl_stat_historical = self._create_stat_card(grid, 1, 1, "Historical Divergences", "0", "#c084fc")

    def _create_stat_card(self, parent: ttk.Frame, r: int, c: int, title: str, init_val: str, color: str) -> ttk.Label:
        box = ttk.Frame(parent, style="Card.TFrame", padding=6)
        box.grid(row=r, column=c, sticky="nsew", padx=4, pady=4)
        parent.columnconfigure(c, weight=1)
        parent.rowconfigure(r, weight=1)

        ttk.Label(box, text=title, style="PanelMuted.TLabel", font=("Segoe UI", 8)).pack(anchor="center")
        val_lbl = ttk.Label(box, text=init_val, style="StatNum.TLabel", foreground=color)
        val_lbl.pack(anchor="center")
        return val_lbl

    def _build_bottom_notebook(self, parent: tk.Widget) -> None:
        """Build bottom notebook with Anomaly Log tab and Historical Visualizer tab."""
        notebook_frame = ttk.Frame(parent, style="Dark.TFrame")
        notebook_frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.notebook = ttk.Notebook(notebook_frame)
        self.notebook.pack(fill="both", expand=True)

        # Tab 1: Anomaly Log
        tab_log = ttk.Frame(self.notebook, style="Card.TFrame", padding=6)
        self.notebook.add(tab_log, text="  ⚠ Real-Time Anomaly Log  ")
        self._build_anomaly_log_tab(tab_log)

        # Tab 2: Historical Telemetry Visualizer
        tab_chart = ttk.Frame(self.notebook, style="Card.TFrame", padding=6)
        self.notebook.add(tab_chart, text="  📈 Historical Telemetry Visualizer  ")
        self._build_historical_chart_tab(tab_chart)

    def _build_anomaly_log_tab(self, parent: ttk.Frame) -> None:
        """Construct the anomaly events Treeview log."""
        cols = ("timestamp", "channel", "value", "severity", "type", "reason")
        self.tree_anomalies = ttk.Treeview(parent, columns=cols, show="headings", height=6)

        self.tree_anomalies.heading("timestamp", text="Timestamp (UTC)")
        self.tree_anomalies.heading("channel", text="Channel")
        self.tree_anomalies.heading("value", text="Value")
        self.tree_anomalies.heading("severity", text="Severity")
        self.tree_anomalies.heading("type", text="Detection Method")
        self.tree_anomalies.heading("reason", text="Root Cause Explanation")

        self.tree_anomalies.column("timestamp", width=170, anchor="center")
        self.tree_anomalies.column("channel", width=160, anchor="w")
        self.tree_anomalies.column("value", width=90, anchor="e")
        self.tree_anomalies.column("severity", width=90, anchor="center")
        self.tree_anomalies.column("type", width=120, anchor="center")
        self.tree_anomalies.column("reason", width=450, anchor="w")

        self.tree_anomalies.tag_configure("tag_warning", foreground=self.COLOR_WARNING)
        self.tree_anomalies.tag_configure("tag_critical", foreground=self.COLOR_CRITICAL, font=("Consolas", 9, "bold"))

        scroll = ttk.Scrollbar(parent, orient="vertical", command=self.tree_anomalies.yview)
        self.tree_anomalies.configure(yscrollcommand=scroll.set)

        self.tree_anomalies.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _build_historical_chart_tab(self, parent: ttk.Frame) -> None:
        """Construct embedded Matplotlib chart or table fallback."""
        ctrl_bar = ttk.Frame(parent, style="Card.TFrame")
        ctrl_bar.pack(fill="x", pady=(0, 6))

        ttk.Label(ctrl_bar, text="Select Telemetry Channel:", style="Panel.TLabel").pack(side="left", padx=4)

        self.combo_chart_channel = ttk.Combobox(
            ctrl_bar,
            values=[f"{ch.display_name} ({name})" for name, ch in CHANNEL_CONFIGS.items()],
            state="readonly",
            width=35,
        )
        self.combo_chart_channel.current(0)
        self.combo_chart_channel.pack(side="left", padx=6)

        btn_plot = ttk.Button(ctrl_bar, text="🔄 Render Historical Trend", style="Action.TButton", command=self.render_historical_chart)
        btn_plot.pack(side="left", padx=4)

        if HAS_MATPLOTLIB:
            self.chart_figure = Figure(figsize=(9, 2.8), dpi=100, facecolor="#1e293b")
            self.chart_ax = self.chart_figure.add_subplot(111)
            self.chart_figure.tight_layout()

            self.chart_canvas = FigureCanvasTkAgg(self.chart_figure, master=parent)
            self.chart_canvas.get_tk_widget().pack(fill="both", expand=True)
            self.render_historical_chart()
        else:
            lbl_fallback = ttk.Label(
                parent,
                text="Matplotlib is not installed. Historical data is saved in SQLite.",
                style="Panel.TLabel",
            )
            lbl_fallback.pack(pady=20)

    def _wire_event_pipeline(self) -> None:
        """Connect TCP server and sender callbacks to enqueue events for the GUI thread."""
        def handle_frame_received(frame):
            # 1. Insert into SQLite
            frame_id = self.db.insert_telemetry_frame(frame)
            # 2. Run anomaly detector (compares against SQLite history excluding current frame)
            eval_result = self.detector.process_frame(frame, frame_id=frame_id, save_anomalies=True)
            # 3. Fetch fresh summary statistics
            stats = self.db.get_summary_stats()
            # 4. Push to GUI thread queue
            self.gui_queue.put(("FRAME_EVALUATED", eval_result, stats))

        def handle_connection_change(connected: bool):
            self.gui_queue.put(("CONNECTION_CHANGED", connected))

        def handle_stream_error(err_msg: str):
            self.gui_queue.put(("STREAM_ERROR", err_msg))

        def handle_sender_status(status_msg: str):
            self.gui_queue.put(("SENDER_STATUS", status_msg))

        self.server.on_frame_received = handle_frame_received
        self.server.on_connection_change = handle_connection_change
        self.server.on_error = handle_stream_error
        self.sender.on_status_change = handle_sender_status

    def _poll_gui_queue(self) -> None:
        """
        Periodically drain the thread-safe queue and update Tkinter widgets on main thread.
        """
        try:
            while not self.gui_queue.empty():
                msg_type, *payload = self.gui_queue.get_nowait()

                if msg_type == "FRAME_EVALUATED":
                    eval_result: FrameEvaluation = payload[0]
                    stats: Dict[str, int] = payload[1]
                    self._update_telemetry_display(eval_result)
                    self._update_stats_display(stats)

                elif msg_type == "CONNECTION_CHANGED":
                    connected = payload[0]
                    if connected:
                        self.lbl_link_status.config(text="CONNECTED", foreground=self.COLOR_NOMINAL)
                    else:
                        self.lbl_link_status.config(text="LISTENING", foreground="#38bdf8")

                elif msg_type == "STREAM_ERROR":
                    err_msg = payload[0]
                    # Append error into anomaly log as critical warning
                    self.tree_anomalies.insert(
                        "",
                        0,
                        values=(datetime.utcnow().isoformat(), "TCP_LINK", "--", "WARNING", "NETWORK_ERROR", err_msg),
                        tags=("tag_warning",),
                    )

        except queue.Empty:
            pass
        finally:
            self.root.after(80, self._poll_gui_queue)

    def _update_telemetry_display(self, eval_result: FrameEvaluation) -> None:
        """Update sensor table rows and header status pill."""
        # 1. Update overall health badge
        overall_sev = eval_result.overall_severity
        if overall_sev == Severity.CRITICAL:
            self.lbl_overall_severity.config(text=" CRITICAL ", background=self.COLOR_CRITICAL, foreground="#ffffff")
        elif overall_sev == Severity.WARNING:
            self.lbl_overall_severity.config(text=" WARNING ", background=self.COLOR_WARNING, foreground="#0f172a")
        else:
            self.lbl_overall_severity.config(text=" NOMINAL ", background=self.COLOR_NOMINAL, foreground="#0f172a")

        # 2. Update sensor table rows
        for ch_key, ch_eval in eval_result.channel_results.items():
            ch = CHANNEL_CONFIGS[ch_key]
            val_str = f"{ch_eval.observed_value:.2f}" if ch_eval.observed_value is not None else "NULL (MISSING)"
            status_str = ch_eval.severity.value

            tag = "tag_nominal"
            if ch_eval.severity == Severity.WARNING:
                tag = "tag_warning"
            elif ch_eval.severity == Severity.CRITICAL:
                tag = "tag_critical"

            self.tree_sensors.item(
                ch_key,
                values=(ch.display_name, val_str, ch.unit, status_str, ch_eval.combined_reason),
                tags=(tag,),
            )

        # 3. Insert newly flagged anomalies into Anomaly Log
        for anom in eval_result.anomalies:
            ch = CHANNEL_CONFIGS[anom.channel_name]
            val_str = f"{anom.observed_value:.2f}" if anom.observed_value is not None else "NULL"
            tag = "tag_critical" if anom.severity == Severity.CRITICAL else "tag_warning"
            self.tree_anomalies.insert(
                "",
                0,
                values=(
                    eval_result.frame.timestamp,
                    ch.display_name,
                    val_str,
                    anom.severity.value,
                    anom.detection_type.value,
                    anom.combined_reason,
                ),
                tags=(tag,),
            )

    def _update_stats_display(self, stats: Dict[str, int]) -> None:
        """Refresh summary metric labels."""
        self.lbl_total_frames.config(text=str(stats.get("total_frames", 0)))
        self.lbl_stat_warnings.config(text=str(stats.get("warning_count", 0)))
        self.lbl_stat_criticals.config(text=str(stats.get("critical_count", 0)))
        self.lbl_stat_historical.config(text=str(stats.get("historical_anomaly_count", 0)))

    def _refresh_summary_stats(self) -> None:
        """Fetch and populate historical records and stats from SQLite on start."""
        stats = self.db.get_summary_stats()
        self._update_stats_display(stats)

        # Populate prior anomalies from previous sessions
        prior_anomalies = self.db.get_recent_anomalies(limit=25)
        for anom in reversed(prior_anomalies):
            ch_name = anom["channel_name"]
            display_name = CHANNEL_CONFIGS[ch_name].display_name if ch_name in CHANNEL_CONFIGS else ch_name
            val_str = f"{anom['observed_value']:.2f}" if anom["observed_value"] is not None else "NULL"
            tag = "tag_critical" if anom["severity"] == "CRITICAL" else "tag_warning"
            self.tree_anomalies.insert(
                "",
                0,
                values=(
                    anom["timestamp"],
                    display_name,
                    val_str,
                    anom["severity"],
                    anom["detection_type"],
                    anom["reason"],
                ),
                tags=(tag,),
            )

    def start_simulation(self) -> None:
        """Start the TCP server (if needed) and the spacecraft sender thread."""
        try:
            if not self.server.is_running:
                self.server.start()
            self.sender.start()
            self.lbl_sim_status.config(text="RUNNING", foreground=self.COLOR_NOMINAL)
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
        except Exception as err:
            messagebox.showerror("Simulation Error", f"Failed to start simulation: {err}")

    def stop_simulation(self) -> None:
        """Halt telemetry transmission."""
        self.sender.stop()
        self.lbl_sim_status.config(text="STOPPED", foreground=self.COLOR_MUTED)
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")

    def _get_selected_fault_channel(self) -> str:
        """Extract channel key from combobox string."""
        selected_text = self.combo_fault_channel.get()
        # Text is in format: 'Display Name (channel_key)'
        if "(" in selected_text and selected_text.endswith(")"):
            return selected_text.split("(")[-1][:-1]
        return list(CHANNEL_CONFIGS.keys())[0]

    def inject_fault(self) -> None:
        """Arm an artificial fault in the fault injector."""
        channel_key = self._get_selected_fault_channel()
        fault_type_str = self.combo_fault_type.get()
        fault_type = FaultType(fault_type_str)

        self.fault_injector.set_fault(channel_key, fault_type)
        summary = self.fault_injector.get_status_summary()
        self.lbl_active_fault.config(text=f"Active Fault: {summary}", foreground=self.COLOR_WARNING)

    def clear_faults(self) -> None:
        """Reset fault injector to nominal."""
        self.fault_injector.clear_fault()
        self.lbl_active_fault.config(text="Active Fault: None (Nominal)", foreground=self.COLOR_NOMINAL)

    def render_historical_chart(self) -> None:
        """Query SQLite and render a time-series plot with safety limits."""
        if not HAS_MATPLOTLIB:
            return

        selected_text = self.combo_chart_channel.get()
        if "(" in selected_text and selected_text.endswith(")"):
            channel_key = selected_text.split("(")[-1][:-1]
        else:
            channel_key = list(CHANNEL_CONFIGS.keys())[0]

        channel = CHANNEL_CONFIGS[channel_key]
        history = self.db.get_channel_history(channel_key, limit=60)

        self.chart_ax.clear()
        self.chart_ax.set_facecolor("#0f172a")

        # Set title and labels
        self.chart_ax.set_title(
            f"Historical Telemetry Trend — {channel.display_name} ({channel.unit})",
            color="#f8fafc",
            fontsize=10,
            pad=8,
        )
        self.chart_ax.set_ylabel(channel.unit, color="#94a3b8", fontsize=9)
        self.chart_ax.grid(True, linestyle="--", alpha=0.25, color="#64748b")
        self.chart_ax.tick_params(colors="#94a3b8", labelsize=8)

        # Plot safety threshold guidelines
        self.chart_ax.axhline(channel.nominal_max, color=self.COLOR_NOMINAL, linestyle="--", linewidth=1, alpha=0.6, label="Nominal Limit")
        self.chart_ax.axhline(channel.nominal_min, color=self.COLOR_NOMINAL, linestyle="--", linewidth=1, alpha=0.6)
        self.chart_ax.axhline(channel.warning_max, color=self.COLOR_WARNING, linestyle=":", linewidth=1, alpha=0.8, label="Warning Limit")
        self.chart_ax.axhline(channel.warning_min, color=self.COLOR_WARNING, linestyle=":", linewidth=1, alpha=0.8)
        self.chart_ax.axhline(channel.critical_max, color=self.COLOR_CRITICAL, linestyle="-.", linewidth=1, alpha=0.8, label="Critical Limit")
        self.chart_ax.axhline(channel.critical_min, color=self.COLOR_CRITICAL, linestyle="-.", linewidth=1, alpha=0.8)

        if history:
            values = [row["value"] for row in history]
            indices = list(range(1, len(values) + 1))
            self.chart_ax.plot(indices, values, marker="o", markersize=3, color="#38bdf8", linewidth=1.5, label="Sensor Reading")
            self.chart_ax.set_xlabel("Recent Telemetry Frames (Chronological)", color="#94a3b8", fontsize=9)
        else:
            self.chart_ax.text(
                0.5, 0.5, "No historical telemetry recorded yet.\nStart simulation to generate readings.",
                horizontalalignment="center", verticalalignment="center",
                transform=self.chart_ax.transAxes, color="#94a3b8", fontsize=9
            )

        self.chart_ax.legend(loc="upper right", facecolor="#1e293b", edgecolor="#334155", labelcolor="#f8fafc", fontsize=7)
        self.chart_figure.tight_layout()
        self.chart_canvas.draw()

    def on_close(self) -> None:
        """Safely terminate all background threads and release resources."""
        self.sender.stop()
        self.server.stop()
        self.db.close()
        self.root.destroy()
