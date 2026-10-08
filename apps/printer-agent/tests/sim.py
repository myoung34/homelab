"""A simulated Moonraker/Klipper printer for tests.

Serves the subset of Moonraker's HTTP API the agent uses, backed by mutable
state. Klipper behaviour that matters for verification is modelled: RESTART
reloads printer.cfg (and enters 'error' if it is invalid), G28 sets
homed_axes or fails like a probe that never triggers, print commands move
print_stats through its states, uploads change files.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from printer_agent import klipper_config
from printer_agent.service import config_dict_to_text

FIXTURES = Path(__file__).parent / "fixtures"
T0 = 1_791_000_000.0  # wall clock "start printer" time used in generated logs
MONO0 = 1000.0


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def klippy_log(
    config_text: str,
    *,
    events: list[tuple[float, str]] = (),
    stats: list[tuple[float, dict[str, Any]]] = (),
    start_wall: float = T0,
    start_mono: float = MONO0,
    gcode_dump: list[str] | None = None,
    version: str = "v0.12.0-450-gabcdef",
) -> str:
    """Build a realistic klippy.log. Times are seconds after start."""
    lines = [
        "Starting Klippy...",
        f"Git version: '{version}'",
        f"Start printer at Thu Oct  1 12:00:00 2026 ({start_wall:.1f} {start_mono:.1f})",
        "===== Config file =====",
        *klipper_config.parse(config_text).text.splitlines(),
        "=======================",
    ]
    timeline: list[tuple[float, str]] = []
    for t, groups in stats:
        body = "gcodein=0 "
        for g, kv in groups.items():
            body += f" {g}: " + " ".join(f"{k}={v}" for k, v in kv.items())
        timeline.append((t, f"Stats {start_mono + t:.1f}: {body}"))
    timeline.extend(events)
    timeline.sort(key=lambda x: x[0])
    for _, line in timeline:
        lines.append(line)
    if gcode_dump:
        lines.append(f"Dumping gcode input {len(gcode_dump)} blocks")
        for i, g in enumerate(gcode_dump):
            lines.append(f"Read {start_mono + 500 + i:.6f}: {g!r}")
    return "\n".join(lines) + "\n"


def stats_series(
    n: int,
    *,
    extruder: tuple[float, float, float] = (21.0, 0.0, 0.0),
    bed: tuple[float, float, float] = (21.0, 0.0, 0.0),
    start: float = 1.0,
    extruder_fn: Any = None,
    retransmit_fn: Any = None,
    sysload: float = 0.3,
) -> list[tuple[float, dict]]:
    out = []
    for i in range(n):
        t = start + i
        e = extruder_fn(i) if extruder_fn else extruder
        rt = retransmit_fn(i) if retransmit_fn else 0
        out.append(
            (
                t,
                {
                    "mcu": {
                        "mcu_awake": 0.004,
                        "bytes_write": 1000 + i * 50,
                        "bytes_retransmit": rt,
                        "bytes_invalid": 0,
                        "srtt": 0.001,
                        "freq": 64000000,
                    },
                    "heater_bed": {"target": bed[1], "temp": bed[0], "pwm": bed[2]},
                    # sysload/memavail are host-wide; the parser files them under "_"
                    # wherever they appear, as Klipper appends them after a group.
                    "extruder": {"target": e[1], "temp": e[0], "pwm": e[2], "sysload": sysload, "memavail": 3_000_000},
                },
            )
        )
    return out


@dataclass
class SimPrinter:
    config_text: str = field(default_factory=lambda: fixture("enderbig.cfg"))
    klippy_state: str = "ready"
    state_message: str = "Printer is ready"
    print_state: str = "standby"
    filename: str = ""
    progress: float = 0.0
    homed_axes: str = ""
    extruder: dict[str, float] = field(default_factory=lambda: {"temperature": 21.5, "target": 0.0, "power": 0.0})
    bed: dict[str, float] = field(default_factory=lambda: {"temperature": 21.2, "target": 0.0, "power": 0.0})
    probe_triggered: bool = False
    endstops: dict[str, str] = field(default_factory=lambda: {"x": "open", "y": "open", "z": "open"})
    jobs: list[dict[str, Any]] = field(default_factory=list)
    gcode_store: list[dict[str, Any]] = field(default_factory=list)
    temperature_store: dict[str, Any] = field(default_factory=dict)
    files: dict[str, dict[str, bytes]] = field(default_factory=dict)
    webcams: list[dict[str, Any]] = field(default_factory=list)
    missing_objects: set[str] = field(default_factory=set)
    home_fails_with: str | None = None
    restart_ignored: bool = False
    eventtime: float = MONO0 + 3600
    free_bytes: int = 4_000_000_000
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    loaded: dict[str, dict[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.files.setdefault("config", {})["printer.cfg"] = self.config_text.encode()
        self.files.setdefault("logs", {}).setdefault("klippy.log", klippy_log(self.config_text).encode())
        self.files["logs"].setdefault(
            "moonraker.log", b"2026-10-01 12:00:00,000 [server.py:main()] - Starting Moonraker\n"
        )
        self.files.setdefault("gcodes", {})
        if not self.loaded:
            self.loaded = klipper_config.parse(self.config_text).to_dict()

    # ------------------------------------------------------------ helpers

    def transport(self) -> httpx.ASGITransport:
        return httpx.ASGITransport(app=self.app())

    def reload(self) -> None:
        text = self.files["config"]["printer.cfg"].decode()
        cfg = klipper_config.parse(text)
        errors = [f for f in klipper_config.validate(cfg) if f.severity == "error"]
        if errors:
            self.klippy_state = "error"
            self.state_message = f"Config error: {errors[0].message}"
        else:
            self.klippy_state = "ready"
            self.state_message = "Printer is ready"
            self.loaded = cfg.to_dict()
            self.homed_axes = ""

    def objects(self) -> dict[str, Any]:
        objs: dict[str, Any] = {
            "webhooks": {"state": self.klippy_state, "state_message": self.state_message},
            "print_stats": {
                "state": self.print_state,
                "filename": self.filename,
                "print_duration": 120.0,
                "total_duration": 130.0,
                "filament_used": 50.0,
                "message": "",
                "info": {},
            },
            "virtual_sdcard": {"progress": self.progress, "is_active": self.print_state == "printing"},
            "toolhead": {
                "homed_axes": self.homed_axes,
                "position": [0, 0, 0, 0],
                "max_velocity": 300,
                "max_accel": 3000,
            },
            "extruder": dict(self.extruder),
            "heater_bed": dict(self.bed),
            "idle_timeout": {"state": "Idle"},
            "fan": {"speed": 0.0},
            "probe": {"name": "bltouch", "last_query": self.probe_triggered, "last_z_result": 0.0},
            "mcu": {"mcu_version": "v0.12.0", "last_stats": {"bytes_retransmit": 0, "bytes_invalid": 0, "srtt": 0.001}},
            "system_stats": {"sysload": 0.2, "cputime": 100.0, "memavail": 3_000_000},
            "configfile": {
                "config": self.loaded,
                "warnings": [],
                "save_config_pending": False,
                "save_config_pending_items": {},
            },
            "tmc2209 stepper_x": {"run_current": 0.58, "drv_status": {"cs_actual": 10}},
            "filament_switch_sensor filament_sensor": {"filament_detected": True, "enabled": True},
            "motion_report": {"live_velocity": 0.0},
        }
        return {k: v for k, v in objs.items() if k not in self.missing_objects}

    # ------------------------------------------------------------ routes

    def app(self) -> Starlette:
        sim = self

        def ok(result: Any) -> JSONResponse:
            return JSONResponse({"result": result})

        def err(code: int, msg: str) -> JSONResponse:
            return JSONResponse({"error": {"code": code, "message": msg}}, status_code=code)

        def klippy_required() -> JSONResponse | None:
            if sim.klippy_state not in ("ready", "shutdown", "startup"):
                return err(503, f"Klippy Host not ready ({sim.klippy_state})")
            return None

        async def record(request: Request) -> None:
            sim.calls.append((request.method, request.url.path, dict(request.query_params)))

        async def server_info(request: Request) -> Response:
            await record(request)
            return ok(
                {
                    "klippy_connected": True,
                    "klippy_state": sim.klippy_state,
                    "components": ["history"],
                    "failed_components": [],
                    "warnings": [],
                    "moonraker_version": "v0.9.3-sim",
                }
            )

        async def printer_info(request: Request) -> Response:
            await record(request)
            return ok({"state": sim.klippy_state, "state_message": sim.state_message, "software_version": "v0.12.0"})

        async def objects_list(request: Request) -> Response:
            await record(request)
            if (r := klippy_required()) is not None:
                return r
            return ok({"objects": list(sim.objects())})

        async def objects_query(request: Request) -> Response:
            await record(request)
            if (r := klippy_required()) is not None:
                return r
            objs = sim.objects()
            out = {}
            for key, val in request.query_params.items():
                if key in objs:
                    fields = [f for f in val.split(",") if f]
                    out[key] = {k: v for k, v in objs[key].items() if not fields or k in fields}
            return ok({"eventtime": sim.eventtime, "status": out})

        async def temperature_store(request: Request) -> Response:
            await record(request)
            return ok(sim.temperature_store)

        async def gcode_store(request: Request) -> Response:
            await record(request)
            n = int(request.query_params.get("count", 100))
            return ok({"gcode_store": sim.gcode_store[-n:]})

        async def history_list(request: Request) -> Response:
            await record(request)
            limit = int(request.query_params.get("limit", 50))
            jobs = sorted(sim.jobs, key=lambda j: j["start_time"], reverse=True)[:limit]
            return ok({"count": len(jobs), "jobs": jobs})

        async def history_job(request: Request) -> Response:
            await record(request)
            uid = request.query_params.get("uid")
            for j in sim.jobs:
                if j["job_id"] == uid:
                    return ok({"job": j})
            return err(404, f"job {uid} not found")

        async def files_list(request: Request) -> Response:
            await record(request)
            root = request.query_params.get("root", "gcodes")
            return ok([{"path": p, "modified": T0 + 10, "size": len(b)} for p, b in sim.files.get(root, {}).items()])

        async def files_metadata(request: Request) -> Response:
            await record(request)
            name = request.query_params.get("filename", "")
            if name not in sim.files["gcodes"]:
                return err(404, f"Metadata not available for <{name}>")
            return ok({"filename": name, "size": len(sim.files["gcodes"][name])})

        async def files_directory(request: Request) -> Response:
            await record(request)
            return ok(
                {
                    "dirs": [],
                    "files": [],
                    "disk_usage": {"total": 8e9, "used": 8e9 - sim.free_bytes, "free": sim.free_bytes},
                }
            )

        async def file_get(request: Request) -> Response:
            await record(request)
            root = request.path_params["root"]
            path = request.path_params["path"]
            data = sim.files.get(root, {}).get(path)
            if data is None:
                return err(404, f"File {root}/{path} does not exist")
            rng = request.headers.get("range")
            if rng and rng.startswith("bytes=-"):
                n = int(rng[7:])
                part = data[-n:]
                return Response(
                    part,
                    status_code=206,
                    headers={"content-range": f"bytes {len(data) - len(part)}-{len(data) - 1}/{len(data)}"},
                )
            return Response(data)

        async def upload(request: Request) -> Response:
            await record(request)
            form = await request.form()
            root = str(form.get("root", "gcodes"))
            directory = str(form.get("path", "") or "")
            up = form["file"]
            content = await up.read()  # type: ignore[union-attr]
            name = f"{directory}/{up.filename}" if directory else str(up.filename)  # type: ignore[union-attr]
            sim.files.setdefault(root, {})[name] = content
            return ok({"item": {"path": name, "root": root}, "action": "create_file"})

        async def endstops(request: Request) -> Response:
            await record(request)
            if (r := klippy_required()) is not None:
                return r
            return ok(sim.endstops)

        async def gcode_script(request: Request) -> Response:
            await record(request)
            if sim.klippy_state != "ready":
                return err(503, "Klippy not ready")
            script = request.query_params.get("script", "")
            now = time.time()
            sim.gcode_store.append({"message": script, "time": now, "type": "command"})
            cmd = script.split()[0].upper()
            if cmd == "G28":
                if sim.home_fails_with:
                    sim.gcode_store.append({"message": f"!! {sim.home_fails_with}", "time": now, "type": "response"})
                    return err(400, sim.home_fails_with)
                axes = "".join(a.lower() for a in script.split()[1:]) or "xyz"
                sim.homed_axes = "".join(a for a in "xyz" if a in sim.homed_axes + axes)
            elif cmd == "SET_HEATER_TEMPERATURE":
                params = dict(p.split("=") for p in script.split()[1:])
                target = float(params["TARGET"])
                heater = params["HEATER"]
                (sim.extruder if heater == "extruder" else sim.bed)["target"] = target
            elif cmd == "QUERY_PROBE":
                pass
            else:
                return err(400, f"sim does not implement {cmd}")
            return ok("ok")

        async def print_action(request: Request) -> Response:
            await record(request)
            action = request.path_params["action"]
            if action == "start":
                name = request.query_params.get("filename", "")
                if name not in sim.files["gcodes"]:
                    return err(400, "file not found")
                sim.print_state, sim.filename = "printing", name
            elif action == "pause":
                sim.print_state = "paused"
            elif action == "resume":
                sim.print_state = "printing"
            elif action == "cancel":
                sim.print_state = "cancelled"
            return ok("ok")

        async def restart(request: Request) -> Response:
            await record(request)
            if not sim.restart_ignored:
                sim.reload()
                log = sim.files["logs"]["klippy.log"].decode()
                sim.files["logs"]["klippy.log"] = (
                    log + f"Start printer at Thu Oct  1 13:00:00 2026 ({T0 + 3600:.1f} {MONO0 + 3600:.1f})\n"
                ).encode()
            return ok("ok")

        async def estop(request: Request) -> Response:
            await record(request)
            sim.klippy_state, sim.state_message = "shutdown", "Shutdown due to webhooks request"
            return ok("ok")

        async def webcams(request: Request) -> Response:
            await record(request)
            return ok({"webcams": sim.webcams})

        return Starlette(
            routes=[
                Route("/server/info", server_info),
                Route("/printer/info", printer_info),
                Route("/printer/objects/list", objects_list),
                Route("/printer/objects/query", objects_query),
                Route("/server/temperature_store", temperature_store),
                Route("/server/gcode_store", gcode_store),
                Route("/server/history/list", history_list),
                Route("/server/history/job", history_job),
                Route("/server/files/list", files_list),
                Route("/server/files/metadata", files_metadata),
                Route("/server/files/directory", files_directory),
                Route("/server/files/upload", upload, methods=["POST"]),
                Route("/server/files/{root}/{path:path}", file_get),
                Route("/printer/query_endstops/status", endstops),
                Route("/printer/gcode/script", gcode_script, methods=["POST"]),
                Route("/printer/print/{action}", print_action, methods=["POST"]),
                Route("/printer/restart", restart, methods=["POST"]),
                Route("/printer/firmware_restart", restart, methods=["POST"]),
                Route("/printer/emergency_stop", estop, methods=["POST"]),
                Route("/server/webcams/list", webcams),
            ]
        )


class OfflineTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)


def job(
    job_id: str, status: str, start: float, duration: float = 600.0, filename: str = "part.gcode", **extra: Any
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "status": status,
        "start_time": start,
        "end_time": start + duration,
        "print_duration": duration * 0.9,
        "total_duration": duration,
        "filament_used": 1000.0,
        "filename": filename,
        "exists": True,
        "user": None,
        "metadata": {"filament_total": 2000.0},
        **extra,
    }


# --------------------------------------------------------------- scenarios


def scenario(name: str, **kw: Any) -> SimPrinter:
    cfg = kw.pop("config_text", fixture("enderbig.cfg"))
    if name == "healthy":
        return SimPrinter(config_text=cfg, jobs=[job("000001", "completed", T0 + 100)], **kw)
    if name == "printing":
        return SimPrinter(
            config_text=cfg,
            print_state="printing",
            filename="part.gcode",
            progress=0.42,
            extruder={"temperature": 210.1, "target": 210.0, "power": 0.45},
            bed={"temperature": 60.0, "target": 60.0, "power": 0.3},
            jobs=[job("000002", "in_progress", T0 + 200)],
            **kw,
        )
    if name == "paused":
        return SimPrinter(config_text=cfg, print_state="paused", filename="part.gcode", **kw)
    if name == "mcu_disconnected":
        stats = stats_series(
            120, extruder=(210.0, 210.0, 0.45), bed=(60.0, 60.0, 0.9), start=200, retransmit_fn=lambda i: i * 30
        )
        log = klippy_log(
            cfg,
            stats=stats,
            events=[
                (320.5, "Timeout with MCU 'mcu' (eventtime=1320.500)"),
                (320.6, "Transition to shutdown state: Lost communication with MCU 'mcu'"),
            ],
        )
        sim = SimPrinter(
            config_text=cfg,
            klippy_state="shutdown",
            state_message="Lost communication with MCU 'mcu'",
            jobs=[job("000003", "klippy_shutdown", T0 + 190, duration=131), job("000002", "completed", T0 - 5000)],
            **kw,
        )
        sim.files["logs"]["klippy.log"] = log.encode()
        return sim
    if name == "thermal_runaway":

        def ext(i: int) -> tuple[float, float, float]:
            # at target, then the heater stops delivering: temp falls at full power
            return (210.0, 210.0, 0.4) if i < 60 else (210.0 - (i - 60) * 0.5, 210.0, 1.0)

        stats = stats_series(110, extruder_fn=ext, bed=(60.0, 60.0, 0.3), start=200)
        log = klippy_log(
            cfg,
            stats=stats,
            events=[
                (309.5, "Heater extruder not heating at expected rate"),
                (309.6, "Transition to shutdown state: Heater extruder not heating at expected rate"),
            ],
            gcode_dump=["G1 X100 Y100 E0.4", "G1 X110 Y100 E0.4"],
        )
        sim = SimPrinter(
            config_text=cfg,
            klippy_state="shutdown",
            state_message="Heater extruder not heating at expected rate",
            jobs=[job("000004", "klippy_shutdown", T0 + 190, duration=120), job("000003", "completed", T0 - 9000)],
            **kw,
        )
        sim.files["logs"]["klippy.log"] = log.encode()
        return sim
    if name == "probe_failure":
        log = klippy_log(
            cfg,
            stats=stats_series(30, start=100),
            events=[
                (125.0, "No trigger on z after full movement"),
            ],
        )
        sim = SimPrinter(
            config_text=cfg,
            jobs=[job("000005", "error", T0 + 110, duration=20), job("000004", "completed", T0 - 9000)],
            **kw,
        )
        sim.files["logs"]["klippy.log"] = log.encode()
        sim.gcode_store = [
            {"message": "G28", "time": T0 + 115, "type": "command"},
            {"message": "!! No trigger on z after full movement", "time": T0 + 125.2, "type": "response"},
        ]
        return sim
    if name == "config_error":
        return SimPrinter(
            config_text=cfg,
            klippy_state="error",
            state_message="Option 'sensor_pin' in section 'bltouch' must be specified",
            **kw,
        )
    if name == "cancelled":
        sim = SimPrinter(config_text=cfg, jobs=[job("000006", "cancelled", T0 + 100, user="mark")], **kw)
        sim.gcode_store = [{"message": "CANCEL_PRINT", "time": T0 + 650, "type": "command"}]
        return sim
    raise ValueError(name)


def loaded_text(sim: SimPrinter) -> str:
    return config_dict_to_text(sim.loaded)


def as_json(o: Any) -> str:
    return json.dumps(o, indent=2, default=str)
