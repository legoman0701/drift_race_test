import math, pygame
from typing import Optional, Dict

import drift.config.const as const


def read_inputs(joysticks, car, cam, mouse_follow_mode: bool, ai_path_mode: bool) -> Dict[str, float]:
    """Read player inputs from keyboard, mouse, and joystick.
    
    Args:
        joysticks: List of joystick objects
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
        mouse_pos = pygame.mouse.get_pos()
        # Convert mouse position to world coordinates
        mous_vec = (
            mouse_pos[0] - car.x + cam.x - const.WINDOW_WIDTH / 2,
            mouse_pos[1] - car.y + cam.y - const.WINDOW_HEIGHT / 2
        )
        # Normalize vector
        mag = math.sqrt(mous_vec[0] ** 2 + mous_vec[1] ** 2) or 1.0
        mous_vec = (mous_vec[0] / mag, mous_vec[1] / mag)

        # Calculate steering angle to reach mouse position
        error = (math.atan2(mous_vec[0], mous_vec[1]) - math.pi / 2 + car.angle + math.pi) % (2 * math.pi) - math.pi
        st = -error * 2

    # --- Joystick inputs ---
    if joysticks and joysticks[0] != []:
        js = joysticks[0]
        steering = js.get_axis(0)  # Left stick horizontal
        throttle = (js.get_axis(5) + 1) / 2  # Right trigger (RT)
        breaks = (js.get_axis(4) + 1) / 2  # Left trigger (LT)
        
        # Override keyboard inputs if joystick is active (except in AI path mode)
        if not ai_path_mode:
            st = steering if abs(steering) > 0.1 else st  # Deadzone
            th = throttle if throttle > 0.1 else th
            br = breaks if breaks > 0.1 else br
    
    return {"th": float(th), "st": float(st), "br": float(br)}
