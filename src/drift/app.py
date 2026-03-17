#!/usr/bin/env python3

# ======= IMPORTS =======

# global imports
import pygame, json, time, random, sys, math, uuid, argparse, threading
# local imports
from drift.tools.paths import asset_path, chdir_to_exe_folder_if_frozen, get_available_cars, normalize_asset_path
import drift.config.const as const
import drift.render.camera as camera
import drift.core.car as car
import drift.ui.button as btn
import drift.ai.path_finder as path_finder
from drift.render.renderer import WorldRenderer
from drift.core.helpers import clamp, rand_name
from drift.core.gamemode import SimpleRace
from drift.ai.ai import ai_algorithme
from drift.core.inputs import read_inputs
from drift.net.communication import connect_to_relay, handle_network_messages, send_network_state, send_ai_states, send_ping, recv_jsons
from drift.ui.ui import handle_game_events, draw_stage_ui, invalidate_ui_text_cache
from drift.core.rpm import calc_engine_rpm
from drift.audio.engine_audio import EngineAudio
from drift.render.map_chunks import ChunkedMap
from drift.core.gamepad import Gamepad

# ======= CONFIGURATION =======

chdir_to_exe_folder_if_frozen()

class AudioController(threading.Thread):
    """Separate thread for audio processing at adaptive rate for better low-end device compatibility."""
    
    def __init__(self, engine_audio, update_rate: float = 100.0):
        """Initialize audio controller thread.
        
        Args:
            engine_audio: EngineAudio instance to control
            update_rate: Updates per second (Hz) for audio processing
        """
        super().__init__(daemon=True)
        self.engine_audio = engine_audio
        self.target_update_rate = update_rate
        self.update_interval = 1.0 / update_rate
        self._running = False
        self._state_lock = threading.Lock()
        
        # Adaptive rate limiting for low-end devices
        self._performance_samples = []
        self._adaptive_rate = update_rate
        self._last_rate_adjust = 0.0
        self._rate_adjust_interval = 2.0  # Check performance every 2 seconds
        
        # Thread-safe state variables
        self._rpm = 0.0
        self._throttle = 0.0
        self._current_gear = 0
        self._drift_ratio = 0.0
        self._last_update = time.perf_counter()
        
    def set_engine_state(self, rpm: float, throttle: float, current_gear: int = 0, drift_ratio: float = 0.0):
        """Thread-safe method to update engine state from game thread."""
        with self._state_lock:
            self._rpm = float(rpm)
            self._throttle = float(throttle)
            self._current_gear = int(current_gear)
            self._drift_ratio = float(drift_ratio)
    
    def get_engine_state(self):
        """Thread-safe method to read engine state from audio thread."""
        with self._state_lock:
            return self._rpm, self._throttle, self._current_gear, self._drift_ratio
    
    def _adjust_adaptive_rate(self, processing_time: float):
        """Adjust audio update rate based on processing performance."""
        current_time = time.perf_counter()
        
        # Track processing time samples
        self._performance_samples.append(processing_time)
        if len(self._performance_samples) > 50:  # Keep last 50 samples
            self._performance_samples.pop(0)
        
        # Only adjust rate every few seconds
        if current_time - self._last_rate_adjust < self._rate_adjust_interval:
            return
            
        self._last_rate_adjust = current_time
        
        if len(self._performance_samples) < 10:
            return
            
        # Calculate average processing time
        avg_processing_time = sum(self._performance_samples) / len(self._performance_samples)
        target_frame_time = 1.0 / self._adaptive_rate
        
        # If processing takes more than 70% of frame time, reduce rate
        if avg_processing_time > target_frame_time * 0.7:
            new_rate = max(30.0, self._adaptive_rate * 0.8)  # Minimum 30 Hz
            if new_rate != self._adaptive_rate:
                self._adaptive_rate = new_rate
                self.update_interval = 1.0 / self._adaptive_rate
                # print(f"Audio rate reduced to {self._adaptive_rate:.1f} Hz due to performance")
        
        # If processing is fast, try to increase rate (but not above target)
        elif avg_processing_time < target_frame_time * 0.3:
            new_rate = min(self.target_update_rate, self._adaptive_rate * 1.1)
            if new_rate != self._adaptive_rate:
                self._adaptive_rate = new_rate
                self.update_interval = 1.0 / self._adaptive_rate
                # print(f"Audio rate increased to {self._adaptive_rate:.1f} Hz")
    
    def start_audio_thread(self):
        """Start the audio processing thread."""
        if not self._running:
            self._running = True
            self.start()
            print(f"Audio thread started at {self._adaptive_rate:.1f} Hz (adaptive)")
    
    def stop_audio_thread(self):
        """Stop the audio processing thread."""
        if self._running:
            self._running = False
            self.join(timeout=1.0)
            print("Audio thread stopped")
    
    def run(self):
        """Main audio thread loop - runs at adaptive rate for better low-end device performance."""
        last_time = time.perf_counter()
        
        while self._running:
            current_time = time.perf_counter()
            dt = current_time - last_time
            last_time = current_time
            
            # Get current engine state
            rpm, throttle, current_gear, drift_ratio = self.get_engine_state()
            
            # Update audio with measured processing time
            processing_start = time.perf_counter()
            try:
                self.engine_audio.update(rpm, throttle, dt, current_gear, drift_ratio)
            except Exception as e:
                print(f"Audio thread error: {e}")
            
            processing_time = time.perf_counter() - processing_start
            
            # Adapt update rate based on performance
            self._adjust_adaptive_rate(processing_time)
            
            # Sleep to maintain target update rate
            elapsed = time.perf_counter() - current_time
            sleep_time = max(0, self.update_interval - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

# ======= RELAY =======

RELAY_PUBLIC_ENDPOINT = const.RELAY_PUBLIC_ENDPOINT
# True : client creates a room, False : joining
I_AM_HOST = False

flags = const.FLAGS

# ======= LOADING SCREEN =======

def draw_loading_screen(screen, progress, total_steps, current_task="Loading...", gpu_display=None):
    """Draw a loading screen with circular progress bar from 7π/4 to π/4"""
    screen.fill(const.GREY_20)  # Dark background
    
    # Create fonts for loading screen
    title_font = pygame.font.SysFont(None, 72)
    task_font = pygame.font.SysFont(None, 36)
    
    # Calculate center
    center_x = const.WINDOW_WIDTH // 2
    center_y = const.WINDOW_HEIGHT // 2
    
    # Draw title
    title_text = title_font.render(f"Drift Race v{const.VERSION}", True, (255, 255, 255))
    title_rect = title_text.get_rect(center=(center_x, center_y - 100))
    screen.blit(title_text, title_rect)
    
    # Draw current task
    task_text = task_font.render(current_task, True, (200, 200, 200))
    task_rect = task_text.get_rect(center=(center_x, center_y + 80))
    screen.blit(task_text, task_rect)
    
    # Draw circular progress bar
    radius = 50
    thickness = 8
    
    # Background circle (darker)
    pygame.draw.circle(screen, (60, 60, 80), (center_x, center_y), radius, thickness)
    
    # Calculate progress angle
    # From 7π/4 (315°) to π/4 (45°) = 90° total sweep
    # 7π/4 = -π/4 in standard position
    start_angle = -5*math.pi / 4  # 7π/4 in standard position
    end_angle = math.pi / 4     # π/4
    total_sweep = end_angle - start_angle  # π/2 radians (90°)
    
    if total_steps > 0:
        progress_ratio = min(progress / total_steps, 1.0)
        
        # Draw progress arc
        if progress_ratio > 0:
            # Create points for the arc
            arc_points = []
            num_segments = max(1, int(progress_ratio * 50))  # More segments for smoother arc
            
            for i in range(num_segments + 1):
                angle = start_angle + (total_sweep * progress_ratio * i / num_segments)
                x = center_x + (radius - thickness // 2) * math.cos(angle)
                y = center_y + (radius - thickness // 2) * math.sin(angle)
                arc_points.append((x, y))
            
            # Draw the progress arc as a thick line
            if len(arc_points) > 1:
                for i in range(len(arc_points) - 1):
                    pygame.draw.line(screen, (100, 200, 255), arc_points[i], arc_points[i + 1], thickness)
    
    # Draw percentage text
    percentage = int((progress / max(total_steps, 1)) * 100)
    percent_text = task_font.render(f"{percentage}%", True, (255, 255, 255))
    percent_rect = percent_text.get_rect(center=(center_x, center_y))
    screen.blit(percent_text, percent_rect)
    
    # Present the loading screen (GPU or software path)
    if gpu_display is not None:
        try:
            gpu_display.present(screen)
        except Exception:
            pass
    else:
        pygame.display.flip()

def load_assets_with_progress(screen, clock, gpu_display=None):
    """Load all game assets with progress tracking"""
    
    # Define loading steps
    loading_steps = [
        ("Initializing audio...", "audio"),
        ("Loading car sprites...", "sprites"),
        ("Loading track data...", "track"),
        ("Initializing systems...", "systems"),
        ("Starting audio controller...", "audio_controller"),
        ("Finalizing...", "final")
    ]
    
    total_steps = len(loading_steps)
    loaded_data = {}
    
    for step, (task_name, step_key) in enumerate(loading_steps):
        # Update loading screen
        draw_loading_screen(screen, step, total_steps, task_name, gpu_display)
        clock.tick(60)  # Maintain smooth animation
        
        # Handle pygame events to prevent "not responding"
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
        
        # Perform actual loading
        if step_key == "audio":
            loaded_data["audio_initialized"] = load_audio_system()
            time.sleep(0.1)  # Small delay to show progress
            
        elif step_key == "sprites":
            loaded_data["car_sprites_cache"] = load_all_car_sprites()
            time.sleep(0.2)
            
        elif step_key == "track":
            loaded_data["track_image"] = pygame.image.load(normalize_asset_path("track", f"map{const.MAP_NUM}", "main.png")).convert()
            loaded_data["chunk_map"] = ChunkedMap(root=normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=const.TILE_SIZE)
            time.sleep(0.1)
            
        elif step_key == "systems":
            loaded_data["path_poly"] = []  # Will be initialized later
            time.sleep(0.1)
            
        elif step_key == "audio_controller":
            loaded_data["engine_sound"], loaded_data["audio_controller"] = load_audio_controller(loaded_data["audio_initialized"])

        elif step_key == "final":
            time.sleep(0.1)
    
    # Show 100% completion briefly
    draw_loading_screen(screen, total_steps, total_steps, "Complete!", gpu_display)
    pygame.time.wait(500)
    
    return loaded_data

def load_audio_system():
    """Load audio system with fallback configurations"""
    audio_configs = [
        # High quality (try first)
        {"freq": 44100, "size": -16, "channels": 2, "buffer": 1024},
        # Medium quality (fallback 1)
        {"freq": 22050, "size": -16, "channels": 2, "buffer": 2048},
        # Low quality (fallback 2 - for very low-end devices)
        {"freq": 22050, "size": -16, "channels": 1, "buffer": 4096},
    ]
    
    audio_initialized = False
    for i, config in enumerate(audio_configs):
        try:
            pygame.mixer.pre_init(
                frequency=config["freq"],
                size=config["size"], 
                channels=config["channels"], 
                buffer=config["buffer"]
            )
            pygame.mixer.init()
            print(f"Audio initialized with config {i+1}: {config['freq']}Hz, {config['channels']}ch, buffer={config['buffer']}")
            audio_initialized = True
            break
        except Exception as e:
            print(f"Audio config {i+1} failed: {e}")
            try:
                pygame.mixer.quit()
            except:
                pass
    
    if not audio_initialized:
        print("Warning: All audio configurations failed - audio will be disabled")
    
    return audio_initialized

def load_all_car_sprites():
    """Load sprites for all car types"""
    def load_car_sprites(car_type):
        """Load sprites for a specific car type."""
        if car_type not in const.CAR_SPRITES:
            car_type = "ae86"  # Default fallback
        
        car_sprites = []
        for path_template in const.CAR_SPRITES[car_type]["paths"]:
            sprite_list = []
            for i in range(64):
                try:
                    img = pygame.image.load(asset_path(path_template.format(i=i))).convert_alpha()
                    sprite_list.append(img)
                except Exception as e:
                    print(f"Warning: Could not load {path_template.format(i=i)}: {e}")
                    # Create a placeholder surface if sprite fails to load
                    placeholder = pygame.Surface((32, 32), pygame.SRCALPHA)
                    placeholder.fill((255, 0, 255, 128))  # Magenta placeholder
                    sprite_list.append(placeholder)
            car_sprites.append(sprite_list)
        return car_sprites
    
    # Load all car type sprites
    car_sprites_cache = {}
    for car_type in const.CAR_SPRITES.keys():
        car_sprites_cache[car_type] = load_car_sprites(car_type)
    
    return car_sprites_cache

def load_audio_controller(audio_initialized):
    engine_sound = None
    audio_controller = None
    try:
        if audio_initialized:
            engine_sound = EngineAudio()
            # Start with lower rate for better compatibility on low-end devices
            initial_rate = 80.0  # Reduced from 120 Hz
            audio_controller = AudioController(engine_sound, initial_rate)
            audio_controller.start_audio_thread()
            print("Threaded audio system initialized")
        else:
            print("Audio system disabled due to initialization failure")
    except Exception as e:
        print("Engine sound init failed:", e)
        engine_sound = None
        audio_controller = None

    return engine_sound, audio_controller

# ======= MAIN LOOP =======
  
def main():
    global I_AM_HOST  # ensure all references/assignments in this function use the module global
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["host", "join"])
    parser.add_argument("--code")
    parser.add_argument("--name")
    args, unknown = parser.parse_known_args()

    pygame.init()
    pygame.joystick.init()
    
    gpu_display = None
    use_gpu = True  # Set to True to enable GPU rendering with texture reuse
    
    if use_gpu:
        try:
            from drift.render.gpu_display import GPUDisplay
            gpu_display = GPUDisplay((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), f"Drift Race v{const.VERSION}")
            print("✓ GPU display initialized via pygame._sdl2")
            try:
                if hasattr(gpu_display.renderer, 'get_info'):
                    info = gpu_display.renderer.get_info()
                    print(f"  Renderer: {info.name if hasattr(info, 'name') else 'unknown'}")
            except Exception:
                pass
            screen = gpu_display.win.get_surface()
        except Exception as e:
            print(f"✗ GPU display initialization failed: {e}")
            print("  Using software rendering fallback")
            gpu_display = None
    
    if gpu_display is None:
        pygame.display.set_caption(f"Drift Race v{const.VERSION}")
        screen = pygame.display.set_mode((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
    
    clock = pygame.time.Clock()
    
    # Fullscreen state tracking
    is_fullscreen = False
    
    # Show loading screen and load assets
    loaded_assets = load_assets_with_progress(screen, clock, gpu_display)
    
    # Create fonts after pygame.init()
    font_small = pygame.font.SysFont(None, const.FONT_SMALL_SIZE)
    font_medium = pygame.font.SysFont(None, const.FONT_MEDIUM_SIZE)
    font_big = pygame.font.SysFont(None, const.FONT_BIG_SIZE)
    
    # Extract loaded assets
    audio_initialized = loaded_assets["audio_initialized"]
    car_sprites_cache = loaded_assets["car_sprites_cache"]
    track_image = loaded_assets["track_image"]
    chunked_map = loaded_assets["chunk_map"]
    engine_sound = loaded_assets["engine_sound"]
    audio_controller = loaded_assets["audio_controller"]
    
    stage1 = "lobby" # lobby | game | error | mode1 | mode2 | leaderboard
    stage2 = "" # new_game | join_game | settings
    stage3 = "" # key_binds
    error_msg = ""
    remotes = {}
    ai_cars = []
    path_poly = []
    game_mode = None           # active BaseGameMode instance (SimpleRace, etc.)
    _prev_stage1 = "lobby"     # detect stage1 transitions
    _return_btn_rect = None    # leaderboard button rect from previous frame
    _local_result_sent = False

    my_name = rand_name()
    my_id = str(uuid.uuid4())[:8]
    code = None
    sock = None
    last_state_send = 0.0
    last_ping = 0.0
    host_name = None  # Will be set when hosting or joining

    lights_on = True

    spawnx = random.uniform(const.WINDOW_WIDTH*0.3, const.WINDOW_WIDTH*0.7)
    spawny = random.uniform(const.WINDOW_HEIGHT*0.3, const.WINDOW_HEIGHT*0.7)
    my_car = car.Car(spawnx, spawny, my_name, is_ai=False, car_type="ae86")
    # Local player's engine state (avoid mutating Car which may use __slots__)
    engine_state = {"gear": 0, "last_rpm": None}

    # controller cooldowns
    ctlr_btn2_time = 0.0 # i'll store last time.time() the X button was pressed (change car)
    ctlr_btn3_time = 0.0 # same for the Y button (spawn ai car)

    if args.mode == "host" and args.code and args.name:
        my_name = args.name
        my_car.name = my_name
        code = args.code
        try:
            sock = connect_to_relay()
            join_pkt = {"t": "create", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
            # Wait briefly for confirmation; otherwise offline fallback
            join_ok_received = False
            timeout = time.time() + 1.0
            while time.time() < timeout:
                for msg in recv_jsons(sock):
                    if msg.get("t") == "join_ok":
                        join_ok_received = True
                        break
                    if msg.get("t") == "error":
                        raise Exception(msg.get("msg", "relay error"))
                if join_ok_received:
                    break
                time.sleep(0.02)
            if join_ok_received:
                stage1 = "game"
                I_AM_HOST = True  # set host flag for CLI host mode
            else:
                raise Exception("no join_ok")
        except Exception:
            # Offline fallback
            sock = None
            code = "Offline"
            stage1 = "game"
            I_AM_HOST = True
    elif args.mode == "join" and args.code and args.name:
        my_name = args.name
        my_car.name = my_name
        code = args.code
        try:
            sock = connect_to_relay()
            code = code.upper()
            join_pkt = {"t": "join", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
            # Wait briefly for confirmation; otherwise offline fallback
            join_ok_received = False
            timeout = time.time() + 1.0
            while time.time() < timeout:
                for msg in recv_jsons(sock):
                    if msg.get("t") == "join_ok":
                        join_ok_received = True
                        break
                    if msg.get("t") == "error":
                        raise Exception(msg.get("msg", "relay error"))
                if join_ok_received:
                    break
                time.sleep(0.02)
            if join_ok_received:
                stage1 = "game"
                I_AM_HOST = False  # set host flag for CLI join mode
            else:
                raise Exception("no join_ok")
        except Exception:
            # Offline fallback
            sock = None
            code = "Offline"
            stage1 = "game"
            I_AM_HOST = False
    
    # Renderer handles track, cars, and drift marks
    renderer = WorldRenderer(track_image, flags, chunked_map=chunked_map)

    # connect first available gamepad (if any)
    gp = Gamepad()
    gp.joystick = pygame.joystick.Joystick(0) if pygame.joystick.get_count() > 0 else None
    gp.selected_index = gp.joystick.get_id() if gp.joystick else None
    if gp.joystick: gp.connect_gamepad(gp.selected_index)

    # Create a camera object; mouse wheel will adjust zoom and middle mouse drag will pan.
    cam = camera.Camera(const.WINDOW_WIDTH, const.WINDOW_HEIGHT, zoom=1.0)
    dragging = False
    host_ref = [I_AM_HOST]

    def leave_room(sock, code, my_id, remotes):
        nonlocal host_name, game_mode, _prev_stage1, _return_btn_rect, _local_result_sent
        if sock and code:
            try:
                sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                sock.close()
            except Exception:
                pass
        remotes.clear()
        ai_cars.clear()
        const.AI_PATH_FOLLOW = False
        const.CURSOR_FOLLOW = False
        host_name = None
        host_ref[0] = False
        if game_mode is not None:
            game_mode.on_exit()
            game_mode = None
        _prev_stage1 = "lobby"
        _return_btn_rect = None
        _local_result_sent = False
        invalidate_ui_text_cache('room')  # Clear cached room code text
        # Clear tire marks and chunk cache to free memory
        renderer.clear_tire_marks()
        renderer.clear_chunk_cache()
        return "lobby", "", None, None, remotes # stage, substage sock, code, remotes
    
    def handle_key_binds():
        nonlocal stage3
        stage3 = "key_binds"
        
    def switch_cursor_follow_mode(stage1):
        const.CURSOR_FOLLOW = not const.CURSOR_FOLLOW
        if const.CURSOR_FOLLOW: const.AI_PATH_FOLLOW = False
        # stage, substage sock, code, remotes
        try: return stage1, "", sock, code, remotes
        except Exception: return stage1, "", None, None, {}

    def switch_ai_path_mode(stage1):
        const.AI_PATH_FOLLOW = not const.AI_PATH_FOLLOW
        if const.AI_PATH_FOLLOW: const.CURSOR_FOLLOW = False
        # stage, substage sock, code, remotes
        try: return stage1, "", sock, code, remotes
        except Exception: return stage1, "", None, None, {}

    settings_buttons = [ # todo : be able to use '*' like '*/settings' for key binds
    btn.Button("Leave Room", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.35, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, [["game", "settings"], ["mode1", "settings"], ["mode2", "settings"], ["leaderboard", "settings"]] ,lambda: leave_room(sock, code, my_id, remotes)),
    btn.Button("Key Binds", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.45, const.BTN_WIDTH, const.BTN_HEIGHT, const.BLUE, [["lobby", "settings"], ["game", "settings"], ["mode1", "settings"], ["mode2", "settings"], ["leaderboard", "settings"]], handle_key_binds),
    btn.Button("Cursor Follow Mode", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.55, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, [["mode1", "settings"], ["mode2", "settings"]], lambda: switch_cursor_follow_mode(stage1)),
    btn.Button("AI Path Mode", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.65, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, [["mode1", "settings"], ["mode2", "settings"]], lambda: switch_ai_path_mode(stage1)),
    ]
    
    # Performance debugging
    frame_count = 0
    last_debug_time = time.time()

    while True:
        dt = clock.tick(const.FPS) / 1000.0
        #dt = min(dt, 1 / const.FPS)  # Cap dt to avoid large jumps
        
        # Performance debugging - print cache sizes every 3 seconds
        frame_count += 1
        current_time = time.time()
        if current_time - last_debug_time >= 3.0:
            from drift.ui import ui_helpers
            text_cache_size = len(ui_helpers._header_footer_text_cache)
            button_cache_size = len(btn.Button._font_cache)
            chunk_cache_size = len(renderer.chunked_map._cache) if renderer and hasattr(renderer, 'chunked_map') else 0
            tire_mark_chunks = len(renderer.tire_mark_grid._marks) if renderer and hasattr(renderer, 'tire_mark_grid') else 0
            current_fps = clock.get_fps()
            # print(f"[DEBUG] FPS: {current_fps:.1f} | Text cache: {text_cache_size} | Button cache: {button_cache_size} | Chunk cache: {chunk_cache_size} | Tire marks: {tire_mark_chunks}")
            last_debug_time = current_time

        # ======== EVENT HANDLING ======== (keyboard)

        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                if sock and code:
                    try: sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                    except Exception: pass
                try:
                    if engine_sound:
                        engine_sound.stop_all()  # Stop all sounds
                    if audio_controller:
                        audio_controller.stop_audio_thread()  # Stop the audio thread
                except Exception:
                    pass
                pygame.quit()
                sys.exit(0)

            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_l: # L to toggle headlights
                lights_on = not lights_on
            if ev.type == pygame.KEYDOWN and ev.key == const.CHANGE_CAR_KEY: # C to change car
                # Cycle through available car types
                available_types = list(const.CAR_SPRITES.keys())
                current_index = available_types.index(my_car.car_type)
                next_index = (current_index + 1) % len(available_types)
                my_car.set_car_type(available_types[next_index])
            if ev.type == pygame.KEYDOWN and ev.key == const.DEBUG_TOGGLE_KEY: # F3 to toggle debug mode
                # Toggle debug mode
                const.DEBUG = not const.DEBUG
                invalidate_ui_text_cache('debug')  # Clear cached debug text
                print(f"Debug mode {'enabled' if const.DEBUG else 'disabled'}")
            if ev.type == pygame.KEYDOWN and ev.key == const.FULLSCREEN_KEY:
                # Toggle fullscreen mode
                is_fullscreen = not is_fullscreen
                if is_fullscreen:
                    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                    const.WINDOW_WIDTH, const.WINDOW_HEIGHT = screen.get_size()
                    cam.zoom = 2.0
                else:
                    const.WINDOW_WIDTH, const.WINDOW_HEIGHT = const.WINDOW_WIDTH_W, const.WINDOW_HEIGHT_W
                    screen = pygame.display.set_mode((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
                    cam.zoom = 1.0
                print(f"Fullscreen mode {'enabled' if is_fullscreen else 'disabled'}")
            if ev.type == pygame.KEYDOWN and ev.key == const.AI_KEY: # N to add AI car
                if I_AM_HOST and stage1 in ["game", "mode1", "mode2"] and stage2 == "":
                    # Randomly assign car type for AI cars
                    ai_car_type = random.choice(const.AVAILABLE_CARS)
                    ai_cars.append(
                        car.Car(
                            random.randint(const.TRACK_MARGIN + 200, const.WINDOW_WIDTH - const.TRACK_MARGIN - 200),
                            random.randint(const.TRACK_MARGIN + 120, const.WINDOW_HEIGHT - const.TRACK_MARGIN - 120),
                            name=f"AI-{len(ai_cars)+1}",
                            is_ai=True,
                            car_type=ai_car_type,
                        )
                    )
                
            if ev.type == pygame.MOUSEWHEEL:
                # Adjust zoom (clamp between 0.5 and 3.0)
                cam.zoom *= 1.1 if ev.y > 0 else 0.9
                cam.zoom = clamp(cam.zoom, 1, 3.0)
            if ev.type == pygame.MOUSEBUTTONDOWN:
                if ev.button == 2:  # Middle mouse for panning
                    dragging = True
            if ev.type == pygame.MOUSEBUTTONUP:
                if ev.button == 2:
                    dragging = False
            if ev.type == pygame.MOUSEMOTION and dragging:
                # Adjust pan offset (divide by zoom so that panning is smooth)
                cam.offset[0] -= ev.rel[0] / cam.zoom
                cam.offset[1] -= ev.rel[1] / cam.zoom

            ev, stage1, stage2, stage3, remotes, sock, code, my_car, error_msg, host_name, track_image, chunked_map, checkpoints = handle_game_events(screen, ev, stage1, stage2, stage3, gp, remotes, ai_cars, sock, code, my_name, my_id, my_car, font_big, font_small, error_msg, host_ref, host_name)
            I_AM_HOST = host_ref[0]

            # Leaderboard "Return to Lobby" button click
            if (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1
                    and stage1 == "leaderboard" and I_AM_HOST
                    and _return_btn_rect is not None
                    and _return_btn_rect.collidepoint(ev.pos)):
                # Return everyone to the waiting room
                if game_mode is not None:
                    game_mode.on_exit()
                    game_mode = None
                stage1 = "game"
                _prev_stage1 = "game"
                _return_btn_rect = None
                _local_result_sent = False
                # Teleport local player back to center
                my_car.x = const.WINDOW_WIDTH // 2
                my_car.y = const.WINDOW_HEIGHT // 2
                my_car.vx, my_car.vy = 0.0, 0.0
                # Tell remote players to return (via relay)
                if sock and code and code != "Offline":
                    try:
                        sock.send(json.dumps({
                            "t": "start_race", "code": code, "id": my_id,
                            "mode": "game"
                        }).encode("utf-8"))
                    except Exception:
                        pass

            # update map changes
            if renderer and track_image and renderer.track_image != track_image: renderer.track_image = track_image
            if renderer and chunked_map and renderer.chunked_map != chunked_map: renderer.chunked_map = chunked_map
            if renderer and checkpoints: renderer.checkpoints = checkpoints

        # ======== JOYSCTICK INPUTS HANDLING ======== (controller buttons)

        # A: button 0, B: button 1, X: button 2, Y: button 3
        # LB: button 4, RB: button 5
        # -: button 6, +: button 7
        # Left joystick: button 8 (press), Right joystick: button 9 (press)
        # Home: button 10

        if gp and gp.joystick:
            js = gp.joystick
            if js.get_button(2) and time.time() - ctlr_btn2_time > 0.2: # X to change car
                ctlr_btn2_time = time.time()
                # Cycle through available car types
                available_types = list(const.CAR_SPRITES.keys())
                current_index = available_types.index(my_car.car_type)
                next_index = (current_index + 1) % len(available_types)
                my_car.set_car_type(    available_types[next_index])
            if js.get_button(3) and time.time() - ctlr_btn3_time > 0.2: # Y to spawn ai car
                ctlr_btn3_time = time.time()
                if I_AM_HOST and stage1 in ["game", "mode1", "mode2"] and stage2 == "":
                    # Randomly assign car type for AI cars
                    ai_car_type = random.choice(const.AVAILABLE_CARS)
                    ai_cars.append(
                        car.Car(
                            random.randint(const.TRACK_MARGIN + 200, const.WINDOW_WIDTH - const.TRACK_MARGIN - 200),
                            random.randint(const.TRACK_MARGIN + 120, const.WINDOW_HEIGHT - const.TRACK_MARGIN - 120),
                            name=f"AI-{len(ai_cars)+1}",
                            is_ai=True,
                            car_type=ai_car_type,
                        )
                    )

        # ======== NETWORKING ========

        if sock:
            # print(sock)
            net_result = handle_network_messages(sock, remotes, dt, my_id, I_AM_HOST, code)
            if net_result.get("host_name") is not None:
                host_name = net_result["host_name"] or None
            if net_result.get("host_id") is not None:
                I_AM_HOST = (net_result["host_id"] == my_id)
                host_ref[0] = I_AM_HOST
            if net_result.get("start_mode") and stage1 in ["game", "mode1", "mode2", "leaderboard"]:
                new_mode = net_result["start_mode"]

                # Race start transitions are one-way from waiting room only.
                # This avoids re-applying stale/echoed starts while already racing.
                if new_mode in ["mode1", "mode2"] and stage1 != "game":
                    new_mode = None
                if new_mode is None:
                    pass
                # "game" means return to waiting room (from leaderboard)
                elif new_mode == "game":
                    if stage1 != "game":
                        if game_mode is not None:
                            game_mode.on_exit()
                            game_mode = None
                        _prev_stage1 = "game"
                        _return_btn_rect = None
                        _local_result_sent = False
                        my_car.x = const.WINDOW_WIDTH // 2
                        my_car.y = const.WINDOW_HEIGHT // 2
                        my_car.vx, my_car.vy = 0.0, 0.0
                        stage1 = new_mode
                else:
                    stage1 = new_mode
            if game_mode is not None and net_result.get("race_results"):
                game_mode.apply_network_results(net_result["race_results"])
                # Non-host: reload the correct map when race starts
                if not I_AM_HOST and net_result.get("start_track"):
                    try:
                        new_map_num = int(net_result["start_track"][5:])
                    except Exception:
                        new_map_num = 1
                    const.MAP_NUM = new_map_num
                    track_image = pygame.image.load(normalize_asset_path("track", f"map{const.MAP_NUM}", "main.png")).convert()
                    chunked_map = ChunkedMap(root=normalize_asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=const.TILE_SIZE)
                    renderer.track_image = track_image
                    renderer.chunked_map = chunked_map
            err = net_result.get("error")
            if err:
                # Switch to offline on relay errors
                try:
                    sock.close()
                except Exception:
                    pass
                sock = None
                code = "Offline"
                remotes.clear()

        if sock and code and code != "Offline":
            now = time.time()
            if now - last_state_send >= 1.0 / const.SEND_HZ:
                last_state_send = now
                send_network_state(sock, code, my_id, my_car)
                if I_AM_HOST and ai_cars:
                    send_ai_states(sock, code, ai_cars)
            if now - last_ping >= 1.0 / const.PING_HZ:
                last_ping = now
                send_ping(sock, code)

        # ======== GAME MODE LIFECYCLE ========

        # Detect stage1 transitions → initialise / tear-down game modes
        if stage1 != _prev_stage1:
            # Leaving a mode
            if _prev_stage1 in ["mode1", "mode2"] and game_mode is not None:
                if stage1 != "leaderboard":  # keep mode alive for leaderboard
                    game_mode.on_exit()
                    game_mode = None

            # Entering mode1
            if stage1 == "mode1" and game_mode is None:
                _start_grid = []
                try:
                    meta_path = asset_path("track", f"map{const.MAP_NUM}", "map_meta.json")
                    with open(meta_path, "r", encoding="utf-8") as fh:
                        _meta = json.load(fh)
                    _start_grid = _meta.get("start", []) or []
                    _lines = _meta.get("lines", []) or []
                except Exception:
                    _start_grid = []
                    _lines = []

                game_mode = SimpleRace(renderer.checkpoints or [], total_laps=1, start_grid=_start_grid, lines=_lines, local_player_id=my_id) # here to change the number of laps
                _local_result_sent = False
                # Build player dict for on_enter
                _mode_players = {my_id: {"car_type": my_car.car_type, "name": my_car.name}}
                for pid, rd in remotes.items():
                    _mode_players[pid] = {"car_type": rd.get("car_type", "ae86"), "name": rd.get("name", pid)}
                for i, ai in enumerate(ai_cars, start=1):
                    _mode_players[f"AI-{i}"] = {"car_type": ai.car_type, "name": ai.name}
                game_mode.on_enter(_mode_players)
                # Teleport all players to start line
                sorted_spawn_ids = sorted(_mode_players.keys())
                start_positions = game_mode.get_start_positions(sorted_spawn_ids)
                if my_id in start_positions:
                    sx, sy, sa = start_positions[my_id]
                    my_car.x, my_car.y, my_car.angle = sx, sy, sa
                    my_car.target_angle = sa
                    my_car.vx, my_car.vy = 0.0, 0.0
                for i, ai in enumerate(ai_cars, start=1):
                    key = f"AI-{i}"
                    if key in start_positions:
                        sx, sy, sa = start_positions[key]
                        ai.x, ai.y, ai.angle = sx, sy, sa
                        ai.target_angle = sa
                        ai.vx, ai.vy = 0.0, 0.0

            # Leaving leaderboard (return to lobby/game)
            if _prev_stage1 == "leaderboard" and game_mode is not None:
                game_mode.on_exit()
                game_mode = None

            _prev_stage1 = stage1

        # Update active game mode
        mode_result = {}
        if game_mode is not None and stage1 in ["mode1", "mode2", "leaderboard"]:
            mode_result = game_mode.update(dt, remotes, my_car, I_AM_HOST)
            local_finish_time = game_mode.get_local_finish_time()
            if (local_finish_time is not None and not _local_result_sent and sock and code and code != "Offline"):
                try:
                    sock.send(json.dumps({
                        "t": "race_result",
                        "code": code,
                        "id": my_id,
                        "time": float(local_finish_time),
                    }).encode("utf-8"))
                    _local_result_sent = True
                except Exception:
                    pass
            # Handle stage transition request (e.g. racing → leaderboard)
            if mode_result.get("stage_transition") == "leaderboard":
                stage1 = "leaderboard"
                _prev_stage1 = "leaderboard"

        # ======== FRAME UPDATE ========
        
        world_size = renderer.get_world_size(stage1 if stage1 != "leaderboard" else "mode1")

        # Skip physics computations when in menus (new_game, join_game, key_binds)
        # This saves CPU on low-end devices and improves battery life
        skip_physics = stage2 in ["new_game", "join_game"] or stage3 == "key_binds"
        
        if not skip_physics:
            movement_locked = bool(mode_result.get("movement_locked"))
            # Prepare remotes view for the player: include network remotes + AI cars (so player can collide with AIs)
            remotes_with_ai_for_player = dict(remotes)
            if I_AM_HOST:
                for i, ai in enumerate(ai_cars, start=1):
                    key = f"AI-{i}"
                    remotes_with_ai_for_player[key] = {"x": ai.x, "y": ai.y, "a": ai.angle, "drift_ratio": ai.drift_ratio, "name": ai.name}
                    
            # Update player car using remotes that include AIs
            # If AI path mode is enabled and a path is available, let the AI drive the player
            controls = None
            if const.AI_PATH_FOLLOW and path_poly:
                try:
                    controls, ai_debug_surface = ai_algorithme(path_poly, my_car, ai_path_mode=True, surface=pygame.Surface((track_image.get_width(), track_image.get_height()), pygame.SRCALPHA), font_small=font_small)
                except Exception:
                    controls = None
            if controls is None:
                controls = read_inputs(gp, my_car, cam, const.CURSOR_FOLLOW, const.AI_PATH_FOLLOW)
            # Lock movement during countdown/cooldown/leaderboard
            if movement_locked:
                controls = {"th": 0.0, "st": 0.0, "br": 0.0}
                my_car.vx, my_car.vy = 0.0, 0.0
                my_car.v_angle = 0.0
            else:
                my_car.step(controls, dt, remotes_with_ai_for_player, world_size, compute_debug=const.DEBUG)
            # Update engine audio based on RPM and throttle with enhanced drift characteristics
            try:
                if engine_sound is not None and audio_controller is not None and audio_initialized:
                    speed_units = math.hypot(my_car.vx, my_car.vy)
                    th = clamp(controls.get("th", 0.0), -1.0, 1.0)
                    prev_rpm = engine_state.get("last_rpm")
                    rpm = calc_engine_rpm(
                        speed_units=speed_units,
                        drift_ratio=my_car.drift_ratio,
                        throttle=th,
                        prev_rpm=prev_rpm,
                        dt=dt,
                        params=None,
                        _state=engine_state,
                    )
                    engine_state["last_rpm"] = rpm
                    # Get current gear from engine state for gear shift sounds
                    current_gear = engine_state.get("gear", 0)
                    # Thread-safe audio state update with gear and drift info
                    audio_controller.set_engine_state(
                        rpm=rpm, 
                        throttle=max(0.0, th),
                        current_gear=current_gear,
                        drift_ratio=my_car.drift_ratio
                    )
            except Exception as e:
                # Silently handle audio errors to prevent crashes on low-end devices
                pass

            # Prepare remotes view for AIs: include network remotes + all AIs + the local player (so AIs can detect collisions with player)
            remotes_with_ai_for_ais = dict(remotes)
            
            if I_AM_HOST:
                # add local player under a distinct key so AIs see it
                remotes_with_ai_for_ais[f"PLAYER-{my_id}"] = {"x": my_car.x, "y": my_car.y, "a": my_car.angle, "drift_ratio": my_car.drift_ratio, "name": my_car.name}
                for i, ai in enumerate(ai_cars, start=1):
                    key = f"AI-{i}"
                    remotes_with_ai_for_ais[key] = {"x": ai.x, "y": ai.y, "a": ai.angle, "drift_ratio": ai.drift_ratio, "name": ai.name}
                
            # Step AIs (each AI sees other AIs + network remotes + the player)
            if I_AM_HOST:
                for ai in ai_cars:
                    if movement_locked:
                        ai.vx, ai.vy = 0.0, 0.0
                        ai.v_angle = 0.0
                    else:
                        ai.step(ai_algorithme(path_poly, ai), dt, remotes_with_ai_for_ais, world_size, compute_debug=const.DEBUG)
            cam.update(my_car, world_size)
        else:
            # In menus: set default controls to prevent undefined variable errors
            controls = {"th": 0.0, "st": 0.0, "br": 0.0}

        # ======== RENDERING ========

        if not skip_physics:
            # draw track, drift marks and cars (online & local)
            render_stage = stage1 if stage1 != "leaderboard" else "mode1"
            world_surf, resized, is_viewport = renderer.render_world(cam, render_stage, my_car, ai_cars, remotes, lights_on, car_sprites_cache)
            if resized and not is_viewport:
                path_poly = path_finder.discover_track(normalize_asset_path("track", f"map{const.MAP_NUM}", "main.png"))

            # draw camera view (scaled or classic)
            if is_viewport: final_surf = pygame.transform.scale(world_surf, (const.WINDOW_WIDTH, const.WINDOW_HEIGHT))  # chunk mode
            else: final_surf = cam.apply(world_surf)  # classic mode
        else:
            # blank world surface for lobby, settings, key binds
            world_surf = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
            world_surf.fill(const.GREY_20)
            final_surf = world_surf

        # draw ui
        ui_surf = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), pygame.SRCALPHA)
        ui_surf.fill((0,0,0,0)) # transparent surface
        fps = clock.get_fps()
        ui_checkpoints = renderer.checkpoints
        if game_mode is not None and stage1 in ["mode1", "leaderboard"]:
            # mode1 draws only the next checkpoint via SimpleRace.draw_checkpoints
            ui_checkpoints = []
        world_surf, button_results, new_game_rects, join_game_rects = draw_stage_ui(
            ui_surf, stage1 if stage1 != "leaderboard" else "mode1",
            stage2, stage3, code, world_surf, world_size, ui_checkpoints,
            settings_buttons, error_msg, my_car, cam, gp, font_big, font_medium, font_small,
            controls, engine_state, fps, dt, I_AM_HOST, host_name, car_sprites_cache
        )

        # Game mode overlays (countdown, lap counter, leaderboard)
        _return_btn_rect = None
        if game_mode is not None:
            if stage1 == "leaderboard":
                lb_result = game_mode.draw_leaderboard(ui_surf, font_big, font_medium, font_small, I_AM_HOST)
                _return_btn_rect = lb_result.get("return_btn_rect")
            elif stage1 in ["mode1", "mode2"]:
                game_mode.draw_hud(ui_surf, cam, font_big, font_medium, font_small)
        
        # Handle button results from settings menu
        for res in button_results:
            if isinstance(res, tuple) and len(res) == 5:
                new_stage, new_substage, new_sock, new_code, new_remotes = res
                stage1 = new_stage
                stage2 = new_substage
                sock = new_sock
                code = new_code
                remotes = new_remotes

        if gpu_display is not None:
            try:
                gpu_display.present(final_surf, ui_surf)
            except Exception:
                print("gpu failed, fallback to software blit (fix pls)")
                screen.blit(final_surf, (0,0))
                screen.blit(ui_surf, (0,0))
                pygame.display.flip()
        else:
            screen.blit(final_surf, (0,0)) # world surface (cars, ai, map...)
            screen.blit(ui_surf, (0,0)) # top and bottom borders
        
        if const.AI_PATH_FOLLOW and stage1 == "game":
            try:
                top_right_pos = cam.x-(const.WINDOW_WIDTH/2)/cam.zoom, cam.y-(const.WINDOW_HEIGHT/2)/cam.zoom
                camera_rect = pygame.Rect(top_right_pos[0],
                                        top_right_pos[1],
                                        const.WINDOW_WIDTH/cam.zoom,
                                        const.WINDOW_HEIGHT/cam.zoom)
                visible_ai_debug_surface = ai_debug_surface.subsurface(camera_rect)
                #pygame.draw.rect(world_surf, TRACK_COLOR, camera_rect)
                screen.blit(visible_ai_debug_surface, (0, 0))
            except Exception: pass
        if gpu_display is None:
            pygame.display.flip()

if __name__ == "__main__":
    main()
