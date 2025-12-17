import pygame, json, time, math
import drift.config.const as const
from drift.ui.ui_helpers import invalidate_ui_text_cache, get_cached_text
from drift.core.helpers import rand_code
from drift.net.communication import connect_to_relay, recv_jsons
from drift.ui.slider import Slider
from drift.config.settings import settings_manager
from drift.tools.paths import normalize_asset_path

# Game setup state (shared across new_game and join_game UI)
_game_setup = {
    "username": "",
    "username_active": False,
    "selected_car": "ae86",  # Default car
    "selected_track": "track1",  # Default track
    "selected_mode": "beta",  # Default mode
    "room_code": "",  # For join game
    "code_active": False,  # For join game code input
    "error_message": None,  # For displaying errors
}

# Key binds state
_key_binds_state = {
    "waiting_for_key": None,  # Which bind is waiting for input (e.g., "UP_KEY")
    "selected_bind": None,  # Currently selected/hovered bind
}

# Car rotation state for selection screens
_car_rotation_angle = 0.0  # Global rotation angle for all car sprites

def _load_car_specs(car_type):
    """Load car specifications from JSON file."""
    try:
        spec_path = normalize_asset_path("cars", car_type.upper(), "specs.json")
        with open(spec_path, "r", encoding="utf-8") as fh:
            specs = json.load(fh)
        return specs.get("manufacturer", "Unknown"), specs.get("model", "Unknown")
    except Exception as e:
        print(f"Warning: Could not load specs for {car_type}: {e}")
        return "Unknown", "Unknown"

def _update_car_rotation(dt):
    """Update the global car rotation angle for selection screens."""
    global _car_rotation_angle
    # Rotate at 45 degrees per second (π/4 radians per second)
    _car_rotation_angle += (math.pi / 4) * dt
    if _car_rotation_angle >= 2 * math.pi:
        _car_rotation_angle -= 2 * math.pi

def draw_lobby():         
    pass

def draw_game():
    pass

def draw_error(ui_surf, error_msg, font_small):
    msg = font_small.render(error_msg, True, (255,200,200))
    ui_surf.blit(msg, (const.WINDOW_WIDTH//2 - msg.get_width()//2, const.WINDOW_HEIGHT//2))
    tip = font_small.render("Press R to restart", True, const.GREY_200)
    ui_surf.blit(tip, (const.WINDOW_WIDTH//2 - tip.get_width()//2, const.WINDOW_HEIGHT//2 + 40))


def draw_new_game(ui_surf, font_big, font_medium, car_sprites_cache=None, dt=0.016):
    """Draw new game setup screen with username input, car/track/mode selection.
    This creates a clean new page with solid background color."""
    
    # Update car rotation
    _update_car_rotation(dt)
    
    # Button dimensions
    btn_width = const.BTN_WIDTH
    btn_height = const.BTN_HEIGHT
    center_x = const.WINDOW_WIDTH // 2
    
    y_start = const.WINDOW_HEIGHT * 0.08
    spacing = btn_height + 30
    
    # Username section
    y = y_start
    label = font_medium.render("Username", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))
    
    # Username input box
    input_box_rect = pygame.Rect(center_x - btn_width // 2, y + 35, btn_width, btn_height)
    input_color = (100, 200, 100) if _game_setup["username_active"] else (80, 80, 90)
    pygame.draw.rect(ui_surf, input_color, input_box_rect, 2)
    
    # Username text (only show if username exists, no placeholder)
    if _game_setup["username"]:
        username_surf = font_medium.render(_game_setup["username"], True, const.WHITE_240)
        ui_surf.blit(username_surf, (input_box_rect.centerx - username_surf.get_width() // 2, 
                                      input_box_rect.centery - username_surf.get_height() // 2))
    
    # Car selection section
    y += spacing + 35
    label = font_medium.render("Car", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))
    
    # Car buttons - now with sprites instead of text
    car_spacing = 30
    car_btn_width = (btn_width - car_spacing) // 2
    car_btn_height = btn_height + 40  # Extra height for car sprite and manufacturer text
    car1_rect = pygame.Rect(center_x - btn_width // 4 - car_btn_width - car_spacing, y + 35, car_btn_width, car_btn_height)
    car2_rect = pygame.Rect(center_x - btn_width // 4, y + 35, car_btn_width, car_btn_height)
    car3_rect = pygame.Rect(center_x - btn_width // 4 + car_btn_width + car_spacing, y + 35, car_btn_width, car_btn_height)
    
    car1_color = const.GREEN if _game_setup["selected_car"] == "ae86" else (80, 80, 90)
    car2_color = const.GREEN if _game_setup["selected_car"] == "barracuda" else (80, 80, 90)
    car3_color = const.GREEN if _game_setup["selected_car"] == "911" else (80, 80, 90)
    
    pygame.draw.rect(ui_surf, car1_color, car1_rect, 2)
    pygame.draw.rect(ui_surf, car2_color, car2_rect, 2)
    pygame.draw.rect(ui_surf, car3_color, car3_rect, 2)
    
    # Draw car sprites if available
    if car_sprites_cache:
        # ae86 car sprite
        ae86_sprites = car_sprites_cache.get("ae86", [])
        if ae86_sprites:
            # Use only the main diffuse sprite (index 1)
            main_sprite = ae86_sprites[1] if len(ae86_sprites) > 1 else ae86_sprites[0] if ae86_sprites else None
            if main_sprite:
                # Calculate sprite angle and index for rotation
                show_angle = (-_car_rotation_angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
                sprite_index = round(show_angle * 64) % 64
                sprite = main_sprite[sprite_index]
                sprite_size = (sprite.get_width(), sprite.get_height())
                # Position sprite in upper part of button
                sprite_x = car1_rect.centerx - sprite_size[0] // 2
                sprite_y = car1_rect.y + 10
                ui_surf.blit(sprite, (sprite_x, sprite_y))
        
        # barracuda car sprite
        barracuda_sprites = car_sprites_cache.get("barracuda", [])
        if barracuda_sprites:
            # Use only the main diffuse sprite (index 1)
            main_sprite = barracuda_sprites[1] if len(barracuda_sprites) > 1 else barracuda_sprites[0] if barracuda_sprites else None
            if main_sprite:
                # Calculate sprite angle and index for rotation
                show_angle = (-_car_rotation_angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
                sprite_index = round(show_angle * 64) % 64
                sprite = main_sprite[sprite_index]
                sprite_size = (sprite.get_width(), sprite.get_height())
                # Position sprite in upper part of button
                sprite_x = car2_rect.centerx - sprite_size[0] // 2
                sprite_y = car2_rect.y + 10
                ui_surf.blit(sprite, (sprite_x, sprite_y))
        
        # 911 car sprite
        p911_sprites = car_sprites_cache.get("911", [])
        if p911_sprites:
            # Use only the main diffuse sprite (index 1)
            main_sprite = p911_sprites[1] if len(p911_sprites) > 1 else p911_sprites[0] if p911_sprites else None
            if main_sprite:
                # Calculate sprite angle and index for rotation
                show_angle = (-_car_rotation_angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
                sprite_index = round(show_angle * 64) % 64
                sprite = main_sprite[sprite_index]
                sprite_size = (sprite.get_width(), sprite.get_height())
                # Position sprite in upper part of button
                sprite_x = car3_rect.centerx - sprite_size[0] // 2
                sprite_y = car3_rect.y + 10
                ui_surf.blit(sprite, (sprite_x, sprite_y))
    
    # Draw manufacturer and model text underneath sprites
    ae86_manufacturer, ae86_model = _load_car_specs("ae86")
    barracuda_manufacturer, barracuda_model = _load_car_specs("barracuda")
    p911_manufacturer, p911_model = _load_car_specs("911")
    
    # ae86 text
    ae86_text = font_medium.render(f"{ae86_manufacturer} {ae86_model}", True, const.WHITE_240)
    ui_surf.blit(ae86_text, (car1_rect.centerx - ae86_text.get_width() // 2, 
                             car1_rect.bottom - ae86_text.get_height() - 5))
    
    # barracuda text
    barracuda_text = font_medium.render(f"{barracuda_manufacturer} {barracuda_model}", True, const.WHITE_240)
    ui_surf.blit(barracuda_text, (car2_rect.centerx - barracuda_text.get_width() // 2, 
                           car2_rect.bottom - barracuda_text.get_height() - 5))

    # 911 text
    p911_text = font_medium.render(f"{p911_manufacturer} {p911_model}", True, const.WHITE_240)
    ui_surf.blit(p911_text, (car3_rect.centerx - p911_text.get_width() // 2, 
                              car3_rect.bottom - p911_text.get_height() - 5))

    # Track selection section
    y += spacing + 75  # Extra space to account for taller car buttons
    label = font_medium.render("Track", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))
    
    track_rect = pygame.Rect(center_x - btn_width // 2, y + 35, btn_width, btn_height)
    track_color = const.GREEN if _game_setup["selected_track"] == "track1" else (80, 80, 90)
    pygame.draw.rect(ui_surf, track_color, track_rect, 2)

    track_text = font_medium.render("track1", True, const.WHITE_240)
    ui_surf.blit(track_text, (track_rect.centerx - track_text.get_width() // 2, 
                               track_rect.centery - track_text.get_height() // 2))
    
    # Mode button
    y += spacing + 35
    label = font_medium.render("Mode", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))

    mode_rect = pygame.Rect(center_x - btn_width // 2, y + 35, btn_width, btn_height)
    mode_color = const.GREEN if _game_setup["selected_mode"] == "beta" else (80, 80, 90)
    pygame.draw.rect(ui_surf, mode_color, mode_rect, 2)

    mode_text = font_medium.render("beta", True, const.WHITE_240)
    ui_surf.blit(mode_text, (mode_rect.centerx - mode_text.get_width() // 2, 
                              mode_rect.centery - mode_text.get_height() // 2))

    # Host Game button
    y += spacing + 50
    host_btn_rect = pygame.Rect(center_x - btn_width // 2, y, btn_width, btn_height)
    pygame.draw.rect(ui_surf, const.GREEN, host_btn_rect)
    
    host_text = font_big.render("Host", True, const.WHITE_240)
    ui_surf.blit(host_text, (host_btn_rect.centerx - host_text.get_width() // 2, 
                              host_btn_rect.centery - host_text.get_height() // 2))
    
    # Error message area
    y += btn_height + 20
    if _game_setup["error_message"]:
        error_surf = font_medium.render(_game_setup["error_message"], True, (255, 100, 100))
        ui_surf.blit(error_surf, (center_x - error_surf.get_width() // 2, y))
    
    # Store rects for click detection (returned for event handling)
    return {
        "username_box": input_box_rect,
        "car1_btn": car1_rect,
        "car2_btn": car2_rect,
        "car3_btn": car3_rect,
        "track_btn": track_rect,
        "mode_btn": mode_rect,
        "host_btn": host_btn_rect,
    }

def draw_join_game(ui_surf, font_big, font_medium, car_sprites_cache=None, dt=0.016):
    """Draw join game screen with username input, car selection, and code input.
    This creates a clean new page with solid background color."""
    
    # Update car rotation
    _update_car_rotation(dt)
    
    # Fill background with solid color (dark background)
    ui_surf.fill(const.GREY_20)
    
    # Button dimensions
    btn_width = const.BTN_WIDTH
    btn_height = const.BTN_HEIGHT
    center_x = const.WINDOW_WIDTH // 2
    
    y_start = const.WINDOW_HEIGHT * 0.1
    spacing = btn_height + 30
    
    # Username section
    y = y_start
    label = font_medium.render("Username", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))
    
    # Username input box
    input_box_rect = pygame.Rect(center_x - btn_width // 2, y + 35, btn_width, btn_height)
    input_color = (100, 200, 100) if _game_setup["username_active"] else (80, 80, 90)
    pygame.draw.rect(ui_surf, input_color, input_box_rect, 2)
    
    # Username text (only show if username exists, no placeholder)
    if _game_setup["username"]:
        username_surf = font_medium.render(_game_setup["username"], True, const.WHITE_240)
        ui_surf.blit(username_surf, (input_box_rect.centerx - username_surf.get_width() // 2, 
                                      input_box_rect.centery - username_surf.get_height() // 2))
    
    # Car selection section
    y += spacing + 35
    label = font_medium.render("Car", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))
    
    # Car buttons - now with sprites instead of text
    car_spacing = 30
    car_btn_width = (btn_width - car_spacing) // 2
    car_btn_height = btn_height + 40  # Extra height for car sprite and manufacturer text
    car1_rect = pygame.Rect(center_x - btn_width // 4 - car_btn_width - car_spacing, y + 35, car_btn_width, car_btn_height)
    car2_rect = pygame.Rect(center_x - btn_width // 4, y + 35, car_btn_width, car_btn_height)
    car3_rect = pygame.Rect(center_x - btn_width // 4 + car_btn_width + car_spacing, y + 35, car_btn_width, car_btn_height)
    
    car1_color = const.GREEN if _game_setup["selected_car"] == "ae86" else (80, 80, 90)
    car2_color = const.GREEN if _game_setup["selected_car"] == "barracuda" else (80, 80, 90)
    car3_color = const.GREEN if _game_setup["selected_car"] == "911" else (80, 80, 90)
    
    pygame.draw.rect(ui_surf, car1_color, car1_rect, 2)
    pygame.draw.rect(ui_surf, car2_color, car2_rect, 2)
    pygame.draw.rect(ui_surf, car3_color, car3_rect, 2)

    # Draw car sprites if available
    if car_sprites_cache:
        # ae86 car sprite
        ae86_sprites = car_sprites_cache.get("ae86", [])
        if ae86_sprites:
            # Use only the main diffuse sprite (index 1)
            main_sprite = ae86_sprites[1] if len(ae86_sprites) > 1 else ae86_sprites[0] if ae86_sprites else None
            if main_sprite:
                # Calculate sprite angle and index for rotation
                show_angle = (-_car_rotation_angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
                sprite_index = round(show_angle * 64) % 64
                sprite = main_sprite[sprite_index]
                sprite_size = (sprite.get_width(), sprite.get_height())
                # Position sprite in upper part of button
                sprite_x = car1_rect.centerx - sprite_size[0] // 2
                sprite_y = car1_rect.y + 10
                ui_surf.blit(sprite, (sprite_x, sprite_y))
        
        # barracuda car sprite
        barracuda_sprites = car_sprites_cache.get("barracuda", [])
        if barracuda_sprites:
            # Use only the main diffuse sprite (index 1)
            main_sprite = barracuda_sprites[1] if len(barracuda_sprites) > 1 else barracuda_sprites[0] if barracuda_sprites else None
            if main_sprite:
                # Calculate sprite angle and index for rotation
                show_angle = (-_car_rotation_angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
                sprite_index = round(show_angle * 64) % 64
                sprite = main_sprite[sprite_index]
                sprite_size = (sprite.get_width(), sprite.get_height())
                # Position sprite in upper part of button
                sprite_x = car2_rect.centerx - sprite_size[0] // 2
                sprite_y = car2_rect.y + 10
                ui_surf.blit(sprite, (sprite_x, sprite_y))

        # 911 car sprite
        p911_sprites = car_sprites_cache.get("911", [])
        if p911_sprites:
            # Use only the main diffuse sprite (index 1)
            main_sprite = p911_sprites[1] if len(p911_sprites) > 1 else p911_sprites[0] if p911_sprites else None
            if main_sprite:
                # Calculate sprite angle and index for rotation
                show_angle = (-_car_rotation_angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
                sprite_index = round(show_angle * 64) % 64
                sprite = main_sprite[sprite_index]
                sprite_size = (sprite.get_width(), sprite.get_height())
                # Position sprite in upper part of button
                sprite_x = car3_rect.centerx - sprite_size[0] // 2
                sprite_y = car3_rect.y + 10
                ui_surf.blit(sprite, (sprite_x, sprite_y))
    
    # Draw manufacturer and model text underneath sprites
    ae86_manufacturer, ae86_model = _load_car_specs("ae86")
    barracuda_manufacturer, barracuda_model = _load_car_specs("barracuda")
    p911_manufacturer, p911_model = _load_car_specs("911")

    # ae86 text
    ae86_text = font_medium.render(f"{ae86_manufacturer} {ae86_model}", True, const.WHITE_240)
    ui_surf.blit(ae86_text, (car1_rect.centerx - ae86_text.get_width() // 2, 
                             car1_rect.bottom - ae86_text.get_height() - 5))
    
    # barracuda text
    barracuda_text = font_medium.render(f"{barracuda_manufacturer} {barracuda_model}", True, const.WHITE_240)
    ui_surf.blit(barracuda_text, (car2_rect.centerx - barracuda_text.get_width() // 2, 
                           car2_rect.bottom - barracuda_text.get_height() - 5))
    
    # 911 text
    p911_text = font_medium.render(f"{p911_manufacturer} {p911_model}", True, const.WHITE_240)
    ui_surf.blit(p911_text, (car3_rect.centerx - p911_text.get_width() // 2, 
                              car3_rect.bottom - p911_text.get_height() - 5))
    
    # Code section
    y += spacing + 75  # Extra space to account for taller car buttons
    label = font_medium.render("Room Code", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))
    
    # Code input box
    code_box_rect = pygame.Rect(center_x - btn_width // 2, y + 35, btn_width, btn_height)
    code_color = (100, 200, 100) if _game_setup.get("code_active", False) else (80, 80, 90)
    pygame.draw.rect(ui_surf, code_color, code_box_rect, 2)
    
    # Code text (only show if code exists, no placeholder)
    if _game_setup.get("room_code", ""):
        code_surf = font_medium.render(_game_setup["room_code"], True, const.WHITE_240)
        ui_surf.blit(code_surf, (code_box_rect.centerx - code_surf.get_width() // 2, 
                                  code_box_rect.centery - code_surf.get_height() // 2))
    
    # Join Game button
    y += spacing + 50
    join_btn_rect = pygame.Rect(center_x - btn_width // 2, y, btn_width, btn_height)
    pygame.draw.rect(ui_surf, const.GREEN, join_btn_rect)
    
    join_text = font_big.render("Join", True, const.WHITE_240)
    ui_surf.blit(join_text, (join_btn_rect.centerx - join_text.get_width() // 2, 
                              join_btn_rect.centery - join_text.get_height() // 2))
    
    # Error message area
    y += btn_height + 10
    if _game_setup["error_message"]:
        error_surf = font_medium.render(_game_setup["error_message"], True, (255, 100, 100))
        ui_surf.blit(error_surf, (center_x - error_surf.get_width() // 2, y))
    
    # Store rects for click detection (returned for event handling)
    return {
        "username_box": input_box_rect,
        "car1_btn": car1_rect,
        "car2_btn": car2_rect,
        "car3_btn": car3_rect,
        "code_box": code_box_rect,
        "join_btn": join_btn_rect,
    }

def handle_new_game_click(click_pos, rects):
    """Handle mouse clicks on new game UI elements."""
    if rects["username_box"].collidepoint(click_pos):
        _game_setup["username_active"] = True
        _game_setup["code_active"] = False
        return "username_clicked"
    elif rects["car1_btn"].collidepoint(click_pos):
        _game_setup["selected_car"] = "ae86"
        return "car1_selected"
    elif rects["car2_btn"].collidepoint(click_pos):
        _game_setup["selected_car"] = "barracuda"
        return "car2_selected"
    elif rects["car3_btn"].collidepoint(click_pos):
        _game_setup["selected_car"] = "911"
        return "car3_selected"
    elif rects["track_btn"].collidepoint(click_pos):
        return "track_clicked"
    elif rects["mode_btn"].collidepoint(click_pos):
        return "mode_clicked"
    elif rects["host_btn"].collidepoint(click_pos):
        return "host_game"
    return None

def handle_join_game_click(click_pos, rects):
    """Handle mouse clicks on join game UI elements."""
    if rects["username_box"].collidepoint(click_pos):
        _game_setup["username_active"] = True
        _game_setup["code_active"] = False
        return "username_clicked"
    elif rects["car1_btn"].collidepoint(click_pos):
        _game_setup["selected_car"] = "ae86"
        return "car1_selected"
    elif rects["car2_btn"].collidepoint(click_pos):
        _game_setup["selected_car"] = "barracuda"
        return "car2_selected"
    elif rects["car3_btn"].collidepoint(click_pos):
        _game_setup["selected_car"] = "911"
        return "car3_selected"
    elif rects["code_box"].collidepoint(click_pos):
        _game_setup["code_active"] = True
        _game_setup["username_active"] = False
        return "code_clicked"
    elif rects["join_btn"].collidepoint(click_pos):
        return "join_game"
    return None

def handle_new_game_keypress(event):
    """Handle keyboard input for username field."""
    if _game_setup["username_active"]:
        if event.key == pygame.K_BACKSPACE:
            _game_setup["username"] = _game_setup["username"][:-1]
        elif event.key == pygame.K_ESCAPE:
            _game_setup["username_active"] = False
        else:
            # Add character if printable and within length limit
            if event.unicode and event.unicode.isprintable():
                if len(_game_setup["username"]) < const.MAX_NAME_LENGTH:
                    _game_setup["username"] += event.unicode

def handle_join_game_keypress(event):
    """Handle keyboard input for username and code fields in join game."""
    if _game_setup["username_active"]:
        if event.key == pygame.K_TAB:
            _game_setup["code_active"] = True
            _game_setup["username_active"] = False
        elif event.key == pygame.K_BACKSPACE:
            _game_setup["username"] = _game_setup["username"][:-1]
        elif event.key == pygame.K_ESCAPE:
            _game_setup["username_active"] = False
        else:
            # Add character if printable and within length limit
            if event.unicode and event.unicode.isprintable():
                if len(_game_setup["username"]) < const.MAX_NAME_LENGTH:
                    _game_setup["username"] += event.unicode
    elif _game_setup["code_active"]:
        if event.key == pygame.K_TAB:
            _game_setup["code_active"] = False
            _game_setup["username_active"] = True
        elif event.key == pygame.K_BACKSPACE:
            _game_setup["room_code"] = _game_setup["room_code"][:-1]
        elif event.key == pygame.K_ESCAPE:
            _game_setup["code_active"] = False
        else:
            # Add character if printable and within length limit (room codes are typically short)
            if event.unicode and event.unicode.isprintable():
                if len(_game_setup["room_code"]) < 4:  # Room codes are usually short
                    _game_setup["room_code"] += event.unicode.upper()  # Convert to uppercase

def get_game_setup():
    """Get current game setup configuration."""
    return _game_setup.copy()

def reset_game_setup():
    """Reset game setup to defaults."""
    _game_setup["username"] = ""
    _game_setup["username_active"] = True
    _game_setup["selected_car"] = "ae86"
    _game_setup["selected_track"] = "track1"
    _game_setup["selected_mode"] = "beta"
    _game_setup["room_code"] = ""
    _game_setup["code_active"] = False
    _game_setup["error_message"] = None

def set_error_message(message):
    """Set an error message to display in the UI."""
    _game_setup["error_message"] = message

def clear_error_message():
    """Clear the error message."""
    _game_setup["error_message"] = None

def host_new_game(my_id):
    """
    Host a new game with the configured settings.
    Returns: (stage1, my_name, code, sock, is_host, host_name) tuple
    """
    
    my_name = _game_setup["username"] or "Player"
    code = rand_code()
    sock = None
    is_host = True
    host_name = my_name  # When hosting, you are the host
    
    try:
        sock = connect_to_relay()
        join_pkt = {
            "t": "create",
            "code": code,
            "name": my_name,
            "id": my_id,
            "car_type": _game_setup["selected_car"],
            "track": _game_setup["selected_track"],
            "mode": _game_setup["selected_mode"]
        }
        sock.send(json.dumps(join_pkt).encode("utf-8"))
        
        # Wait briefly for server confirmation
        join_ok_received = False
        timeout = time.time() + 1.0
        while time.time() < timeout:
            for msg in recv_jsons(sock):
                if msg.get("t") == "join_ok":
                    join_ok_received = True
                    # Extract host_name from relay response (should be our name)
                    host_name = msg.get("host_name", my_name)
                    break
                if msg.get("t") == "error":
                    raise Exception(msg.get("msg", "relay error"))
            if join_ok_received:
                break
            time.sleep(0.02)
        
        if not join_ok_received:
            # Relay didn't confirm; fall back to offline mode
            try:
                sock.close()
            except Exception:
                pass
            sock = None
            code = "Offline"
            is_host = True  # Offline single-player acts as host
        
    except Exception as e:
        # Relay unreachable; fall back to offline mode
        print(f"Failed to connect to relay: {e}")
        try:
            if sock:
                sock.close()
        except Exception:
            pass
        sock = None
        code = "Offline"
        is_host = True
    
    # Invalidate UI text cache when room code changes
    invalidate_ui_text_cache('room')
    return ("game", my_name, code, sock, is_host, host_name)

def join_new_game(my_id):
    """
    Join an existing game with the configured settings.
    Returns: (stage1, my_name, code, sock, is_host, host_name) tuple
    """    
    my_name = _game_setup["username"] or "Player"
    code = _game_setup["room_code"].upper() if _game_setup["room_code"] else ""
    sock = None
    is_host = False
    host_name = "Host"  # Default if not received
    error = None
    
    # Special bypass code to access offline mode
    if code == "-_--_-":
        code = "Offline"
        is_host = False
        return ("game", my_name, code, sock, is_host, host_name, error)
    
    try:
        sock = connect_to_relay()
        join_pkt = {
            "t": "join",
            "code": code,
            "name": my_name,
            "id": my_id,
            "car_type": _game_setup["selected_car"]
        }
        sock.send(json.dumps(join_pkt).encode("utf-8"))
        
        # Wait briefly for server confirmation
        join_ok_received = False
        timeout = time.time() + 1.0
        while time.time() < timeout:
            for msg in recv_jsons(sock):
                if msg.get("t") == "join_ok":
                    join_ok_received = True
                    # Extract host_name from relay response
                    host_name = msg.get("host_name", "Host")
                    break
                if msg.get("t") == "error":
                    error = msg.get("msg", "relay error")
                    raise Exception(error)
            if join_ok_received:
                break
            time.sleep(0.02)
        
        if not join_ok_received:
            # Relay didn't confirm; fall back to offline mode
            try:
                sock.close()
            except Exception:
                pass
            sock = None
            code = "Offline"
            is_host = False
        
    except Exception as e:
        # Handle specific error cases
        error = str(e)
        print(f"Failed to join game: {error}")
        try:
            if sock:
                sock.close()
        except Exception:
            pass
        sock = None
        
        # If room not found, return error instead of falling back to offline
        if "room_not_found" in error:
            return ("lobby", my_name, "", None, False, "Host", error)
        # For other errors (relay unreachable, etc), fall back to offline mode
        code = "Offline"
        is_host = False

    # Invalidate UI text cache when room code changes
    invalidate_ui_text_cache('room')
    return ("game", my_name, code, sock, is_host, host_name, error)

def draw_settings(ui_surf, world_surf, world_size, buttons, stage_path, font_small=None):    
    # Draw buttons and handle their state
    button_results = []
    for button in buttons:
        try:
            if hasattr(button, 'action'):
                # Update button text based on current state
                action_name = button.action.__name__ if hasattr(button.action, '__name__') else str(button.action)
                if 'cursor_follow' in action_name.lower():
                    if const.CURSOR_FOLLOW:
                        button.text = "Mouse Following : On"
                        button.color = const.GREEN
                    else:
                        button.text = "Mouse Following : Off"
                        button.color = const.RED
                elif 'ai_path' in action_name.lower():
                    if const.AI_PATH_FOLLOW:
                        button.text = "AI Path Mode : On"
                        button.color = const.GREEN
                    else:
                        button.text = "AI Path Mode : Off"
                        button.color = const.RED
        except Exception: 
            pass
        
        res = button.draw(ui_surf, stage_path)
        if res is not None:
            button_results.append(res)
    
    # Draw STEER_BIAS slider
    if font_small is not None:
        # Initialize slider if not already done
        if 'steer_bias' not in settings_manager.sliders:
            slider_x = const.WINDOW_WIDTH // 2 - 100
            slider_y = const.WINDOW_HEIGHT * 0.75  # Position below buttons
            slider = Slider(
                x=slider_x, y=slider_y, width=200, height=30,
                min_val=0.5, max_val=1.5, current_val=const.STEER_BIAS,
                label="Steer Bias:", font=font_small
            )
            settings_manager.add_slider('steer_bias', slider)
        
        # Draw the slider
        settings_manager.draw_sliders(ui_surf)

    return world_surf, button_results

def draw_key_binds(ui_surf, font_small):
    """Draw key binds configuration page with dynamic layout.
    
    Returns:
        dict: Rectangles for click detection {bind_name: rect}
    """
    # Define key bindings to display (order matters for UI)
    key_binds = [
        ("UP_KEY", "Accelerate"),
        ("DOWN_KEY", "Reverse"),
        ("LEFT_KEY", "Steer Left"),
        ("RIGHT_KEY", "Steer Right"),
        ("BRAKE_KEY", "Handbrake"),
        ("RESET_KEY", "Reset Car"),
        ("CHANGE_CAR_KEY", "Change Car"),
    ]
    
    total_btn = len(key_binds)
    
    # Layout calculations
    center_x = const.WINDOW_WIDTH // 2
    label_width = 150
    key_box_width = 120
    key_box_height = 40
    spacing_x = 15  # Space between label and key box
    column_spacing = 60  # Space between two columns
    
    # Calculate vertical spacing to distribute button rows evenly
    # Leave margin at top and bottom
    top_margin = const.WINDOW_HEIGHT * 0.3
    bottom_margin = const.WINDOW_HEIGHT * 0.3
    available_height = const.WINDOW_HEIGHT - top_margin - bottom_margin
    
    # Calculate number of rows (2 items per row)
    num_rows = (total_btn + 1) // 2  # Ceiling division
    
    # Space between each key bind row
    if num_rows > 1:
        row_spacing = available_height / (num_rows - 1)
    else:
        row_spacing = 0
    
    # Calculate width of one column (label + spacing + key box)
    column_width = label_width + spacing_x + key_box_width
    
    # Store rects for click detection
    bind_rects = {}
    
    for idx, (bind_name, bind_label) in enumerate(key_binds):
        row = idx // 2  # Which row (0, 1, 2, ...)
        col = idx % 2   # Which column (0 = left, 1 = right)
        
        y = int(top_margin + row * row_spacing)
        
        # Calculate x position for this column
        if col == 0:
            # Left column
            label_x = center_x - column_width - column_spacing // 2
        else:
            # Right column
            label_x = center_x + column_spacing // 2
        
        # Get current key value from const
        current_value = getattr(const, bind_name, pygame.K_UNKNOWN)
        
        # Handle list of keys (like UP_KEY = [K_UP, K_z])
        # Display the second element (index 1) for list keys
        if isinstance(current_value, list):
            current_key = current_value[1] if len(current_value) > 1 else pygame.K_UNKNOWN
        else:
            current_key = current_value
        
        # Get key name
        if _key_binds_state["waiting_for_key"] == bind_name:
            key_text = "Press a key..."
            key_color = (255, 200, 100)  # Orange when waiting
        else:
            key_text = pygame.key.name(current_key).upper()
            key_color = (80, 80, 90)  # Grey color
        
        # Draw label (action description)
        label_surf = get_cached_text(font_small, bind_label, const.WHITE_240,
                                     cache_key=("key_binds", "label", bind_label))
        ui_surf.blit(label_surf, (label_x, y + (key_box_height - label_surf.get_height()) // 2))
        
        # Draw key box (clickable rect)
        key_box_x = label_x + label_width + spacing_x
        key_box_rect = pygame.Rect(key_box_x, y, key_box_width, key_box_height)
        
        # Highlight if selected/hovered
        if _key_binds_state["selected_bind"] == bind_name or _key_binds_state["waiting_for_key"] == bind_name:
            pygame.draw.rect(ui_surf, (100, 200, 100), key_box_rect, 3)  # Green border
        else:
            pygame.draw.rect(ui_surf, key_color, key_box_rect)
            pygame.draw.rect(ui_surf, const.GREY_180, key_box_rect, 2)  # Border
        
        # Draw key text (always white)
        key_surf = get_cached_text(font_small, key_text, const.WHITE_240,
                                   cache_key=("key_binds", "key", bind_name, key_text))
        ui_surf.blit(key_surf, (key_box_rect.centerx - key_surf.get_width() // 2,
                                key_box_rect.centery - key_surf.get_height() // 2))
        
        # Store rect for click detection
        bind_rects[bind_name] = key_box_rect
    
    return bind_rects

def handle_key_binds_click(click_pos, bind_rects):
    """Handle mouse clicks on key bind rectangles.
    
    Args:
        click_pos: (x, y) tuple of click position
        bind_rects: dict of {bind_name: rect} from draw_key_binds
    
    Returns:
        str: The bind name that was clicked, or None
    """
    for bind_name, rect in bind_rects.items():
        if rect.collidepoint(click_pos):
            # Start waiting for new key input
            _key_binds_state["waiting_for_key"] = bind_name
            _key_binds_state["selected_bind"] = bind_name
            invalidate_ui_text_cache('all')  # Clear cache to update UI
            return bind_name
    return None

def handle_key_binds_keypress(event):
    """Handle keyboard input for key binds configuration.
    
    Args:
        event: pygame.KEYDOWN event
    
    Returns:
        str: "saved" if changes were saved, "back" if escape pressed, None otherwise
    """
    # Check if we're waiting for a key to rebind
    if _key_binds_state["waiting_for_key"]:
        bind_name = _key_binds_state["waiting_for_key"]
        
        # Escape cancels the rebind
        if event.key == pygame.K_ESCAPE:
            _key_binds_state["waiting_for_key"] = None
            _key_binds_state["selected_bind"] = None
            invalidate_ui_text_cache('all')
            return "back"
        
        # Get current value from const
        current_value = getattr(const, bind_name, None)
        
        # Update the key binding
        # If it's a list, update list[1] only
        if isinstance(current_value, list):
            # Keep index 0, update index 1
            new_list = [current_value[0], event.key]
            if len(current_value) > 2:
                # Preserve any additional elements
                new_list.extend(current_value[2:])
            setattr(const, bind_name, new_list)
        else:
            # Single key, replace directly
            setattr(const, bind_name, event.key)
        
        # Clear waiting state and auto-save
        _key_binds_state["waiting_for_key"] = None
        _key_binds_state["selected_bind"] = None
        invalidate_ui_text_cache('all')  # Clear cache to show new key
        return "saved"
    
    # If not waiting for key, Escape exits to settings menu
    if event.key == pygame.K_ESCAPE:
        return "back"
    
    return None