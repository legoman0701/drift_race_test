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
    redline_rpm: float = 6500.0
    idle_rpm: float = 900.0
    stall_rpm: float = 600.0

    # Driveline
    final_drive: float = 4.1
    gear_ratios: tuple[float, ...] = (3.166, 1.481, 0.916)
    wheel_radius_m: float = 0.31  # ~ 615 mm diameter tire

    # Units mapping (game units to meters)
    units_per_meter: float = 20.0  # 50 px == 1 m; adjust to your map scaling

    # Dynamics/smoothing
    upshift_rpm: float = 4500.0
    downshift_rpm: float = 2500.0
    max_rpm_change_per_s: float = 9000.0  # engine spinup limit for smoothing
    engine_brake_strength: float = 0.25   # how fast rpm decays toward wheel rpm on low throttle

    # Drift behavior tuning
    drift_threshold: float = 0.5          # start of drift influence
    drift_free_rev_gain: float = 0.85     # contribution of free-rev target at full drift (0..1)
    drift_slip_gain: float = 0.5          # extra slip allowance at full drift
    drift_brake_scale: float = 0.3        # scale of engine braking at full drift (lower => less braking)

    # Turbo parameters
    has_turbo: bool = True                 # enable/disable turbo simulation
    max_boost_psi: float = 15.0           # maximum boost pressure in PSI
    boost_threshold_rpm: float = 2500.0   # RPM where turbo starts spooling
    full_boost_rpm: float = 4000.0        # RPM where turbo reaches max boost
    turbo_lag_s: float = 0.8              # time constant for turbo spool-up (seconds)
    wastegate_rpm: float = 6500.0         # RPM where wastegate starts opening
    boost_decay_rate: float = 3.0         # how fast boost decays when off-throttle (multiplier)
    boost_rpm_multiplier: float = 1.3     # how much boost affects RPM climb rate


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


def _calc_turbo_boost(
    rpm: float,
    throttle: float,
    prev_boost: float,
    dt: float,
    p: RpmParams
) -> float:
    """Calculate turbo boost pressure with realistic spool dynamics.
    
    Arguments:
    - rpm: current engine RPM
    - throttle: throttle position (0..1)
    - prev_boost: previous frame's boost pressure (PSI)
    - dt: timestep in seconds
    - p: RpmParams containing turbo configuration
    
    Returns:
    - Current boost pressure in PSI
    """
    if not p.has_turbo:
        return 0.0
    
    # Calculate target boost based on RPM and throttle
    target_boost = 0.0
    
    if rpm >= p.boost_threshold_rpm and throttle > 0.1:
        # RPM-based boost curve: ramp from threshold to full boost RPM
        if rpm <= p.full_boost_rpm:
            rpm_factor = (rpm - p.boost_threshold_rpm) / max(1.0, p.full_boost_rpm - p.boost_threshold_rpm)
        else:
            rpm_factor = 1.0
            # Wastegate effect: reduce boost at very high RPM
            if rpm > p.wastegate_rpm:
                wastegate_factor = max(0.5, 1.0 - (rpm - p.wastegate_rpm) / (p.redline_rpm - p.wastegate_rpm))
                rpm_factor *= wastegate_factor
        
        # Throttle affects boost - partial throttle = partial boost
        throttle_factor = _clamp(throttle, 0.0, 1.0) ** 0.7  # slight curve for more linear feel
        
        target_boost = p.max_boost_psi * rpm_factor * throttle_factor
    
    # Apply turbo lag using exponential approach to target
    if target_boost > prev_boost:
        # Spooling up - use turbo lag time constant
        spool_rate = 1.0 / max(0.1, p.turbo_lag_s)
        boost = prev_boost + (target_boost - prev_boost) * (1.0 - (2.718281828 ** (-spool_rate * dt)))
    else:
        # Spooling down - faster decay when off throttle
        decay_rate = p.boost_decay_rate / max(0.1, p.turbo_lag_s)
        boost = prev_boost + (target_boost - prev_boost) * (1.0 - (2.718281828 ** (-decay_rate * dt)))
    
    return _clamp(boost, 0.0, p.max_boost_psi)


def calc_turbo_rpm(
    engine_rpm: float,
    throttle: float = 0.0,
    prev_turbo_rpm: Optional[float] = None,
    dt: float = 1/60,
    params: Optional[RpmParams] = None,
    _state: dict | None = None,
) -> float:
    """Calculate turbo RPM based on engine RPM.
    
    Arguments:
    - engine_rpm: current engine RPM from calc_engine_rpm
    - throttle: throttle position (0..1)
    - prev_turbo_rpm: previous frame's turbo RPM for smoothing
    - dt: timestep in seconds
    - params: RpmParams containing turbo configuration
    - _state: optional dict to persist turbo state
    
    Returns:
    - Turbo RPM (typically much higher than engine RPM)
    """
    p = params or RpmParams()
    
    if not p.has_turbo:
        return 0.0
    
    # Maintain turbo state
    if _state is None:
        _state = {}
    prev_boost: float = _state.get("turbo_boost", 0.0)
    
    # Calculate boost pressure based on engine RPM
    current_boost = _calc_turbo_boost(
        rpm=engine_rpm,
        throttle=throttle,
        prev_boost=prev_boost,
        dt=dt,
        p=p
    )
    _state["turbo_boost"] = current_boost
    
    # Turbo RPM is typically 10-20x engine RPM when spooling
    # Base turbo speed ratio (how fast turbo spins relative to engine)
    base_turbo_ratio = 15.0  # turbo spins 15x faster than engine at idle
    max_turbo_ratio = 25.0   # max ratio at high boost
    
    # Calculate target turbo RPM based on engine RPM and boost
    if current_boost > 0.1:
        # Boost affects turbo speed ratio
        boost_factor = current_boost / p.max_boost_psi
        turbo_ratio = base_turbo_ratio + boost_factor * (max_turbo_ratio - base_turbo_ratio)
        target_turbo_rpm = engine_rpm * turbo_ratio
    else:
        # No boost = turbo spinning at base rate
        target_turbo_rpm = engine_rpm * base_turbo_ratio * 0.3  # much slower when not spooling
    
    # Smooth turbo RPM changes (turbo has inertia)
    if prev_turbo_rpm is None:
        prev_turbo_rpm = target_turbo_rpm
    
    # Turbo spins up/down faster than engine but still has lag
    turbo_accel_rate = p.max_rpm_change_per_s * 3.0  # turbo can change faster than engine
    max_turbo_delta = turbo_accel_rate * dt
    
    turbo_rpm = prev_turbo_rpm + _clamp(target_turbo_rpm - prev_turbo_rpm, -max_turbo_delta, max_turbo_delta)
    
    # Turbo has its own limits (much higher than engine)
    max_turbo_rpm = p.redline_rpm * 20.0  # turbo can spin much faster
    return _clamp(turbo_rpm, 0.0, max_turbo_rpm)


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
    
    Note: For turbo simulation, use calc_turbo_rpm() separately with the engine RPM output.
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

    # Drift influence factor
    # 0 below threshold, 1 at max drift, smooth ramp between
    if p.drift_threshold < 1.0:
        drift_factor = _clamp((drift_ratio - p.drift_threshold) / max(1e-6, (1.0 - p.drift_threshold)), 0.0, 1.0)
    else:
        drift_factor = 0.0

    # Pick gear that keeps rpm in band based on wheel speed
    # If vehicle is essentially stopped, allow free-rev toward throttle-based target when drifting,
    # otherwise bleed toward idle.
    if wheel_rps < 1e-4:
        _state["gear"] = current_gear
        base = prev_rpm if prev_rpm is not None else p.idle_rpm
        th = _clamp(throttle, 0.0, 1.0)
        th_eff = th ** 0.9
        free_rev_rpm = p.idle_rpm + th_eff * (p.redline_rpm - p.idle_rpm)
        # Blend toward free-rev when drifting and/or throttle is applied
        blend = max(drift_factor * p.drift_free_rev_gain, th * 0.5)
        target = base + (free_rev_rpm - base) * _clamp(blend, 0.0, 1.0)
        max_delta = p.max_rpm_change_per_s * dt
        rpm = base + _clamp(target - base, -max_delta, max_delta)
        return _clamp(rpm, p.idle_rpm, p.redline_rpm)

    current_gear = _choose_gear(target_rpm=p.upshift_rpm*0.9, wheel_rps=wheel_rps, p=p, current_gear=current_gear)
    _state["gear"] = current_gear
    gear_ratio = p.gear_ratios[current_gear] * p.final_drive

    wheel_based_rpm = wheel_rps * gear_ratio * 60.0

    # Throttle affects slip: at high throttle the engine can sit above wheel rpm
    throttle = max(0.0, min(1.0, throttle))

    if prev_rpm is None:
        prev_rpm = wheel_based_rpm

    # Free-rev target based on throttle (no wheel coupling)
    th_eff = throttle ** 0.9
    free_rev_rpm = p.idle_rpm + th_eff * (p.redline_rpm - p.idle_rpm)

    # Blend toward wheel rpm based on throttle and drift (engine braking reduced in drift)
    slip_up = 0.25 + 0.6 * throttle + p.drift_slip_gain * drift_factor  # how much RPM can sit above wheel RPM under load
    base_target = wheel_based_rpm * (1.0 + slip_up * 0.15)  # modest slip allowance

    # If throttle is near zero, apply engine braking pulling RPM down (scaled by drift)
    if throttle < 0.15:
        brake_scale = 1.0 - drift_factor * (1.0 - p.drift_brake_scale)
        target_brake = wheel_based_rpm - (wheel_based_rpm - p.idle_rpm) * (p.engine_brake_strength * brake_scale)
        base_target = max(target_brake, p.idle_rpm)

    # Mix with free-rev based on drift
    mix = _clamp(drift_factor * p.drift_free_rev_gain, 0.0, 1.0)
    target_rpm = base_target * (1.0 - mix) + free_rev_rpm * mix

    # Smooth rate of change to avoid jumps
    max_delta = p.max_rpm_change_per_s * dt
    rpm = prev_rpm + _clamp(target_rpm - prev_rpm, -max_delta, max_delta)

    return _clamp(rpm, p.idle_rpm, p.redline_rpm)


def get_turbo_boost(_state: dict | None = None) -> float:
    """Get current turbo boost pressure from state.
    
    Arguments:
    - _state: state dictionary from calc_engine_rpm calls
    
    Returns:
    - Current boost pressure in PSI, or 0.0 if no turbo state
    """
    if _state is None:
        return 0.0
    return _state.get("turbo_boost", 0.0)


__all__ = ["RpmParams", "calc_engine_rpm", "calc_turbo_rpm", "get_turbo_boost"]
