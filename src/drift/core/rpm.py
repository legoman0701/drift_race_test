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
    redline_rpm: float = 7000.0
    idle_rpm: float = 900.0
    stall_rpm: float = 600.0

    # Driveline
    final_drive: float = 4.1
    gear_ratios: tuple[float, ...] = (3.166, 1.481, 1.1, 0.8)
    wheel_radius_m: float = 0.31  # ~ 615 mm diameter tire

    # Units mapping (game units to meters)
    units_per_meter: float = 10.0  # 50 px == 1 m; adjust to your map scaling

    # Dynamics/smoothing - instant shifting at thresholds
    upshift_rpm: float = 6500.0          # instant upshift at this RPM
    downshift_rpm: float = 3500.0        # lower downshift point for more power
    max_rpm_change_per_s: float = 12000.0  # faster RPM changes for snappier response
    engine_brake_strength: float = 0.15   # reduced engine braking for more free-revving feel

    # Drift behavior tuning - enhanced for manual transmission feel
    drift_threshold: float = 0.4          # start of drift influence (lowered for earlier engagement)
    drift_free_rev_gain: float = 0.95     # contribution of free-rev target at full drift (increased)
    drift_slip_gain: float = 0.8          # extra slip allowance at full drift (increased)
    drift_brake_scale: float = 0.15       # scale of engine braking at full drift (reduced for less braking)
    
    # Manual transmission parameters - instant shifting
    manual_mode: bool = True              # enable manual transmission characteristics
    aggressive_shift_delay: float = 0.0   # absolutely no delay for instant shifting
    clutch_slip_factor: float = 0.3       # reduced clutch slip to prevent RPM hanging
    rev_hang_time: float = 0.3            # much shorter rev hang
    overrev_limit: float = 1.02           # minimal overrev allowance (102% max)


def _clamp(v: float, lo: float, hi: float) -> float:
    return hi if v > hi else lo if v < lo else v


def _choose_gear(target_rpm: float, wheel_rps: float, p: RpmParams, current_gear: int, 
                 drift_ratio: float = 0.0, throttle: float = 0.0, prev_gear_time: float = 0.0) -> int:
    """Pick a gear index (0-based) trying to keep RPM between downshift and upshift.
    Enhanced with manual transmission characteristics and drift behavior.
    """
    if wheel_rps <= 1e-4:
        return max(current_gear, 0)

    # Compute rpm per gear at current wheel speed
    rpms = [wheel_rps * gr * p.final_drive * 60.0 for gr in p.gear_ratios]

    # Prefer the nearest gear that keeps within band
    best = current_gear
    if best < 0 or best >= len(p.gear_ratios):
        best = 0

    # Manual transmission behavior: delay gear changes and be more aggressive
    if p.manual_mode:
        # During drift, hold gears longer and allow higher RPM
        if drift_ratio > p.drift_threshold:
            upshift_threshold = p.upshift_rpm * (1.0 + drift_ratio * 0.4)  # Allow higher RPM when drifting
            downshift_threshold = p.downshift_rpm * (1.0 - drift_ratio * 0.3)  # Shift down later
        else:
            upshift_threshold = p.upshift_rpm
            downshift_threshold = p.downshift_rpm
        
        # Remove any delay - instant shifting only
        # No time-based restrictions for immediate response
        
        # Instant upshift behavior - shift immediately at threshold
        if rpms[best] >= upshift_threshold and best < len(rpms) - 1:
            # Always upshift immediately when RPM threshold is reached
            next_gear = best + 1
            if next_gear < len(rpms):
                return next_gear

        # Instant downshift behavior
        if rpms[best] <= downshift_threshold and best > 0:
            # Always downshift immediately when RPM threshold is reached
            prev_gear = best - 1
            if prev_gear >= 0:
                return prev_gear
    else:
        # Original automatic behavior
        if rpms[best] > p.upshift_rpm and best < len(rpms) - 1:
            for g in range(best + 1, len(rpms)):
                if rpms[g] <= p.upshift_rpm:
                    return g
            return len(rpms) - 1

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
    """Estimate engine RPM from vehicle speed and state with enhanced manual transmission feel.

    Arguments
    - speed_units: vehicle speed magnitude in "game units / s" (pixels/s by default)
    - drift_ratio: 0..1 measure of drift; if > ~0.4 we assume aggressive driving
    - throttle: -1..1 (absolute value used), affects clutch slip/spinup
    - prev_rpm: last frame's rpm for smoothing; if None, starts from wheel rpm
    - dt: timestep in seconds
    - params: RpmParams to override defaults
    - _state: optional dict to persist transient state (like current gear, shift timing)

    Enhanced Behavior for Drift/Manual Feel
    - More aggressive gear selection during drift
    - Rev hanging after throttle lift for drift style
    - Allow overrev during aggressive driving
    - Manual transmission shift delays
    - Enhanced clutch slip simulation
    """
    p = params or RpmParams()
    # Convert speed to m/s
    v_mps = speed_units / p.units_per_meter

    # Wheel rotational speed in rev/s
    two_pi = 6.283185307179586
    wheel_rps = 0.0 if p.wheel_radius_m <= 1e-6 else (v_mps / (two_pi * p.wheel_radius_m))

    # Maintain state
    if _state is None:
        _state = {}
    current_gear: int = _state.get("gear", 0)
    last_gear_change_time: float = _state.get("last_gear_change", 0.0)
    rev_hang_target: float = _state.get("rev_hang_target", p.idle_rpm)
    
    current_time = _state.get("current_time", 0.0) + dt
    _state["current_time"] = current_time

    # Enhanced drift influence factor
    if p.drift_threshold < 1.0:
        drift_factor = _clamp((drift_ratio - p.drift_threshold) / max(1e-6, (1.0 - p.drift_threshold)), 0.0, 1.0)
    else:
        drift_factor = 0.0

    # Calculate time since last gear change
    time_since_gear_change = current_time - last_gear_change_time

    # Treat reverse input like forward load for engine RPM modeling.
    # This keeps reverse audible while still using first-gear ratios.
    throttle_abs = abs(float(throttle))

    # Enhanced stopped/low speed behavior with rev hanging
    if wheel_rps < 1e-4:
        _state["gear"] = current_gear
        base = prev_rpm if prev_rpm is not None else p.idle_rpm
        th = _clamp(throttle_abs, 0.0, 1.0)
        
        # Rev hanging: when throttle is lifted, RPM hangs for a bit (drift style)
        if th < 0.1 and prev_rpm and prev_rpm > p.idle_rpm * 1.5:
            rev_hang_target = max(rev_hang_target * (1.0 - dt / p.rev_hang_time), p.idle_rpm)
            _state["rev_hang_target"] = rev_hang_target
            target = max(rev_hang_target, p.idle_rpm + th * (p.redline_rpm - p.idle_rpm))
        else:
            # Normal throttle response with enhanced aggression
            th_eff = th ** 0.8  # More responsive than original
            free_rev_rpm = p.idle_rpm + th_eff * (p.redline_rpm - p.idle_rpm)
            # Allow overrev during aggressive driving
            if drift_ratio > 0.6 and th > 0.8:
                free_rev_rpm = min(free_rev_rpm * p.overrev_limit, p.redline_rpm * p.overrev_limit)
            
            blend = max(drift_factor * p.drift_free_rev_gain, th * 0.7)  # More aggressive blend
            target = base + (free_rev_rpm - base) * _clamp(blend, 0.0, 1.0)
            _state["rev_hang_target"] = target
        
        # Enhanced RPM change rate during drift
        max_delta = p.max_rpm_change_per_s * dt
        if drift_ratio > 0.4:
            max_delta *= (1.0 + drift_ratio * 0.5)  # Faster RPM changes when drifting
        
        rpm = base + _clamp(target - base, -max_delta, max_delta)
        return _clamp(rpm, p.idle_rpm, p.redline_rpm * p.overrev_limit)

    # Enhanced gear selection with manual characteristics
    new_gear = _choose_gear(
        target_rpm=p.upshift_rpm,  # Use full upshift RPM, not 90%
        wheel_rps=wheel_rps, 
        p=p, 
        current_gear=current_gear,
        drift_ratio=drift_ratio,
        throttle=throttle,
        prev_gear_time=time_since_gear_change
    )
    
    # Track gear changes
    if new_gear != current_gear:
        _state["last_gear_change"] = current_time
        last_gear_change_time = current_time
    
    _state["gear"] = new_gear
    current_gear = new_gear
    gear_ratio = p.gear_ratios[current_gear] * p.final_drive

    wheel_based_rpm = wheel_rps * gear_ratio * 60.0

    # Enhanced throttle and clutch slip
    throttle = max(0.0, min(1.0, throttle_abs))

    if prev_rpm is None:
        prev_rpm = wheel_based_rpm

    # Enhanced free-rev with overrev capability
    th_eff = throttle ** 0.8  # More responsive
    free_rev_rpm = p.idle_rpm + th_eff * (p.redline_rpm - p.idle_rpm)
    
    # Allow overrev during drift and high throttle
    if drift_ratio > 0.5 and throttle > 0.7:
        free_rev_rpm = min(free_rev_rpm * p.overrev_limit, p.redline_rpm * p.overrev_limit)

    # Enhanced slip calculation - simplified to prevent RPM hanging
    base_slip = 0.1 + 0.3 * throttle  # Reduced slip for instant response
    drift_slip = p.drift_slip_gain * drift_factor * 0.5  # Reduced drift slip
    
    # Remove clutch slip during gear changes to prevent RPM hanging
    total_slip = base_slip + drift_slip
    base_target = wheel_based_rpm * (1.0 + total_slip * 0.1)  # Reduced slip effect

    # Enhanced engine braking with drift scaling
    if throttle < 0.15:
        brake_scale = 1.0 - drift_factor * (1.0 - p.drift_brake_scale)
        # Reduced engine braking for more free-revving feel
        brake_strength = p.engine_brake_strength * 0.7  # Weaker engine braking
        target_brake = wheel_based_rpm - (wheel_based_rpm - p.idle_rpm) * (brake_strength * brake_scale)
        base_target = max(target_brake, p.idle_rpm)

    # Enhanced mixing with free-rev
    mix = _clamp(drift_factor * p.drift_free_rev_gain, 0.0, 1.0)
    target_rpm = base_target * (1.0 - mix) + free_rev_rpm * mix

    # Enhanced rate limiting - much faster to prevent RPM hanging
    max_delta = p.max_rpm_change_per_s * dt * 3.0  # 3x faster base rate
    if drift_ratio > 0.3:
        max_delta *= (2.0 + drift_ratio)  # Even faster when drifting
    
    # Special case: if gear just changed, allow instant RPM adjustment
    if time_since_gear_change < 0.1:
        max_delta *= 10.0  # 10x faster right after gear change
    
    rpm = prev_rpm + _clamp(target_rpm - prev_rpm, -max_delta, max_delta)

    # Allow overrev with gradual limiting
    max_rpm = p.redline_rpm * p.overrev_limit if drift_ratio > 0.4 else p.redline_rpm
    
    return _clamp(rpm, p.idle_rpm, max_rpm)


__all__ = ["RpmParams", "calc_engine_rpm"]
