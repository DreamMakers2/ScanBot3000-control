// ---- Global UI state ----

const GLOBAL = {
  systemSettings: null,
  openSockets: 0,
  statusDot: document.getElementById("connection-status"),
};

function setConnectionStatus(isOnline) {
  const el = GLOBAL.statusDot;
  if (!el) return;
  el.classList.toggle("offline", !isOnline);
  el.textContent = isOnline ? "Online" : "Offline";
}

async function sendCommandHttp(command) {
  const normalized = String(command || "").trim();
  if (!normalized) return;
  try {
    const res = await fetch("/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: normalized }),
    });
    if (!res.ok) {
      // Swallow, panels show their own error lines via WS if any
      await res.json().catch(() => ({}));
    }
  } catch {}
}

// ---- Axis Panel implementation ----

const CHART_METRICS = [
  { key: "dps", label: "Speed (°/s)", color: "#a855f7" },
  { key: "ang", label: "Angle (°)", color: "#38bdf8" },
  { key: "temp", label: "Temp (°C)", color: "#f97316" },
  { key: "dist", label: "Position", color: "#22c55e" },
];

class AxisPanel {
  constructor(axisId, mount, options = {}) {
    this.axis = axisId; // Display label (R, Z, X, P)
    // Axis token to use in commands (e.g. 'x','z','p','r')
    this.axisKey = (options.commandAxis || axisId).toLowerCase();
    // Primary WS axis ids (backend-recognized: 'r','z','x1','x2') used for metrics + console
    this.primaryWsAxes = Array.isArray(options.primaryWsAxes) && options.primaryWsAxes.length
      ? options.primaryWsAxes
      : [this.axisKey];
    // Additional WS axis ids whose console should mirror into this panel (console only)
    this.mirrorConsoleAxes = Array.isArray(options.mirrorConsoleAxes) ? options.mirrorConsoleAxes : [];
    this.mount = mount;
    // Per-axis WebSocket connections
    this.wsMap = new Map(); // axisId -> WebSocket
    this.wsReconnectDelay = new Map(); // axisId -> ms
    this.maxConsoleLines = 500;
    this.metricsHistorySec = 300;
    this.chartWindowSec = 20;
    this.consoleLines = [];
    this.consoleDirty = false;
    this.chartDirty = false;
    this.series = { time: [], temp: [], ang: [], dps: [], dist: [], lim: [] };
    this.chart = null;
    this.canvasUnder = null;
    this.canvasOver = null;
    this.latestSampleTime = null;
    // Console pause + debug state
    this.consolePaused = false;
    this.debugEnabled = true; // client-side only
    // Define which console prefixes this panel should display
    this.allowedTokens = this._computeAllowedTokens();
    this._build();
    this._connectAll();
  }

  _build() {
    const root = document.createElement("div");
    root.className = "axis-panel";

    // Header
    const header = document.createElement("div");
    header.className = "axis-header";
    const title = document.createElement("h2");
    title.className = "axis-title";
    title.textContent = `Axis ${this.axis}`;
    this.statusDot = document.createElement("span");
    this.statusDot.className = "status-dot offline";
    this.statusDot.textContent = "Offline";
    this.stateBadge = document.createElement("span");
    this.stateBadge.className = "runstate-badge live";
    this.stateBadge.textContent = "Live";
    const headerTools = document.createElement("div");
    headerTools.className = "axis-tools";
    // Show run-state badge to the left of the Online/Offline badge
    headerTools.append(this.stateBadge, this.statusDot);
    header.append(title, headerTools);

    // Console section
    const consoleSection = document.createElement("section");
    const consoleHeader = document.createElement("div");
    consoleHeader.className = "section-header";
    const consoleTitle = document.createElement("h3");
    consoleTitle.textContent = "Console";
    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.textContent = "Clear";
    clearBtn.addEventListener("click", () => this._clearConsole());
    const pauseBtn = document.createElement("button");
    pauseBtn.type = "button";
    pauseBtn.textContent = "⏸ Pause";
    pauseBtn.addEventListener("click", () => this._togglePause(pauseBtn));
    consoleHeader.append(consoleTitle, pauseBtn, clearBtn);
    this.consoleOutput = document.createElement("div");
    this.consoleOutput.className = "console-output";

    // Quick actions
    const quick = document.createElement("div");
    quick.className = "quick-commands";
    this._buildQuickButtons(quick);

    // Command input
    const cmdForm = document.createElement("form");
    cmdForm.autocomplete = "off";
    cmdForm.id = `cmd-form-${this.axisKey}`;
    cmdForm.className = "command-form";
    const cmdInput = document.createElement("input");
    cmdInput.type = "text";
    cmdInput.placeholder = `Enter ${this.axis} command…`;
    cmdInput.required = true;
    cmdInput.className = "command-input";
    const sendBtn = document.createElement("button");
    sendBtn.type = "submit";
    sendBtn.textContent = "Send";
    cmdForm.append(cmdInput, sendBtn);
    this.commandInput = cmdInput;
    cmdForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const raw = String(this.commandInput.value || "").trim();
      if (!raw) return;
      const formatted = this._formatAxisCommand(raw);
      this._send(formatted);
      this._appendConsoleLine(`> ${formatted}`);
      this.commandInput.value = "";
    });

    consoleSection.append(consoleHeader, this.consoleOutput, quick, cmdForm);

    // Status grid
    const statusGrid = document.createElement("section");
    statusGrid.className = "status-grid";
    this.elPos = this._statusCard(statusGrid, "Position", "--");
    this.elAng = this._statusCard(statusGrid, "Angle", "-- °");
    this.elLimit = this._statusCard(statusGrid, "Limitswitch", "Unknown");
    this.elTemp = this._statusCard(statusGrid, "Temperature", "-- °C");

    // Chart section
    const chartSection = document.createElement("section");
    const chartHeader = document.createElement("div");
    chartHeader.className = "section-header";
    const chartTitle = document.createElement("h3");
    chartTitle.textContent = "Status Chart";
    const chartTools = document.createElement("div");
    chartTools.className = "chart-tools";
    this.chartLegend = document.createElement("div");
    this.chartLegend.className = "chart-legend";
    chartTools.append(this.chartLegend);
    chartHeader.append(chartTitle, chartTools);
    this.chartContainer = document.createElement("div");
    this.chartContainer.className = "chart-container";
    chartSection.append(chartHeader, this.chartContainer);

    // Always-visible Chart Window control below the chart
    const chartControls = document.createElement("div");
    chartControls.className = "chart-controls";
    const rangeLabel = document.createElement("label");
    rangeLabel.textContent = "Chart Window (s)";
    const rangeInput = document.createElement("input");
    rangeInput.type = "number";
    rangeInput.min = "5";
    rangeInput.max = "600";
    rangeInput.step = "5";
    rangeInput.value = String(this.chartWindowSec);
    rangeInput.addEventListener("change", () => this._applyRange(rangeInput));
    rangeInput.addEventListener("keyup", (ev) => ev.key === "Enter" && this._applyRange(rangeInput));
    chartControls.append(rangeLabel, rangeInput);
    chartSection.append(chartControls);

    root.append(header, consoleSection, statusGrid, chartSection);
    this.mount.appendChild(root);

    // Legend
    this._renderLegend();
    window.addEventListener("resize", () => {
      if (this.chart) {
        this.chart.setSize({ width: this.chartContainer.clientWidth, height: 360 });
        this._applyFixedWindow();
      }
    });
  }

  _computeAllowedTokens() {
    const k = this.axisKey;
    if (k === "x") return new Set(["x", "x1", "x2"]);
    if (k === "p") return new Set(["p"]);
    if (k === "z") return new Set(["z"]);
    if (k === "r") return new Set(["r"]);
    return new Set([k]);
  }

  _parseAxisToken(line) {
    if (!line || typeof line !== "string") return null;
    let i = 0;
    while (i < line.length && (line[i] === " " || line[i] === "\t")) i += 1;
    let token = "";
    while (i < line.length) {
      const ch = line[i];
      if (ch === ":" || ch === " " || ch === "\t") break;
      token += ch;
      i += 1;
    }
    token = token.trim().replace(/:$/, "").toLowerCase();
    return token || null;
  }

  _shouldDisplayLine(line) {
    const tok = this._parseAxisToken(line);
    if (!tok) return false; // hide unlabeled lines per requirements
    return this.allowedTokens.has(tok);
  }

  _statusCard(container, label, initial) {
    const card = document.createElement("div");
    card.className = "status-card";
    const lb = document.createElement("span");
    lb.className = "label";
    lb.textContent = label;
    const val = document.createElement("span");
    val.className = "value";
    val.textContent = initial;
    card.append(lb, val);
    container.appendChild(card);
    return val;
  }

  _buildQuickButtons(container) {
    const addButton = (label, cmd, className) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      if (className) b.className = className;
      b.addEventListener("click", () => {
        const formatted = this._formatAxisCommand(cmd);
        this._send(formatted);
        this._appendConsoleLine(`> ${formatted}`);
      });
      container.appendChild(b);
    };

    // Stop is always first
    addButton(`STOP ${this.axis}`, "stop", "danger");

    const common = [
      [`move ${this.axis} 100 100 100`, "move 100 100 100"],
      [`move ${this.axis} -100 100 100`, "move -100 100 100"],
      ["tmcsettings", "tmcsettings"],
      ["tmcstatus", "tmcstatus"],
      ["hi", "hi"],
    ];

    // Standstill mode buttons (replacement for deprecated disablewhenstopped)
    const standstill = [
      ["standstill: normal", "standstillmode normal"],
      ["standstill: freewheel", "standstillmode freewheeling"],
      ["standstill: braking", "standstillmode braking"],
      ["standstill: strong", "standstillmode strong_braking"],
    ];

    const buttons = [...common, ...standstill];

    for (const [label, cmd] of buttons) addButton(label, cmd);
  }

  _applyRange(input) {
    const nextValue = Number(input.value);
    if (!Number.isFinite(nextValue) || nextValue <= 0) return;
    this.chartWindowSec = nextValue;
    this._scheduleChart();
    this._requestReanchor();
  }

  _formatAxisCommand(raw) {
    // Ensure axis-first syntax: <command> <axis> [args...]
    const txt = String(raw || "").trim();
    if (!txt) return txt;
    const t = txt.split(/\s+/);
    if (t.length === 1) {
      // commands like "stop" or "hi" -> add axis param
      return `${t[0]} ${this._axisTokenForCommand()}`;
    }
    const second = (t[1] || "").toLowerCase();
    if (["r", "z", "x1", "x2", "x", "p"].includes(second)) {
      // user already included axis; do not modify
      return txt;
    }
    // inject axis after command
    return `${t[0]} ${this._axisTokenForCommand()} ${t.slice(1).join(" ")}`.trim();
  }

  _axisTokenForCommand() {
    // Send commands using the panel's helper axis token (x, z, p, r)
    return this.axisKey;
  }

  _send(command) {
    // Try any primary WS connection first
    for (const ax of this.primaryWsAxes) {
      const ws = this.wsMap.get(ax);
      if (ws && ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(String(command));
          return;
        } catch {}
      }
    }
    // Fallback HTTP
    void sendCommandHttp(command);
  }

  _appendConsoleLine(line) {
    if (this.consolePaused) return; // drop lines while paused
    this.consoleLines.push(line);
    if (this.consoleLines.length > this.maxConsoleLines) {
      this.consoleLines.splice(0, this.consoleLines.length - this.maxConsoleLines);
    }
    if (!this.consoleDirty) {
      this.consoleDirty = true;
      window.requestAnimationFrame(() => {
        const el = this.consoleOutput;
        const stick = el.scrollTop >= el.scrollHeight - el.clientHeight - 10;
        el.textContent = this.consoleLines.join("\n");
        if (stick) el.scrollTop = el.scrollHeight;
        this.consoleDirty = false;
      });
    }
  }

  _clearConsole() {
    this.consoleLines = [];
    this.consoleOutput.textContent = "";
  }

  _ensureChart() {
    if (this.chart) return;
    const s = this._getWindowedSeries();
    const data = [s.time, ...CHART_METRICS.map(({ key }) => s[key])];

    const opts = {
      width: this.chartContainer.clientWidth || 400,
      height: 360,
      scales: {
        x: { time: true },
      },
      axes: [
        { stroke: "#94a3b8", grid: { stroke: "rgba(148,163,184,0.2)" } },
        { stroke: "#94a3b8", grid: { stroke: "rgba(148,163,184,0.2)" } },
      ],
      series: [{}, ...CHART_METRICS.map(({ label, color }) => ({ label, stroke: color }))],
    };
    this.chart = new uPlot(opts, data, this.chartContainer);
    this._applyFixedWindow();
    this._renderLegend();
  }

  _getWindowedSeries() {
    const out = { time: [] };
    const T = this.series.time;
    if (T.length === 0) return { time: [], dps: [], ang: [], temp: [], dist: [] };
    const windowSec = Number(this.chartWindowSec);
    let i = 0;
    if (Number.isFinite(windowSec) && windowSec > 0) {
      const cutoff = T[T.length - 1] - windowSec;
      while (i < T.length && T[i] < cutoff) i += 1;
    }
    out.time = T.slice(i);
    for (const { key } of CHART_METRICS) {
      out[key] = (this.series[key] || []).slice(i);
    }
    return out;
  }

  _getLatestTime() {
    if (Number.isFinite(this.latestSampleTime)) return this.latestSampleTime;
    const T = this.series.time;
    if (T && T.length) return T[T.length - 1];
    return Date.now() / 1000;
  }

  _buildChartData() {
    const s = this._getWindowedSeries();
    const data = [s.time, ...CHART_METRICS.map(({ key }) => s[key])];
    if (s.time.length === 0) {
      const now = Date.now() / 1000;
      return [[now], ...CHART_METRICS.map(() => [null])];
    }
    return data;
  }

  _renderLegend() {
    this.chartLegend.innerHTML = "";
    CHART_METRICS.forEach(({ label, color }) => {
      const span = document.createElement("span");
      const m = document.createElement("span");
      m.className = "marker"; m.style.background = color;
      const t = document.createElement("span");
      t.textContent = label;
      span.append(m, t);
      this.chartLegend.appendChild(span);
    });
  }

  _scheduleChart() {
    this.chartDirty = true;
    window.requestAnimationFrame(() => {
      if (!this.chartDirty) return;
      this._ensureChart();
      // Build next window + data once per frame and apply
      const s = this._getWindowedSeries();
      const nextData = [s.time, ...CHART_METRICS.map(({ key }) => s[key])];
      this.chart.setData(nextData);
      this._applyFixedWindow();
      this.chartDirty = false;
    });
  }

  _applyFixedWindow() {
    if (!this.chart) return;
    const latest = this._getLatestTime();
    const maxValue = Number.isFinite(latest) ? latest : Date.now() / 1000;
    const minValue = maxValue - Number(this.chartWindowSec || 0);
    this.chart.setScale("x", { min: minValue, max: maxValue });
  }

  _pushMetric(sample) {
    if (!sample) return;
    const ts = typeof sample.time === "number" ? sample.time : Date.now() / 1000;
    this.latestSampleTime = ts;
    this.series.time.push(ts);
    this.series.temp.push(toNum(sample.temp));
    this.series.ang.push(toNum(sample.ang));
    this.series.dps.push(toNum(sample.dps));
    this.series.dist.push(toNum(sample.dist));
    this.series.lim.push(toNum(sample.lim));
    // trim to history
    const maxS = Math.max(Math.floor(this.metricsHistorySec * 10), 60);
    const len = this.series.time.length;
    if (len > maxS) {
      const excess = len - maxS;
      for (const arr of Object.values(this.series)) arr.splice(0, excess);
    }
    // update status cards
    if (isFiniteNum(sample.temp)) this.elTemp.textContent = `${Number(sample.temp).toFixed(1)} °C`;
    if (isFiniteNum(sample.ang)) this.elAng.textContent = `${Number(sample.ang).toFixed(2)} °`;
    if (isFiniteNum(sample.dist)) this.elPos.textContent = Number(sample.dist).toFixed(2);
    if (isFiniteNum(sample.lim)) {
      const isTriggered = Number(sample.lim) >= 1;
      this.elLimit.textContent = isTriggered ? "Limitswitch: triggered" : "Limitswitch open";
    }
    this._scheduleChart();
  }

  _resetMetrics(history) {
    this.series = { time: [], temp: [], ang: [], dps: [], dist: [], lim: [] };
    this.latestSampleTime = null;
    if (Array.isArray(history)) history.forEach((s) => this._pushMetric(s));
    this._applyFixedWindow();
  }

  _handleMessage(msg) {
    switch (msg.type) {
      case "init":
        this.statusDot.classList.toggle("offline", !msg.uartReady);
        this.statusDot.textContent = msg.uartReady ? "Online" : "Offline";
        this.maxConsoleLines = (msg.settings?.console_history) ?? this.maxConsoleLines;
        this.metricsHistorySec = (msg.settings?.metrics_history) ?? this.metricsHistorySec;
        this._resetConsole(msg.console);
        this._resetMetrics(msg.metrics);
        break;
      case "console":
        this._appendConsoleLine(msg.line ?? "");
        if (msg.metrics) this._pushMetric(msg.metrics);
        break;
      case "error":
        this._appendConsoleLine(`[ERROR] ${msg.message}`);
        break;
      default:
        break;
    }
  }

  _resetConsole(lines) {
    const src = Array.isArray(lines) ? lines : [];
    this.consoleLines = src.filter((ln) => this._shouldDisplayLine(ln));
    this.consoleOutput.textContent = this.consoleLines.join("\n");
  }

  _connectAll() {
    const axes = [...this.primaryWsAxes, ...this.mirrorConsoleAxes];
    axes.forEach((ax) => this._connectAxisWs(ax, this.primaryWsAxes.includes(ax)));
  }

  _connectAxisWs(ax, isPrimary) {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${protocol}://${window.location.host}/ws/axis/${ax}`;
    const ws = new WebSocket(url);
    this.wsMap.set(ax, ws);
    const currentDelay = this.wsReconnectDelay.get(ax) || 1000;

    ws.addEventListener("open", () => {
      GLOBAL.openSockets += 1;
      if (isPrimary) {
        this.statusDot.classList.remove("offline");
        this.statusDot.textContent = "Online";
      }
      setConnectionStatus(true);
      this.wsReconnectDelay.set(ax, 1000);
    });
    ws.addEventListener("message", (e) => {
      try {
        const payload = JSON.parse(e.data);
        this._handleMessageFrom(payload, ax, isPrimary);
      } catch {}
    });
    ws.addEventListener("close", () => {
      GLOBAL.openSockets = Math.max(GLOBAL.openSockets - 1, 0);
      if (isPrimary) {
        const anyPrimaryOpen = this.primaryWsAxes.some((p) => {
          const w = this.wsMap.get(p);
          return w && w.readyState === WebSocket.OPEN;
        });
        if (!anyPrimaryOpen) {
          this.statusDot.classList.add("offline");
          this.statusDot.textContent = "Offline";
        }
      }
      setConnectionStatus(GLOBAL.openSockets > 0);
      this._scheduleReconnectAxis(ax, isPrimary);
    });
    ws.addEventListener("error", () => ws.close());
  }

  _scheduleReconnectAxis(ax, isPrimary) {
    const prev = this.wsReconnectDelay.get(ax) || 1000;
    const delay = Math.min(prev, 10000);
    setTimeout(() => {
      const next = Math.min((this.wsReconnectDelay.get(ax) || prev) * 1.5, 10000);
      this.wsReconnectDelay.set(ax, next);
      this._connectAxisWs(ax, isPrimary);
    }, delay);
  }

  _handleMessageFrom(payload, sourceAxis, isPrimary) {
    if (!payload || typeof payload !== "object") return;
    switch (payload.type) {
      case "init": {
        // Primary axis seeds metrics + console; mirror axes append filtered console snapshot
        if (isPrimary) {
          this._resetConsole(payload.console || []);
          if (Array.isArray(payload.metrics)) {
            // seed metrics series
            for (const m of payload.metrics) this._pushMetric(m);
            this._scheduleChart();
          }
          if (payload.uartReady) {
            this.statusDot.classList.remove("offline");
            this.statusDot.textContent = "Online";
          }
        } else {
          const lines = Array.isArray(payload.console) ? payload.console : [];
          for (const line of lines) {
            if (this._shouldDisplayLine(line)) this._appendConsoleLine(String(line));
          }
        }
        break;
      }
      case "console": {
        if (typeof payload.line === "string" && this._shouldDisplayLine(payload.line)) this._appendConsoleLine(payload.line);
        if (isPrimary && payload.metrics) this._pushMetric(payload.metrics);
        this._scheduleChart();
        this._scheduleChart();
        this._scheduleChart();
        break;
      }
      case "error":
        this._appendConsoleLine(`! Error: ${payload.message || "unknown"}`);
        break;
      default:
        break;
    }
  }

  _togglePause(buttonEl) {
    this.consolePaused = !this.consolePaused;
    if (this.consolePaused) {
      this.stateBadge.textContent = "Paused";
      this.stateBadge.classList.remove("live");
      this.stateBadge.classList.add("paused");
      if (buttonEl) buttonEl.textContent = "▶ Resume";
    } else {
      this.stateBadge.textContent = "Live";
      this.stateBadge.classList.remove("paused");
      this.stateBadge.classList.add("live");
      if (buttonEl) buttonEl.textContent = "⏸ Pause";
    }
  }
}

function isFiniteNum(v) {
  const n = Number(v);
  return Number.isFinite(n);
}
function toNum(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }

// ---- System Settings (global) ----

const elements = {
  settingsForm: document.getElementById("settings-form"),
  settingsMessage: document.getElementById("settings-message"),
  toggleSystemSettings: document.getElementById("toggle-system-settings"),
  systemSettingsBody: document.getElementById("system-settings-body"),
  globalStop: document.getElementById("global-stop"),
};

function populateSettingsForm(settings) {
  if (!settings || !elements.settingsForm) return;
  GLOBAL.systemSettings = settings;
  const form = elements.settingsForm;
  form.serial_device.value = settings.serial_device ?? "";
  form.baud_rate.value = settings.baud_rate ?? "";
  form.data_bits.value = settings.data_bits ?? "8";
  form.parity.value = settings.parity ?? "N";
  form.stop_bits.value = settings.stop_bits ?? "1";
  form.newline.value = settings.newline ?? "\n";
  form.console_history.value = settings.console_history ?? 500;
  form.metrics_history.value = settings.metrics_history ?? 300;
}

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    if (res.ok) populateSettingsForm(await res.json());
  } catch {}
}

function getSettingsPayload() {
  const form = elements.settingsForm;
  const data = new FormData(form);
  const payload = {};
  for (const [k, v] of data.entries()) {
    if (v === "" || v == null) continue;
    if (["baud_rate","data_bits","stop_bits","console_history","metrics_history"].includes(k)) payload[k] = Number(v);
    else payload[k] = v;
  }
  return payload;
}

async function submitSettings(e) {
  e.preventDefault();
  try {
    const res = await fetch("/api/settings", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(getSettingsPayload()) });
    if (!res.ok) throw new Error((await res.json().catch(()=>({detail:res.statusText}))).detail || "Failed to save");
    populateSettingsForm(await res.json());
    elements.settingsMessage.textContent = "Settings saved";
    setTimeout(()=> elements.settingsMessage.textContent = "", 2500);
  } catch (err) {
    elements.settingsMessage.textContent = `Error: ${err.message}`;
  }
}

function initSystemSettings() {
  elements.toggleSystemSettings?.addEventListener("click", () => {
    const body = elements.systemSettingsBody;
    const nowHidden = !body.hidden ? true : false;
    body.hidden = nowHidden;
    elements.toggleSystemSettings.textContent = nowHidden ? "Show" : "Hide";
    elements.toggleSystemSettings.setAttribute("aria-expanded", String(!nowHidden));
  });
  elements.settingsForm?.addEventListener("submit", submitSettings);
  elements.globalStop?.addEventListener("click", () => {
    // Global STOP with no axis
    void sendCommandHttp("stop");
  });
}

function bootstrap() {
  // Mount four panels in grid
  const grid = document.getElementById("axis-grid");
  // Order: P, X, Z, R
  new AxisPanel("P", grid, { commandAxis: "p", primaryWsAxes: ["x2"] });
  // X panel mirrors X2 console in addition to X1
  new AxisPanel("X", grid, { commandAxis: "x", primaryWsAxes: ["x1"], mirrorConsoleAxes: ["x2"] });
  new AxisPanel("Z", grid, { commandAxis: "z", primaryWsAxes: ["z"] });
  new AxisPanel("R", grid, { commandAxis: "r", primaryWsAxes: ["r"] });
  initSystemSettings();
  loadSettings();
}

window.addEventListener("DOMContentLoaded", bootstrap);
