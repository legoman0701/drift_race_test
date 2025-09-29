"""
Engine RPM estimation utilities.

This module provides `calc_engine_rpm`, a semi-realistic RPM model that:
- Uses wheel speed with gear ratios, final drive, and wheel radius
- Handles clutch/traction slip and throttle influence
- Smooths RPM change and clamps to idle/redline
- Forces RPM to redline when the car is drifting

Units and conventions
- speed_units: pixels per second by default (same as car.v magnitude)
- wheel_radius_px: converts pixels to radians at the wheel. If your
  game uses meters, set `units_per_meter` to 1.0 and provide `wheel_radius_m`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RpmParams:
    # Vehicle/engine parameters
    redline_rpm: float = 7800.0
    idle_rpm: float = 900.0
    stall_rpm: float = 600.0

    # Driveline
    final_drive: float = 4.1
    gear_ratios: tuple[float, ...] = (3.166, 2.050, 1.481, 1.166, 0.916)  # close-ish 5-speed
    wheel_radius_m: float = 0.31  # ~ 615 mm diameter tire

    # Units mapping (game units to meters)
    units_per_meter: float = 10.0  # 50 px == 1 m; adjust to your map scaling

    # Dynamics/smoothing
    upshift_rpm: float = 7200.0
    downshift_rpm: float = 2500.0
    max_rpm_change_per_s: float = 9000.0  # engine spinup limit for smoothing
    engine_brake_strength: float = 0.25   # how fast rpm decays toward wheel rpm on low throttle


def _clamp(v: float, lo: float, hi: float) -> float:
    return hi if v > hi else lo if v < lo else v


def _choose_gear(target_rpm: float, wheel_rps: float, p: RpmParams, current_gear: int) -> int:
    """Pick a gear index (0-based) trying to keep RPM between downshift and upshift.
    Uses current gear as a hint to avoid gear hunting.
    """
    if wheel_rps <= 1e-4:
        return max(current_gear, 0)

    # Compute rpm per gear at current wheel speed
    rpms = [wheel_rps * gr * p.final_drive * 60.0 for gr in p.gear_ratios]

    # Prefer the nearest gear that keeps within band
    best = current_gear
    if best < 0 or best >= len(p.gear_ratios):
        best = 0

    # If above upshift threshold in current gear, try higher gears
    if rpms[best] > p.upshift_rpm and best < len(rpms) - 1:
        for g in range(best + 1, len(rpms)):
            if rpms[g] <= p.upshift_rpm:
                return g
        return len(rpms) - 1

    # If below downshift threshold, try lower gears
    if rpms[best] < p.downshift_rpm and best > 0:
        for g in range(best - 1, -1, -1):
            if rpms[g] >= p.downshift_rpm:
                return g
        return 0

    return best


def calc_engine_rpm(
    speed_units: float,
    drift_ratio: float = 0.0,
    throttle: float = 0.0,
    prev_rpm: Optional[float] = None,
    dt: float = 1/60,
    params: Optional[RpmParams] = None,
    _state: dict | None = None,
) -> float:
    """Estimate engine RPM from vehicle speed and state.

    Arguments
    - speed_units: vehicle speed magnitude in "game units / s" (pixels/s by default)
    - drift_ratio: 0..1 measure of drift; if > ~0.6 we assume tires are sliding
    - throttle: -1..1 (only positive used here), affects clutch slip/spinup
    - prev_rpm: last frame's rpm for smoothing; if None, starts from wheel rpm
    - dt: timestep in seconds
    - params: RpmParams to override defaults
    - _state: optional dict to persist transient state (like current gear)

    Behavior
    - If drifting (drift_ratio >= 0.6), RPM goes to redline (with gentle smoothing)
    - Otherwise, compute wheel RPM and map to engine RPM using gear ratio
    - Auto-select gear to keep RPM in a reasonable band
    - Apply engine braking when off-throttle, allow slip/spin-up on throttle
    - Clamp to [idle, redline] after smoothing
    """
    p = params or RpmParams()
    # Convert speed to m/s
    v_mps = speed_units / p.units_per_meter

    # Wheel rotational speed in rev/s
    # wheel_rps = linear_speed / (2*pi*R)
    # Avoid importing math repeatedly; inline constants
    two_pi = 6.283185307179586
    wheel_rps = 0.0 if p.wheel_radius_m <= 1e-6 else (v_mps / (two_pi * p.wheel_radius_m))

    # Maintain current gear in _state
    if _state is None:
        _state = {}
    current_gear: int = _state.get("gear", 0)

    # Drifting => go to redline
    if drift_ratio >= 0.6:
        target_rpm = p.redline_rpm
        # simple smoothing toward redline
        base = prev_rpm if prev_rpm is not None else p.redline_rpm * 0.8
        max_delta = p.max_rpm_change_per_s * dt
        rpm = base + _clamp(target_rpm - base, -max_delta, max_delta)
        rpm = _clamp(rpm, p.idle_rpm, p.redline_rpm)
        _state["gear"] = current_gear
        return rpm

    # Pick gear that keeps rpm in band based on wheel speed
    # If vehicle is essentially stopped, keep current gear and idle
    if wheel_rps < 1e-4:
        _state["gear"] = current_gear
        base = prev_rpm if prev_rpm is not None else p.idle_rpm
        # bleed toward idle when stopped
        rpm = base + (p.idle_rpm - base) * _clamp(dt * 2.0, 0.0, 1.0)
        return _clamp(rpm, p.idle_rpm, p.redline_rpm)

    current_gear = _choose_gear(target_rpm=p.upshift_rpm*0.9, wheel_rps=wheel_rps, p=p, current_gear=current_gear)
    _state["gear"] = current_gear
    gear_ratio = p.gear_ratios[current_gear] * p.final_drive

    wheel_based_rpm = wheel_rps * gear_ratio * 60.0

    # Throttle affects slip: at high throttle the engine can sit above wheel rpm
    throttle = max(0.0, min(1.0, throttle))

    if prev_rpm is None:
        prev_rpm = wheel_based_rpm

    # Blend toward wheel rpm based on throttle (engine braking when low throttle)
    slip_up = 0.25 + 0.6 * throttle     # how much RPM can sit above wheel RPM under load
    target_rpm = wheel_based_rpm * (1.0 + slip_up * 0.15)  # modest slip allowance

    # If throttle is near zero, apply engine braking pulling RPM down
    if throttle < 0.15:
        target_rpm = wheel_based_rpm - (wheel_based_rpm - p.idle_rpm) * p.engine_brake_strength
        target_rpm = max(target_rpm, p.idle_rpm)

    # Smooth rate of change to avoid jumps
    max_delta = p.max_rpm_change_per_s * dt
    rpm = prev_rpm + _clamp(target_rpm - prev_rpm, -max_delta, max_delta)

    return _clamp(rpm, p.idle_rpm, p.redline_rpm)


__all__ = ["RpmParams", "calc_engine_rpm"]
