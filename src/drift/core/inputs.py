import math, pygame
from typing import Optional, Dict

import drift.config.const as const


def read_inputs(gamepad, car, cam, mouse_follow_mode: bool, ai_path_mode: bool) -> Dict[str, float]:
    """Read player inputs from keyboard, mouse, and joystick.
    
    Args:
        gamepad: Gamepad object
        car: Player car object (for mouse following mode)
        cam: Camera object (for mouse following mode)
        mouse_follow_mode: If True, use mouse position for steering
        ai_path_mode: If True, joystick overrides are disabled
    
    Returns:
        Dictionary with 'th' (throttle), 'st' (steering), 'br' (brake) keys
    """
    keys = pygame.key.get_pressed()
    
    # --- Keyboard inputs ---
    # Raw digital inputs (-1, 0, or 1)
    th = (1 if any(keys[key] for key in const.UP_KEY) else 0) - \
         (1 if any(keys[key] for key in const.DOWN_KEY) else 0)
    raw_st = (1 if any(keys[key] for key in const.RIGHT_KEY) else 0) - \
             (1 if any(keys[key] for key in const.LEFT_KEY) else 0)
    br = 1.0 if keys[const.BRAKE_KEY] else 0.0

    # Normalize to -1.0 / 0.0 / 1.0
    if th != 0:
        th = 1.0 if th > 0 else -1.0
    if raw_st != 0:
        raw_st = 1.0 if raw_st > 0 else -1.0

    # Use raw steering input (target angle system handles smoothing)
    st = raw_st

    # --- Mouse following mode ---
    if mouse_follow_mode:
        # Mouse steering is handled directly in car.step() by setting target_angle
        # Set steering to 0 to avoid interfering with direct angle control
        st = 0.0

    # --- Joystick inputs ---
    if gamepad and gamepad.joystick:
        js = gamepad.joystick
        steering = js.get_axis(0)  # left stick horizontal : steering
        throttle = round((js.get_axis(5) + 1) / 2, 2) - round((js.get_axis(4) + 1) / 2, 2) # RT : throttle. LT : brake
        handbrake = js.get_button(5)  # RB : handbrake

        # Override keyboard inputs if joystick is active (except in AI path mode)
        if not ai_path_mode:
            st = steering if abs(steering) > 0.1 else st  # Deadzone
            th = throttle if abs(throttle) > 0.1 else th
            br = handbrake if handbrake > 0.1 else br
    
    return {"th": float(th), "st": float(st), "br": float(br)}


def apply_driver_assists(inputs: Dict[str, float], car, dt: float) -> Dict[str, float]:
    """Apply oversteer and understeer assists, modifying steer_angle smoothing on the car.

    Oversteer assist: counter-steer nudge is added to the raw input and the steer-angle
    tracking rate is slowed proportionally to drift severity so the wheel cannot be turned
    faster than the car can recover from the slide.

    Understeer assist: at high speed, steering authority is reduced so the car does not
    snap into a spin from excessive front input.
    """
    import math
    from drift.config.settings import physics_controls

    drivetrain = car.specs.get("specs", {}).get("drivetrain",
                    car.specs.get("drivetrain", "RWD"))
    steer_bias_base = physics_controls.get_value('steer_bias') if physics_controls else 0.0
    steer_bias = steer_bias_base if drivetrain == "RWD" else steer_bias_base * 0.1

    user_st = float(inputs.get("st", 0.0))
    ca, sa = math.cos(car.angle), math.sin(car.angle)
    body_fwd = car.vx * ca + car.vy * sa
    body_lat = car.vx * (-sa) + car.vy * ca
    spd = (body_fwd**2 + body_lat**2 + 1e-4) ** 0.5
    vel_dir_f = body_fwd / spd
    vel_dir_r = body_lat / spd
    drift_angle = ((math.atan2(vel_dir_f, vel_dir_r) - math.pi/2 + math.pi) % (2*math.pi) - math.pi)
    speed_norm = (car.vx**2 + car.vy**2) ** 0.5

    # Understeer assist: reduce driver steer authority at high speed for RWD.
    # This is applied to user input only so it doesn't weaken auto counter-steer.
    if drivetrain == "RWD" and vel_dir_f > 0:
        user_st /= max(1.0, speed_norm / 200)

    assist_st = 0.0
    if vel_dir_f > 0 and steer_bias > 0:
        # Stronger counter-steer assist normalized by drift angle.
        assist_st = max(-1.0, min(1.0, (-drift_angle / math.radians(25.0)) * 0.9 * steer_bias))

        # Slow steering while sliding, but keep enough response for visible counter-steer.
        drift_severity = min(abs(drift_angle) / math.radians(30.0), 1.0)
        car._steer_rate_scale = max(0.70, min(1.0, 1.0 - 0.30 * drift_severity * steer_bias))
    else:
        car._steer_rate_scale = 1.0

    raw_st = user_st + assist_st

    inputs = dict(inputs)
    inputs["st"] = float(max(-1.0, min(1.0, raw_st)))
    return inputs
