import pygame, json, time, math
from drift.config.const import AVAILABLE_CARS
import drift.config.const as const
from drift.render.map_chunks import ChunkedMap
from drift.render.map_chunks import ChunkedMap
from drift.ui.ui_helpers import invalidate_ui_text_cache, get_cached_text
from drift.ui.button import Button
from drift.core.helpers import rand_code
from drift.net.communication import connect_to_relay, recv_jsons
from drift.ui.slider import Slider
from drift.config.settings import settings_manager
from drift.tools.paths import asset_path, normalize_asset_path

# Game setup state (shared across new_game and join_game UI)
_game_setup = {
    "username": "",
    "username_active": False,
    "selected_car": "ae86",  # Default car
    "selected_track": "track1",  # Default track
    "selected_mode": "mode1",  # Default mode
    "room_code": "",  # For join game
    "code_active": False,  # For join game code input
    "error_message": None,  # For displaying errors
}

# Key binds state
_key_binds_state = {
    "waiting_for_key": None,  # Which bind is waiting for input (e.g., "UP_KEY")
    "selected_bind": None,  # Currently selected/hovered bind
    "selected_gamepad": None,  # Index of the active/connected gamepad
    "active_joystick_object": None,  # Active pygame joystick object selected from UI
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

def draw_game(ui_surf, font_big, font_medium, is_host):
    """Draw the game lobby/waiting room with start button (host only)."""
    
    btn_width = const.BTN_WIDTH
    btn_height = const.BTN_HEIGHT
    center_x = const.WINDOW_WIDTH // 2
    
    # Start button (bottom center) - only if host
    if is_host:
        start_btn_y = const.WINDOW_HEIGHT - 150  # Bottom area
        start_btn = Button("Start Game", center_x - btn_width // 2, start_btn_y, btn_width, btn_height, const.GREEN, ["game"])
        start_btn.draw(ui_surf, "game")
        
        return {"start_btn": start_btn.rect}
    
    return {}

def draw_mode1(ui_surf, font_big, font_medium, cam, cp_rects=[]):
    # screen dimensions for culling
    if not cp_rects:
        return {}
    
    screen_rect = ui_surf.get_rect()
    
    # draw checkpoints
    for rect in cp_rects:
        # Transform world coordinates to screen coordinates
        # using the camera's offset and zoom
        # The camera center is at cam.x, cam.y
        # Screen center is at const.WINDOW_WIDTH // 2, const.WINDOW_HEIGHT // 2
        
        # Calculate position relative to camera center
        rel_x = rect.x - cam.x
        rel_y = rect.y - cam.y
        
        # Scale by zoom and offset by screen center
        screen_x = int(rel_x * cam.zoom + const.WINDOW_WIDTH / 2)
        screen_y = int(rel_y * cam.zoom + const.WINDOW_HEIGHT / 2)
        
        width = int(rect.width * cam.zoom)
        height = int(rect.height * cam.zoom)
        
        draw_rect = pygame.Rect(screen_x, screen_y, width, height)
        
        # Draw only if visible on screen (culling)
        if screen_rect.colliderect(draw_rect):
            pygame.draw.rect(ui_surf, (0, 255, 0), draw_rect, 2)
            
            # Optional: Draw label ID
            # label = font_medium.render(str(cp_rects.index(rect)), True, const.WHITE_240)
            # ui_surf.blit(label, draw_rect.center)

    return {}

def draw_mode2(ui_surf, font_big, font_medium, cam, cp_rects=[]):
    # screen dimensions for culling
    if not cp_rects:
        return {}
    
    screen_rect = ui_surf.get_rect()
    
    # draw checkpoints
    for rect in cp_rects:
        # Transform world coordinates to screen coordinates
        # using the camera's offset and zoom
        # The camera center is at cam.x, cam.y
        # Screen center is at const.WINDOW_WIDTH // 2, const.WINDOW_HEIGHT // 2
        
        # Calculate position relative to camera center
        rel_x = rect.x - cam.x
        rel_y = rect.y - cam.y
        
        # Scale by zoom and offset by screen center
        screen_x = int(rel_x * cam.zoom + const.WINDOW_WIDTH / 2)
        screen_y = int(rel_y * cam.zoom + const.WINDOW_HEIGHT / 2)
        
        width = int(rect.width * cam.zoom)
        height = int(rect.height * cam.zoom)
        
        draw_rect = pygame.Rect(screen_x, screen_y, width, height)
        
        # Draw only if visible on screen (culling)
        if screen_rect.colliderect(draw_rect):
            pygame.draw.rect(ui_surf, (0, 255, 0), draw_rect, 2)
            
            # Optional: Draw label ID
            # label = font_medium.render(str(cp_rects.index(rect)), True, const.WHITE_240)
            # ui_surf.blit(label, draw_rect.center)

    return {}

def draw_error(ui_surf, error_msg, font_small):
    msg = font_small.render(error_msg, True, (255,200,200))
    ui_surf.blit(msg, (const.WINDOW_WIDTH//2 - msg.get_width()//2, const.WINDOW_HEIGHT//2))
    tip = font_small.render("Press R to restart", True, const.GREY_200)
    ui_surf.blit(tip, (const.WINDOW_WIDTH//2 - tip.get_width()//2, const.WINDOW_HEIGHT//2 + 40))

def _draw_rotating_car(ui_surf, car_id, rect, font_medium, car_sprites_cache, rotation_angle):
    """Helper to draw a rotating car sprite and its text centered in a given rect."""
    # draw cars' sprites
    if car_sprites_cache and car_id in car_sprites_cache:
        sprites = car_sprites_cache[car_id]
        if sprites:
            main_sprite = sprites[1] if len(sprites) > 1 else sprites[0]
            if main_sprite:
                show_angle = (-rotation_angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
                sprite_index = round(show_angle * 64) % 64
                sprite = main_sprite[sprite_index]
                
                sprite_x = rect.centerx - sprite.get_width() // 2
                sprite_y = rect.y + 20  # Padding from top
                ui_surf.blit(sprite, (sprite_x, sprite_y))
    
    # draw car's name
    manufacturer, model = _load_car_specs(car_id)
    text_surf = font_medium.render(f"{manufacturer} {model}", True, const.WHITE_240)
    text_x = rect.centerx - text_surf.get_width() // 2
    text_y = rect.top + text_surf.get_height() - 5
    ui_surf.blit(text_surf, (text_x, text_y))

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
    
    # dimension
    car_spacing = 30
    car_btn_width = (btn_width - car_spacing) // 2
    car_btn_height = btn_height + 40  # Extra height for car sprite and manufacturer text
    sidebar_width = 40
    total_width = car_btn_width + sidebar_width
    start_x = center_x - total_width // 2
    car_box_y = y + 35
    
    # Get current car index
    selected_car = _game_setup.get("selected_car", AVAILABLE_CARS[0])
    try: current_index = AVAILABLE_CARS.index(selected_car)
    except ValueError: current_index = 0

    # 1. Main Display Box (Green Border)
    main_car_rect = pygame.Rect(start_x, car_box_y, car_btn_width, car_btn_height)
    pygame.draw.rect(ui_surf, const.GREEN, main_car_rect, 2)
    
    # Use the helper to draw the rotating car inside the centered box
    _draw_rotating_car(ui_surf, selected_car, main_car_rect, font_medium, car_sprites_cache, _car_rotation_angle)

    # 2. Sidebar Layout (White Borders) attached to the right edge
    sidebar_x = main_car_rect.right
    section_height = car_btn_height // 3
    
    # Define the 3 clickable/display zones
    up_rect = pygame.Rect(sidebar_x, car_box_y, sidebar_width, section_height)
    # Middle rect takes remaining height to ensure it perfectly aligns with the bottom
    counter_rect = pygame.Rect(sidebar_x, car_box_y + section_height, sidebar_width, car_btn_height - 2 * section_height)
    down_rect = pygame.Rect(sidebar_x, main_car_rect.bottom - section_height, sidebar_width, section_height)
    
    # Draw Sidebar outlines
    pygame.draw.rect(ui_surf, const.WHITE_240, up_rect, 2)
    pygame.draw.rect(ui_surf, const.WHITE_240, counter_rect, 2)
    pygame.draw.rect(ui_surf, const.WHITE_240, down_rect, 2)
    
    # Draw Up Arrow (^)
    arrow_offset_x = 8
    arrow_offset_y = 6
    pygame.draw.lines(ui_surf, const.WHITE_240, False, [
        (up_rect.centerx - arrow_offset_x, up_rect.centery + arrow_offset_y),
        (up_rect.centerx, up_rect.centery - arrow_offset_y),
        (up_rect.centerx + arrow_offset_x, up_rect.centery + arrow_offset_y)
    ], 2)
    
    # Draw Down Arrow (v)
    pygame.draw.lines(ui_surf, const.WHITE_240, False, [
        (down_rect.centerx - arrow_offset_x, down_rect.centery - arrow_offset_y),
        (down_rect.centerx, down_rect.centery + arrow_offset_y),
        (down_rect.centerx + arrow_offset_x, down_rect.centery - arrow_offset_y)
    ], 2)
    
    # Draw Counter Text
    counter_text = font_medium.render(f"{current_index + 1}/{len(AVAILABLE_CARS)}", True, const.WHITE_240)
    ui_surf.blit(counter_text, (counter_rect.centerx - counter_text.get_width() // 2, 
                                counter_rect.centery - counter_text.get_height() // 2))

    # Track selection section
    y += spacing + 75  # Extra space to account for taller car buttons
    label = font_medium.render("Track", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))
    
    # Track buttons - two side by side
    track_spacing = 20
    track_btn_width = (btn_width - track_spacing) // 2
    track1_rect = pygame.Rect(center_x - btn_width // 2, y + 35, track_btn_width, btn_height)
    track2_rect = pygame.Rect(center_x - btn_width // 2 + track_btn_width + track_spacing, y + 35, track_btn_width, btn_height)
    
    track1_color = const.GREEN if _game_setup["selected_track"] == "track1" else (80, 80, 90)
    track2_color = const.GREEN if _game_setup["selected_track"] == "track2" else (80, 80, 90)
    
    pygame.draw.rect(ui_surf, track1_color, track1_rect, 2)
    pygame.draw.rect(ui_surf, track2_color, track2_rect, 2)

    track1_text = font_medium.render("Acre Fields", True, const.WHITE_240)
    ui_surf.blit(track1_text, (track1_rect.centerx - track1_text.get_width() // 2, 
                               track1_rect.centery - track1_text.get_height() // 2))
    
    track2_text = font_medium.render("Beta Center", True, const.WHITE_240)
    ui_surf.blit(track2_text, (track2_rect.centerx - track2_text.get_width() // 2, 
                               track2_rect.centery - track2_text.get_height() // 2))
    
    # Mode selection section
    y += spacing + 35
    label = font_medium.render("Mode", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))

    # Mode buttons - two side by side
    mode_spacing = 20
    mode_btn_width = (btn_width - mode_spacing) // 2
    mode1_rect = pygame.Rect(center_x - btn_width // 2, y + 35, mode_btn_width, btn_height)
    mode2_rect = pygame.Rect(center_x - btn_width // 2 + mode_btn_width + mode_spacing, y + 35, mode_btn_width, btn_height)
    
    mode1_color = const.GREEN if _game_setup["selected_mode"] == "mode1" else (80, 80, 90)
    mode2_color = const.GREEN if _game_setup["selected_mode"] == "mode2" else (80, 80, 90)
    
    pygame.draw.rect(ui_surf, mode1_color, mode1_rect, 2)
    pygame.draw.rect(ui_surf, mode2_color, mode2_rect, 2)

    mode1_text = font_medium.render("Classic Race", True, const.WHITE_240)
    ui_surf.blit(mode1_text, (mode1_rect.centerx - mode1_text.get_width() // 2, 
                              mode1_rect.centery - mode1_text.get_height() // 2))
    
    mode2_text = font_medium.render("Coming Soon", True, const.WHITE_240)
    ui_surf.blit(mode2_text, (mode2_rect.centerx - mode2_text.get_width() // 2, 
                              mode2_rect.centery - mode2_text.get_height() // 2))

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
        "car_up_btn": up_rect,
        "car_down_btn": down_rect,
        "track1_btn": track1_rect,
        "track2_btn": track2_rect,
        "mode1_btn": mode1_rect,
        "mode2_btn": mode2_rect,
        "host_btn": host_btn_rect,
    }

def draw_join_game(ui_surf, font_big, font_medium, car_sprites_cache=None, dt=0.016):
    _update_car_rotation(dt)
    ui_surf.fill(const.GREY_20)
    
    # scales
    btn_width = const.BTN_WIDTH
    btn_height = const.BTN_HEIGHT
    center_x = const.WINDOW_WIDTH // 2    
    y_start = const.WINDOW_HEIGHT * 0.08
    spacing = btn_height + 30
    
    # --- Username section ---
    y = y_start
    label = font_medium.render("Username", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))
    
    input_box_rect = pygame.Rect(center_x - btn_width // 2, y + 35, btn_width, btn_height)
    input_color = (100, 200, 100) if _game_setup["username_active"] else (80, 80, 90)
    pygame.draw.rect(ui_surf, input_color, input_box_rect, 2)
    
    if _game_setup["username"]:
        username_surf = font_medium.render(_game_setup["username"], True, const.WHITE_240)
        ui_surf.blit(username_surf, (input_box_rect.centerx - username_surf.get_width() // 2, 
                                      input_box_rect.centery - username_surf.get_height() // 2))
    
    # --- Car section ---
    y += spacing + 35
    label = font_medium.render("Car", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))
    
    # dimension
    car_spacing = 30
    car_btn_width = (btn_width - car_spacing) // 2
    car_btn_height = btn_height + 40  # Extra height for car sprite and manufacturer text
    sidebar_width = 40
    total_width = car_btn_width + sidebar_width
    start_x = center_x - total_width // 2
    car_box_y = y + 35
    
    # Get current car index
    selected_car = _game_setup.get("selected_car", AVAILABLE_CARS[0])
    try: current_index = AVAILABLE_CARS.index(selected_car)
    except ValueError: current_index = 0

    # 1. Main Display Box (Green Border)
    main_car_rect = pygame.Rect(start_x, car_box_y, car_btn_width, car_btn_height)
    pygame.draw.rect(ui_surf, const.GREEN, main_car_rect, 2)
    
    # Use the helper to draw the rotating car inside the centered box
    _draw_rotating_car(ui_surf, selected_car, main_car_rect, font_medium, car_sprites_cache, _car_rotation_angle)

    # 2. Sidebar Layout (White Borders) attached to the right edge
    sidebar_x = main_car_rect.right
    section_height = car_btn_height // 3
    
    # Define the 3 clickable/display zones
    up_rect = pygame.Rect(sidebar_x, car_box_y, sidebar_width, section_height)
    # Middle rect takes remaining height to ensure it perfectly aligns with the bottom
    counter_rect = pygame.Rect(sidebar_x, car_box_y + section_height, sidebar_width, car_btn_height - 2 * section_height)
    down_rect = pygame.Rect(sidebar_x, main_car_rect.bottom - section_height, sidebar_width, section_height)
    
    # Draw Sidebar outlines
    pygame.draw.rect(ui_surf, const.WHITE_240, up_rect, 2)
    pygame.draw.rect(ui_surf, const.WHITE_240, counter_rect, 2)
    pygame.draw.rect(ui_surf, const.WHITE_240, down_rect, 2)
    
    # Draw Up Arrow (^) - Scaled down slightly for the smaller box
    arrow_offset_x = 8
    arrow_offset_y = 6
    pygame.draw.lines(ui_surf, const.WHITE_240, False, [
        (up_rect.centerx - arrow_offset_x, up_rect.centery + arrow_offset_y),
        (up_rect.centerx, up_rect.centery - arrow_offset_y),
        (up_rect.centerx + arrow_offset_x, up_rect.centery + arrow_offset_y)
    ], 2)
    
    # Draw Down Arrow (v)
    pygame.draw.lines(ui_surf, const.WHITE_240, False, [
        (down_rect.centerx - arrow_offset_x, down_rect.centery - arrow_offset_y),
        (down_rect.centerx, down_rect.centery + arrow_offset_y),
        (down_rect.centerx + arrow_offset_x, down_rect.centery - arrow_offset_y)
    ], 2)
    
    # Draw Counter Text
    counter_text = font_medium.render(f"{current_index + 1}/{len(AVAILABLE_CARS)}", True, const.WHITE_240)
    ui_surf.blit(counter_text, (counter_rect.centerx - counter_text.get_width() // 2, 
                                counter_rect.centery - counter_text.get_height() // 2))

    # Add the buttons to the rects dictionary so we can click them later
    rects_to_return = {
        "username_box": input_box_rect,
        "car_up_btn": up_rect,
        "car_down_btn": down_rect
        # (Make sure to include your other existing return rects here!)
    }

    
    # Code section
    y += spacing + 75
    label = font_medium.render("Room Code", True, const.WHITE_240)
    ui_surf.blit(label, (center_x - label.get_width() // 2, y))
    
    # Code input box
    code_box_rect = pygame.Rect(center_x - btn_width // 2, y + 35, btn_width, btn_height)
    code_color = (100, 200, 100) if _game_setup.get("code_active", False) else (80, 80, 90)
    pygame.draw.rect(ui_surf, code_color, code_box_rect, 2)
    rects_to_return["code_box"] = code_box_rect
    
    # Code text (only show if code exists, no placeholder)
    if _game_setup.get("room_code", ""):
        code_surf = font_medium.render(_game_setup["room_code"], True, const.WHITE_240)
        ui_surf.blit(code_surf, (code_box_rect.centerx - code_surf.get_width() // 2, 
                                  code_box_rect.centery - code_surf.get_height() // 2))
    
    # Join Game button
    y += spacing + 50
    join_btn_rect = pygame.Rect(center_x - btn_width // 2, y, btn_width, btn_height)
    pygame.draw.rect(ui_surf, const.GREEN, join_btn_rect)
    rects_to_return["join_btn"] = join_btn_rect
    
    join_text = font_big.render("Join", True, const.WHITE_240)
    ui_surf.blit(join_text, (join_btn_rect.centerx - join_text.get_width() // 2, 
                              join_btn_rect.centery - join_text.get_height() // 2))
    
    # Error message
    y += btn_height + 10
    if _game_setup["error_message"]:
        error_surf = font_medium.render(_game_setup["error_message"], True, (255, 100, 100))
        ui_surf.blit(error_surf, (center_x - error_surf.get_width() // 2, y))
    
    return rects_to_return

def handle_new_game_click(click_pos, rects):
    """Handle mouse clicks on new game UI elements."""
    if "username_box" in rects and rects["username_box"].collidepoint(click_pos):
        _game_setup["username_active"] = True
        _game_setup["code_active"] = False
        return "username_clicked"
    elif "track1_btn" in rects and rects["track1_btn"].collidepoint(click_pos):
        _game_setup["selected_track"] = "track1"
        return "track1_selected"
    elif "track2_btn" in rects and rects["track2_btn"].collidepoint(click_pos):
        _game_setup["selected_track"] = "track2"
        return "track2_selected"
    elif "mode1_btn" in rects and rects["mode1_btn"].collidepoint(click_pos):
        _game_setup["selected_mode"] = "mode1"
        return "mode1_selected"
    elif "mode2_btn" in rects and rects["mode2_btn"].collidepoint(click_pos):
        _game_setup["selected_mode"] = "mode2"
        return "mode2_selected"
    elif "host_btn" in rects and rects["host_btn"].collidepoint(click_pos):
        return "host_game"
    # car selection
    current_car = _game_setup.get("selected_car", AVAILABLE_CARS[0])
    current_idx = AVAILABLE_CARS.index(current_car) if current_car in AVAILABLE_CARS else 0
    if "car_up_btn" in rects and rects["car_up_btn"].collidepoint(click_pos):
        new_idx = (current_idx - 1) % len(AVAILABLE_CARS)
        _game_setup["selected_car"] = AVAILABLE_CARS[new_idx]
        return "car_changed"
    elif "car_down_btn" in rects and rects["car_down_btn"].collidepoint(click_pos):
        new_idx = (current_idx + 1) % len(AVAILABLE_CARS)
        _game_setup["selected_car"] = AVAILABLE_CARS[new_idx]
        return "car_changed"
    return None

def handle_join_game_click(click_pos, rects):
    """Handle mouse clicks on join game UI elements."""
    # username box
    if "username_box" in rects and rects["username_box"].collidepoint(click_pos):
        _game_setup["username_active"] = True
        _game_setup["code_active"] = False
        return "username_clicked"
    # code box
    elif "code_box" in rects and rects["code_box"].collidepoint(click_pos):
        _game_setup["code_active"] = True
        _game_setup["username_active"] = False
        return "code_clicked"
    # join button
    elif "join_btn" in rects and rects["join_btn"].collidepoint(click_pos):
        return "join_game"
    # car selection
    current_car = _game_setup.get("selected_car", AVAILABLE_CARS[0])
    current_idx = AVAILABLE_CARS.index(current_car) if current_car in AVAILABLE_CARS else 0
    if "car_up_btn" in rects and rects["car_up_btn"].collidepoint(click_pos):
        new_idx = (current_idx - 1) % len(AVAILABLE_CARS)
        _game_setup["selected_car"] = AVAILABLE_CARS[new_idx]
        return "car_changed"
    elif "car_down_btn" in rects and rects["car_down_btn"].collidepoint(click_pos):
        new_idx = (current_idx + 1) % len(AVAILABLE_CARS)
        _game_setup["selected_car"] = AVAILABLE_CARS[new_idx]
        return "car_changed"
    
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
    _game_setup["selected_mode"] = "mode1"
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
    
    my_name = _game_setup["username"] or "Player_" + str(my_id)[:4]
    code = rand_code()
    sock = None
    is_host = True
    host_name = my_name  # When hosting, you are the host
    track_image, chunked_map = None, None
    
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

    try: const.MAP_NUM = int(_game_setup["selected_track"][5:]) 
    except Exception: pass
    track_image = pygame.image.load(normalize_asset_path("track", f"map{const.MAP_NUM}", "main.png")).convert()
    chunked_map = ChunkedMap(root=normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=const.TILE_SIZE)
    
    _cp_rects = []
    meta_path = asset_path("track", f"map{const.MAP_NUM}", "map_meta.json")
    try:
        with open(meta_path, "r", encoding="utf-8") as fh: meta = json.load(fh)
        checkpoints = meta.get("checkpoints", {})
        for cp in checkpoints:
            rect = pygame.Rect(cp.get("x", 0), cp.get("y", 0), cp.get("width", 0), cp.get("height", 0))
            _cp_rects.append(rect)
    except Exception as e: print(f"Error reading map metadata: {e}")

    # Invalidate UI text cache when room code changes
    invalidate_ui_text_cache('room')
    return ("game", my_name, code, sock, is_host, host_name, track_image, chunked_map, _cp_rects)

def join_new_game(my_id):
    """
    Join an existing game with the configured settings.
    Returns: (stage1, my_name, code, sock, is_host, host_name) tuple
    """    
    my_name = _game_setup["username"] or "Player_" + str(my_id)[:4]
    code = _game_setup["room_code"].upper() if _game_setup["room_code"] else ""
    sock = None
    is_host = False
    host_name = "Host"  # Default if not received
    error = None
    track_image, chunked_map = None, None
    
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
                    # Extract host_name and track from relay response
                    host_name = msg.get("host_name", "Host")
                    server_track = msg.get("track")
                    if server_track:
                        _game_setup["selected_track"] = server_track
                    break
                if msg.get("t") == "error":
                    error = msg.get("msg", "relay error")
                    raise Exception(error)
            if join_ok_received:
                break
            time.sleep(0.02)
        
        if not join_ok_received:
            # Relay didn't confirm; keep user in lobby with explicit error
            try:
                sock.close()
            except Exception:
                pass
            return ("lobby", my_name, "", None, False, "Host", "join_timeout", None, None, [])
        
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

        # Join failures should not silently create an offline room/session.
        return ("lobby", my_name, "", None, False, "Host", error, None, None, [])

    try: const.MAP_NUM = int(_game_setup["selected_track"][5:]) 
    except Exception: pass
    track_image = pygame.image.load(normalize_asset_path("track", f"map{const.MAP_NUM}", "main.png")).convert()
    chunked_map = ChunkedMap(root=normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=const.TILE_SIZE)
    
    _cp_rects = []
    meta_path = asset_path("track", f"map{const.MAP_NUM}", "map_meta.json")
    try:
        with open(meta_path, "r", encoding="utf-8") as fh: meta = json.load(fh)
        checkpoints = meta.get("checkpoints", [])
        for cp in checkpoints:
            rect = pygame.Rect(cp.get("x", 0), cp.get("y", 0), cp.get("width", 0), cp.get("height", 0))
            _cp_rects.append(rect)
    except Exception as e: print(f"Error reading map metadata: {e}")

    # Invalidate UI text cache when room code changes
    invalidate_ui_text_cache('room')
    return ("game", my_name, code, sock, is_host, host_name, error, track_image, chunked_map, _cp_rects)

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
        dict: Rectangles for click detection {bind_name: rect, "gp_0": rect, ...}
    """
    # list every gamepad connected to the hardware
    count = pygame.joystick.get_count()
    joysticks = [pygame.joystick.Joystick(i) for i in range(count)]

    # Display connected gamepads at the top
    center_x = const.WINDOW_WIDTH // 2
    gp_y = int(const.WINDOW_HEIGHT * 0.08)
    gp_row_height = font_small.get_height() + 8
    gp_rects = {}  # {"gp_0": rect, "gp_1": rect, ...}

    gp_title = get_cached_text(font_small, f"Connected Gamepads ({count})", const.WHITE_240,
                               cache_key=("key_binds", "gp_title", count))
    ui_surf.blit(gp_title, (center_x - gp_title.get_width() // 2, gp_y))

    row_y = gp_y + gp_title.get_height() + 6
    if count == 0:
        no_gp = get_cached_text(font_small, "No gamepads detected", const.GREY_180,
                                cache_key=("key_binds", "no_gp"))
        no_gp_rect = pygame.Rect(center_x - no_gp.get_width() // 2 - 8, row_y,
                                 no_gp.get_width() + 16, gp_row_height)
        pygame.draw.rect(ui_surf, (50, 50, 60), no_gp_rect)
        pygame.draw.rect(ui_surf, const.GREY_180, no_gp_rect, 1)
        ui_surf.blit(no_gp, (no_gp_rect.centerx - no_gp.get_width() // 2,
                              no_gp_rect.centery - no_gp.get_height() // 2))
        gp_rects["gp_none"] = no_gp_rect
    else:
        for i, js in enumerate(joysticks):
            is_selected = _key_binds_state["selected_gamepad"] == i
            js_label = f"[{i}]  {js.get_name()}"
            if is_selected:
                js_label += "  [connected]"
            js_text = get_cached_text(font_small, js_label, const.WHITE_240 if is_selected else const.GREY_180,
                                      cache_key=("key_binds", "gp", i, js.get_name(), is_selected))
            js_rect = pygame.Rect(center_x - js_text.get_width() // 2 - 8,
                                  row_y + i * gp_row_height + 5 * i,
                                  js_text.get_width() + 16, gp_row_height)
            bg_color = (40, 80, 40) if is_selected else (50, 50, 60)
            border_color = (100, 200, 100) if is_selected else const.GREY_180
            pygame.draw.rect(ui_surf, bg_color, js_rect)
            pygame.draw.rect(ui_surf, border_color, js_rect, 2 if is_selected else 1)
            ui_surf.blit(js_text, (js_rect.centerx - js_text.get_width() // 2,
                                   js_rect.centery - js_text.get_height() // 2))
            gp_rects[f"gp_{i}"] = js_rect

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
    
    return {**bind_rects, **gp_rects}

def handle_key_binds_click(click_pos, all_rects, gamepad):
    """Handle mouse clicks on key bind rectangles and gamepad rows.
    
    Args:
        click_pos: (x, y) tuple of click position
        all_rects: merged dict returned by draw_key_binds
        gamepad: Gamepad object
    
    Returns:
        str: The bind name clicked, "gp_connected_N" for a gamepad, or None
    """
    for name, rect in all_rects.items():
        if not rect.collidepoint(click_pos): continue
        if name.startswith("gp_") and name != "gp_none":
            idx = int(name[3:])
            gamepad.connect_gamepad(idx)
            _key_binds_state["selected_gamepad"] = idx
            invalidate_ui_text_cache('all')
            return f"gp_connected_{idx}"
        elif not name.startswith("gp_"):
            _key_binds_state["waiting_for_key"] = name
            _key_binds_state["selected_bind"] = name
            invalidate_ui_text_cache('all')
            return name
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
