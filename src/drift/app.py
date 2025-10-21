#!/usr/bin/env python3

# ======= IMPORTS =======

# global imports
import pygame, json, time, random, sys, math, uuid, argparse, threading
# local imports
from tools.paths import asset_path
import drift.config.const as const
import drift.render.camera as camera
import drift.core.car as car
import drift.ui.button as btn
import drift.ai.path_finder as path_finder
from drift.render.renderer import WorldRenderer
from drift.core.helpers import clamp, rand_name
from drift.ai.ai import ai_algorithme
from drift.core.inputs import read_inputs
from drift.net.communication import connect_to_relay, handle_network_messages, send_network_state, send_ai_states, send_ping, recv_jsons
from drift.ui.ui import handle_game_events, draw_stage_ui
from drift.core.rpm import calc_engine_rpm
from drift.audio.engine_audio import EngineAudio
from drift.render.map_chunks import ChunkedMap

# ======= CONFIGURATION =======

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
                print(f"Audio rate reduced to {self._adaptive_rate:.1f} Hz due to performance")
        
        # If processing is fast, try to increase rate (but not above target)
        elif avg_processing_time < target_frame_time * 0.3:
            new_rate = min(self.target_update_rate, self._adaptive_rate * 1.1)
            if new_rate != self._adaptive_rate:
                self._adaptive_rate = new_rate
                self.update_interval = 1.0 / self._adaptive_rate
                print(f"Audio rate increased to {self._adaptive_rate:.1f} Hz")
    
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


# ======= CONFIGURATION =======

RELAY_PUBLIC_ENDPOINT = const.RELAY_PUBLIC_ENDPOINT
# True : client creates a room, False : joining
I_AM_HOST = False

flags = const.FLAGS

# ======= LOADING SCREEN =======

def draw_loading_screen(screen, progress, total_steps, current_task="Loading..."):
    """Draw a loading screen with circular progress bar from 7π/4 to π/4"""
    screen.fill((20, 20, 30))  # Dark background
    
    # Create fonts for loading screen
    title_font = pygame.font.SysFont(None, 72)
    task_font = pygame.font.SysFont(None, 36)
    
    # Calculate center
    center_x = const.WINDOW_WIDTH // 2
    center_y = const.WINDOW_HEIGHT // 2
    
    # Draw title
    title_text = title_font.render("Drift Race v0.7.10", True, (255, 255, 255))
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
            num_segments = max(1, int(progress_ratio * 200))  # More segments for smoother arc
            
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
    
    pygame.display.flip()

def load_assets_with_progress(screen, clock):
    """Load all game assets with progress tracking"""
    
    # Define loading steps
    loading_steps = [
        ("Initializing audio...", "audio"),
        ("Loading car sprites...", "sprites"),
        ("Loading track data...", "track"),
        ("Initializing systems...", "systems"),
        ("Starting engine audio...", "engine_audio"),
        ("Finalizing...", "final")
    ]
    
    total_steps = len(loading_steps)
    loaded_data = {}
    
    for step, (task_name, step_key) in enumerate(loading_steps):
        # Update loading screen
        draw_loading_screen(screen, step, total_steps, task_name)
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
            loaded_data["track_image"] = pygame.image.load(asset_path("track", f"map{const.MAP_NUM}", "main.png")).convert()
            loaded_data["chunk_map"] = ChunkedMap(root=asset_path("track", f"map{const.MAP_NUM}", "chunks"), tile_size=1024)
            time.sleep(0.1)
            
        elif step_key == "systems":
            loaded_data["path_poly"] = []  # Will be initialized later
            time.sleep(0.1)
            
        elif step_key == "engine_audio":
            loaded_data["engine_audio"], loaded_data["audio_controller"] = start_engine_audio_thread(loaded_data["audio_initialized"])
            time.sleep(0.1)

        elif step_key == "final":
            time.sleep(0.1)
    
    # Show 100% completion briefly
    draw_loading_screen(screen, total_steps, total_steps, "Complete!")
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

def start_engine_audio_thread(audio_initialized):
    # Engine audio: 4A-GE Bluetop intake+exhaust layers
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
    
    pygame.display.set_caption("Drift Race v0.7.10")
    screen = pygame.display.set_mode((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
    clock = pygame.time.Clock()
    
    # Show loading screen and load assets
    loaded_assets = load_assets_with_progress(screen, clock)
    
    # Create fonts after pygame.init()
    font_small = pygame.font.SysFont(None, const.FONT_SMALL_SIZE)
    font_medium = pygame.font.SysFont(None, const.FONT_MEDIUM_SIZE)
    font_big = pygame.font.SysFont(None, const.FONT_BIG_SIZE)
    
    # Extract loaded assets
    audio_initialized = loaded_assets["audio_initialized"]
    car_sprites_cache = loaded_assets["car_sprites_cache"]
    track_image = loaded_assets["track_image"]
    chunk_map = loaded_assets["chunk_map"]
    engine_sound = loaded_assets["engine_audio"]
    audio_controller = loaded_assets["audio_controller"]

    stage1 = "lobby" # lobby | game | error
    stage2 = "" # new_game | join_game | settings
    stage3 = "" # key_binds
    error_msg = ""
    remotes = {}
    ai_cars = []
    path_poly = []

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
    renderer = WorldRenderer(track_image, flags, chunked_map=chunk_map)

    joysticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
    for js in joysticks:
        js.init()

    # Create a camera object; mouse wheel will adjust zoom and middle mouse drag will pan.
    cam = camera.Camera(const.WINDOW_WIDTH, const.WINDOW_HEIGHT, zoom=1.0)
    dragging = False
    host_ref = [I_AM_HOST]

    def leave_room(sock, code, my_id, remotes):
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
        return "lobby", "", None, None, remotes # stage, substage sock, code, remotes
        
    def switch_cursor_follow_mode():
        const.CURSOR_FOLLOW = not const.CURSOR_FOLLOW
        if const.CURSOR_FOLLOW: const.AI_PATH_FOLLOW = False
        # stage, substage sock, code, remotes
        try: return "game", "", sock, code, remotes
        except Exception: return "game", "", None, None, {}

    def switch_ai_path_mode():
        const.AI_PATH_FOLLOW = not const.AI_PATH_FOLLOW
        if const.AI_PATH_FOLLOW: const.CURSOR_FOLLOW = False
        # stage, substage sock, code, remotes
        try: return "game", "", sock, code, remotes
        except Exception: return "game", "", None, None, {}

    settings_buttons = [
    btn.Button("Leave Room", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.35, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, lambda: leave_room(sock, code, my_id, remotes)),
    btn.Button("Cursor Follow Mode", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.55, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, switch_cursor_follow_mode),
    btn.Button("AI Path Mode", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.65, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, switch_ai_path_mode),
    ]

    while True:
        dt = clock.tick(const.FPS) / 1000.0
        #dt = min(dt, 1 / const.FPS)  # Cap dt to avoid large jumps

        # ======== EVENT HANDLING ========

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

            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_l:
                lights_on = not lights_on
            if ev.type == pygame.KEYDOWN and ev.key == const.CHANGE_CAR_KEY:
                # Cycle through available car types
                available_types = list(const.CAR_SPRITES.keys())
                current_index = available_types.index(my_car.car_type)
                next_index = (current_index + 1) % len(available_types)
                my_car.car_type = available_types[next_index]
            if ev.type == pygame.KEYDOWN and ev.key == const.DEBUG_TOGGLE_KEY:
                # Toggle debug mode
                const.DEBUG = not const.DEBUG
                print(f"Debug mode {'enabled' if const.DEBUG else 'disabled'}")
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_n:
                if I_AM_HOST and stage1 == "game":
                    # Randomly assign car type for AI cars
                    ai_car_type = random.choice(["ae86", "m5"])
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

            ev, stage1, stage2, remotes, sock, code, my_car, error_msg, host_name = handle_game_events(screen, ev, stage1, stage2, remotes, ai_cars, sock, code, my_name, my_id, my_car, font_big, font_small, error_msg, host_ref, host_name)
            I_AM_HOST = host_ref[0]

        if sock:
            err = handle_network_messages(sock, remotes, dt, my_id, I_AM_HOST)
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

        # ======== FRAME UPDATE ========
        
        world_size = renderer.get_world_size(stage1)

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
            controls = read_inputs(joysticks, my_car, cam, const.CURSOR_FOLLOW, const.AI_PATH_FOLLOW)
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
                ai.step(ai_algorithme(path_poly, ai), dt, remotes_with_ai_for_ais, world_size, compute_debug=const.DEBUG)
        cam.update(my_car, world_size)

        # ======== RENDERING ========

        # draw track, drift marks and cars (online & local)
        world_surf, resized, is_viewport = renderer.render_world(cam, stage1, my_car, ai_cars, remotes, lights_on, car_sprites_cache)
        if resized and not is_viewport:
            path_poly = path_finder.discover_track(asset_path("track", f"map{const.MAP_NUM}", "main.png"))

        # draw camera view (scaled or classic)
        if is_viewport: final_surf = pygame.transform.scale(world_surf, (const.WINDOW_WIDTH, const.WINDOW_HEIGHT))  # chunk mode
        else: final_surf = cam.apply(world_surf)  # classic mode

        # draw ui
        ui_surf = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), pygame.SRCALPHA)
        ui_surf.fill((0,0,0,0)) # transparent surface
        fps = clock.get_fps()
        world_surf, button_results, new_game_rects, join_game_rects = draw_stage_ui(
            ui_surf, stage1, stage2, stage3, code, world_surf, world_size, 
            settings_buttons, error_msg, my_car, cam, joysticks, font_big, font_medium, font_small,
            controls, engine_state, fps, dt, host_name
        )
        
        # Handle button results from settings menu
        for res in button_results:
            if isinstance(res, tuple) and len(res) == 5:
                new_stage, new_substage, new_sock, new_code, new_remotes = res
                stage1 = new_stage
                stage2 = new_substage
                sock = new_sock
                code = new_code
                remotes = new_remotes

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
        pygame.display.flip()

if __name__ == "__main__":
    main()
