"""Heater behaviour analysis over a 1 Hz series of (temp, target, pwm).

Used for both Moonraker's temperature_store (last ~20 min, live) and Stats
traces reconstructed from klippy.log (before a shutdown).
"""

from __future__ import annotations

import itertools
import statistics
from dataclasses import dataclass
from typing import Any

# Settled-band thresholds. Bed heaters are slower and steadier.
LIMITS = {
    "extruder": {"std": 1.0, "max_dev": 3.0},
    "heater_bed": {"std": 0.5, "max_dev": 2.0},
}
JUMP_THRESHOLD = 10.0  # degC change between consecutive 1 s samples: not physical


@dataclass(slots=True)
class ThermalAnalysis:
    heater: str
    samples: int
    verdict: str  # idle | heating | stable | unstable | fault_suspected | insufficient_data
    findings: list[str]
    stats: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "heater": self.heater,
            "samples": self.samples,
            "verdict": self.verdict,
            "findings": self.findings,
            "stats": self.stats,
        }


def analyse(
    heater: str, temps: list[float | None], targets: list[float], pwms: list[float] | None = None
) -> ThermalAnalysis:
    n = min(len(temps), len(targets))
    t = [x for x in temps[-n:]]
    tg = targets[-n:]
    pw = (pwms or [])[-n:] if pwms else []
    findings: list[str] = []
    stats: dict[str, Any] = {}
    valid = [x for x in t if x is not None]
    if len(valid) < 10:
        return ThermalAnalysis(heater, len(valid), "insufficient_data", ["fewer than 10 samples"], stats)
    jumps = [
        (i, abs(t[i] - t[i - 1]))  # type: ignore[operator]
        for i in range(1, n)
        if t[i] is not None and t[i - 1] is not None and abs(t[i] - t[i - 1]) > JUMP_THRESHOLD  # type: ignore[operator]
    ]
    if jumps:
        worst = max(j for _, j in jumps)
        findings.append(
            f"{len(jumps)} single-sample jumps > {JUMP_THRESHOLD:g}C (worst {worst:.1f}C): "
            "a heater cannot change temperature this fast; points to an intermittent "
            "thermistor connection or electrical noise"
        )
        stats["jumps"] = len(jumps)
    current_target = tg[-1]
    stats["current"] = {"temp": t[-1], "target": current_target}
    if current_target <= 0:
        verdict = "fault_suspected" if jumps else "idle"
        return ThermalAnalysis(heater, len(valid), verdict, findings, stats)
    # Settled region: contiguous tail at the current target, after first
    # coming within 2C of it.
    start = n - 1
    while start > 0 and tg[start - 1] == current_target:
        start -= 1
    seg = [(t[i], pw[i] if i < len(pw) else None) for i in range(start, n) if t[i] is not None]
    # "Reached" = first within 2C of target, or first sample on the other side
    # of it (a 1 Hz sample can skip over the band while oscillating).
    reached = None
    for i, (temp, _) in enumerate(seg):
        if temp is None:
            continue
        prev = seg[i - 1][0] if i > 0 else None
        crossed = prev is not None and (prev - current_target) * (temp - current_target) < 0
        if abs(temp - current_target) <= 2.0 or crossed:
            reached = i
            break
    if reached is None:
        rising = len(seg) > 10 and seg[-1][0] > seg[0][0] + 1  # type: ignore[operator]
        saturated = [p for _, p in seg[-30:] if p is not None and p >= 0.95]
        stats["heating"] = {"seconds_at_target": len(seg), "from": seg[0][0], "now": seg[-1][0]}
        if not rising and len(seg) > 30:
            msg = f"target {current_target:g}C set for {len(seg)} s without the temperature rising"
            if saturated:
                msg += " while heater PWM is saturated (>=95%): heater/wiring not delivering power"
            findings.append(msg)
            return ThermalAnalysis(heater, len(valid), "fault_suspected", findings, stats)
        return ThermalAnalysis(heater, len(valid), "heating" if not jumps else "fault_suspected", findings, stats)
    settled = [temp for temp, _ in seg[reached:] if temp is not None]
    if len(settled) < 10:
        return ThermalAnalysis(heater, len(valid), "heating", findings, stats)
    err = [x - current_target for x in settled]
    std = statistics.pstdev(err)
    max_dev = max(abs(e) for e in err)
    crossings = sum(1 for a, b in itertools.pairwise(err) if (a < 0) != (b < 0))
    p_settled = [p for _, p in seg[reached:] if p is not None]
    stats.update(
        {
            "settled_seconds": len(settled),
            "mean_error": round(statistics.fmean(err), 2),
            "std": round(std, 2),
            "max_deviation": round(max_dev, 2),
            "zero_crossings": crossings,
        }
    )
    if p_settled:
        stats["pwm_mean"] = round(statistics.fmean(p_settled), 3)
        stats["pwm_max"] = round(max(p_settled), 3)
        if statistics.fmean(p_settled) > 0.9:
            findings.append(
                f"holding target needs {statistics.fmean(p_settled):.0%} average power: little "
                "headroom (strong part cooling, draft, failing heater, or missing sock)"
            )
    lim = LIMITS.get(heater, LIMITS["extruder"])
    unstable = std > lim["std"] or max_dev > lim["max_dev"]
    if unstable:
        kind = "oscillating around target (PID tuning or airflow)" if crossings > 6 else "drifting/excursions"
        findings.append(
            f"temperature std {std:.2f}C, max deviation {max_dev:.1f}C at target {current_target:g}C: {kind}"
        )
    verdict = "fault_suspected" if jumps else "unstable" if unstable else "stable"
    return ThermalAnalysis(heater, len(valid), verdict, findings, stats)


def analyse_trace(heater: str, trace: list[dict[str, float]]) -> ThermalAnalysis:
    return analyse(heater, [s["temp"] for s in trace], [s["target"] for s in trace], [s["pwm"] for s in trace])


def runaway_shape(trace: list[dict[str, float]]) -> dict[str, Any]:
    """Characterize the ~60 s before a verify_heater/ADC shutdown."""
    tail = trace[-60:]
    if len(tail) < 5:
        return {"shape": "insufficient_data"}
    temps = [s["temp"] for s in tail]
    pwms = [s["pwm"] for s in tail]
    target = tail[-1]["target"]
    sat = sum(1 for p in pwms if p >= 0.95) / len(pwms)
    drop = temps[0] - temps[-1]
    jumps = sum(1 for a, b in itertools.pairwise(temps) if abs(b - a) > JUMP_THRESHOLD)
    shape = "unclear"
    if jumps:
        shape = "sensor_jumps"
    elif sat > 0.6 and drop > 2:
        shape = "falling_at_full_power"
    elif sat > 0.6 and abs(drop) <= 2 and target - temps[-1] > 5:
        shape = "flat_below_target_at_full_power"
    elif temps[-1] > target + 15:
        shape = "overshoot_above_target"
    return {
        "shape": shape,
        "target": target,
        "temp_first": temps[0],
        "temp_last": temps[-1],
        "pwm_saturated_fraction": round(sat, 2),
        "single_sample_jumps": jumps,
    }
