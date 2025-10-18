import math, pygame
from typing import Optional, Dict

import drift.config.const as const


def get_text_input(surface: pygame.Surface, title_text: str, tip_text: str,
                   font_big: pygame.font.Font, font_small: pygame.font.Font,
                   allowed_set: Optional[str] = None, min_length: int = 0,
                   error_callback=None) -> Optional[str]:
    """Generic text input handler with validation.
    
    Args:
        surface: Pygame surface to draw on
        title_text: Main title text to display
        tip_text: Help text to display
        font_big: Large font for title and input
        font_small: Small font for tips
        allowed_set: String of allowed characters (None = all printable)
        min_length: Minimum required length (0 = no minimum)
        error_callback: Function that takes text and returns error message or None
    
    Returns:
        Input text string or None if cancelled
    """    
    pygame.key.set_repeat(const.KEY_REPEAT_DELAY, const.KEY_REPEAT_INTERVAL)
    text = ""
    error_msg = ""
    
    while True:
        surface.fill((20, 20, 25))
        
        # Title
        title = font_big.render(title_text, True, const.WHITE_240)
        surface.blit(title, (const.WINDOW_WIDTH // 2 - title.get_width() // 2, const.WINDOW_HEIGHT // 2 - 70))
        
        # Input text
        disp_text = text if text else "(empty)"
        inp = font_big.render(disp_text, True, (180, 255, 180))
        surface.blit(inp, (const.WINDOW_WIDTH // 2 - inp.get_width() // 2, const.WINDOW_HEIGHT // 2 - 10))
        
        # Tip text
        tip = font_small.render(tip_text, True, (180, 180, 180))
        surface.blit(tip, (const.WINDOW_WIDTH // 2 - tip.get_width() // 2, const.WINDOW_HEIGHT // 2 + 40))
        
        # Error message
        if error_msg:
            error_surf = font_big.render(error_msg, True, (230, 80, 80))
            surface.blit(error_surf, (const.WINDOW_WIDTH // 2 - error_surf.get_width() // 2, const.WINDOW_HEIGHT // 2 - 120))
        
        pygame.display.flip()
        
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit()
                raise SystemExit(0)
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN:
                    # Validate minimum length
                    if min_length > 0 and len(text) < min_length:
                        error_msg = f"Must be at least {min_length} characters long."
                        continue
                    # Custom validation callback
                    if error_callback:
                        validation_error = error_callback(text)
                        if validation_error:
                            error_msg = validation_error
                            continue
                    return text or None
                elif ev.key == const.ESCAPE_KEY:
                    return None
                elif ev.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                    error_msg = ""
                else:
                    ch = ev.unicode.upper() if allowed_set is not None else ev.unicode
                    if allowed_set is None or (ch in allowed_set):
                        if len(text) < const.MAX_CODE_LENGTH:
                            text += ch
                            error_msg = ""


def get_code_input(surface: pygame.Surface, font_big: pygame.font.Font, 
                   font_small: pygame.font.Font) -> Optional[str]:
    """Get room code input from user."""
    return get_text_input(
        surface,
        "Enter ROOM CODE (A-Z/0-9)",
        "Enter : validate  -  Esc : cancel",
        font_big, 
        font_small, 
        allowed_set=const.ROOM_ALPHABET
    )


def get_name_input(surface: pygame.Surface, font_big: pygame.font.Font, 
                   font_small: pygame.font.Font, tag: str) -> Optional[str]:
    """Get player name input with profanity check."""
    
    def validate_name(name: str) -> Optional[str]:
        """Returns error message if invalid, None if valid."""
        if name.upper() in const.PROFANITY_SET:
            return "Inappropriate name. Choose another."
        return None
    
    return get_text_input(
        surface,
        "Enter your name",
        "Enter : OK  -  Esc : cancel",
        font_big,
        font_small,
        allowed_set=None,  # Allow all printable characters
        min_length=const.MIN_NAME_LENGTH,
        error_callback=validate_name
    )


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

    # --- Steering smoothing (keyboard only) ---
    # Exponential smoothing for more natural steering feel
    if not hasattr(read_inputs, "_smoothed_st"):
        read_inputs._smoothed_st = 0.0
    
    # Smoothly approach target steering value
    if read_inputs._smoothed_st < raw_st:
        read_inputs._smoothed_st += 0.07
    else:
        read_inputs._smoothed_st -= 0.07
    
    # Avoid tiny float drift
    if abs(read_inputs._smoothed_st) < 1e-3:
        read_inputs._smoothed_st = 0.0
    
    st = read_inputs._smoothed_st

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
