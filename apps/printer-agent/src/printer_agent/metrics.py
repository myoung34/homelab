"""Prometheus-format metrics, scraped by the existing Datadog agent.

No Prometheus server is run: the pod carries a Datadog OpenMetrics
autodiscovery annotation (see the homelab manifests). Cardinality is kept to
printers x a handful of series.
"""

from __future__ import annotations

from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

REGISTRY = CollectorRegistry()

TOOL_CALLS = Counter("printer_agent_tool_calls", "MCP tool calls", ["tool", "outcome"], registry=REGISTRY)
TOOL_DURATION = Histogram(
    "printer_agent_tool_duration_seconds",
    "MCP tool latency",
    ["tool"],
    buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
    registry=REGISTRY,
)
ACTIONS = Counter(
    "printer_agent_actions",
    "Privileged action attempts by outcome",
    ["action", "printer", "risk", "outcome"],
    registry=REGISTRY,
)
DIAGNOSES = Counter("printer_agent_diagnoses", "Diagnoses produced", ["printer", "failure_class"], registry=REGISTRY)
POLL_ERRORS = Counter(
    "printer_agent_poll_errors",
    "Background poll failures",
    ["printer", "source"],
    registry=REGISTRY,
)

ONLINE = Gauge("printer_online", "Moonraker reachable (1/0)", ["printer"], registry=REGISTRY)
KLIPPY_READY = Gauge("printer_klippy_ready", "Klipper ready (1/0)", ["printer"], registry=REGISTRY)
STATE = Gauge("printer_state", "Print state one-hot", ["printer", "state"], registry=REGISTRY)
PRINT_ACTIVE = Gauge("printer_print_active", "Printing or paused (1/0)", ["printer"], registry=REGISTRY)
PROGRESS = Gauge("printer_print_progress_ratio", "Print progress 0..1", ["printer"], registry=REGISTRY)
PRINT_DURATION = Gauge("printer_print_duration_seconds", "Current print duration", ["printer"], registry=REGISTRY)
TEMP = Gauge(
    "printer_temperature_celsius",
    "Heater/sensor temperature",
    ["printer", "sensor"],
    registry=REGISTRY,
)
TARGET = Gauge("printer_target_temperature_celsius", "Heater target", ["printer", "sensor"], registry=REGISTRY)
POWER = Gauge("printer_heater_power_ratio", "Heater PWM 0..1", ["printer", "sensor"], registry=REGISTRY)
FAN = Gauge("printer_fan_speed_ratio", "Fan speed 0..1", ["printer", "fan"], registry=REGISTRY)
VELOCITY = Gauge("printer_toolhead_velocity_mm_s", "Live toolhead velocity", ["printer"], registry=REGISTRY)
MCU_RETRANSMIT = Gauge(
    "printer_mcu_retransmit_bytes",
    "MCU link retransmitted bytes (cumulative)",
    ["printer", "mcu"],
    registry=REGISTRY,
)
JOBS = Gauge(
    "printer_jobs",
    "Jobs in Moonraker history by status (last 200)",
    ["printer", "status"],
    registry=REGISTRY,
)
TELEMETRY_AGE = Gauge(
    "printer_telemetry_age_seconds",
    "Seconds since last successful poll",
    ["printer"],
    registry=REGISTRY,
)

PRINT_STATES = ("standby", "printing", "paused", "complete", "cancelled", "error")


def render() -> bytes:
    return bytes(generate_latest(REGISTRY))


def update_from_status(printer: str, status: dict[str, Any] | None) -> None:
    if status is None:
        ONLINE.labels(printer).set(0)
        KLIPPY_READY.labels(printer).set(0)
        return
    ONLINE.labels(printer).set(1)
    KLIPPY_READY.labels(printer).set(1 if status.get("klippy_state") == "ready" else 0)
    objs = status.get("status", {})
    ps = objs.get("print_stats", {})
    state = ps.get("state")
    for s in PRINT_STATES:
        STATE.labels(printer, s).set(1 if s == state else 0)
    PRINT_ACTIVE.labels(printer).set(1 if state in ("printing", "paused") else 0)
    if "virtual_sdcard" in objs:
        PROGRESS.labels(printer).set(float(objs["virtual_sdcard"].get("progress") or 0))
    if ps:
        PRINT_DURATION.labels(printer).set(float(ps.get("print_duration") or 0))
    for name, val in objs.items():
        if name in ("extruder", "heater_bed") or name.startswith(("temperature_sensor ", "heater_generic ")):
            sensor = name.split(" ", 1)[-1]
            if val.get("temperature") is not None:
                TEMP.labels(printer, sensor).set(float(val["temperature"]))
            if val.get("target") is not None:
                TARGET.labels(printer, sensor).set(float(val["target"]))
            if val.get("power") is not None:
                POWER.labels(printer, sensor).set(float(val["power"]))
        is_fan = name == "fan" or name.startswith(("heater_fan ", "fan_generic ", "controller_fan "))
        if is_fan and val.get("speed") is not None:
            FAN.labels(printer, name.split(" ", 1)[-1]).set(float(val["speed"]))
        if name == "mcu" or name.startswith("mcu "):
            rt = (val.get("last_stats") or {}).get("bytes_retransmit")
            if rt is not None:
                MCU_RETRANSMIT.labels(printer, name).set(float(rt))
    mr = objs.get("motion_report", {})
    if mr.get("live_velocity") is not None:
        VELOCITY.labels(printer).set(float(mr["live_velocity"]))
