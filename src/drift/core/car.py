import json, math, time
import drift.config.const as const
from drift.config.settings import physics_controls
from drift.tools.paths import normalize_asset_path
from drift.core.rpm import RpmParams

_SQRT2 = math.sqrt(2)  # pre-computed constant for isometric compensation

# world
WINDOW_WIDTH, WINDOW_HEIGHT = 1000, 700
TRACK_MARGIN = 40
TRANSMITION_SETUP = "RWD"
TRANSMITION_SETUP_DICT = {
    "RWD": [2, 3], # rear wheels drive
    "FWD": [0, 1], # front wheels drive
    "AWD": [0, 1, 2, 3], # all wheels drive
    "AWDS": [0, 1, 2, 3], # all wheels drive with rear steering
}


# 16 cm per pixel -> 160 mm per pixel
MM_PER_PIXEL = 80.0

# car (default values, will be overridden by specs)
CAR_LEN = 38.0
CAR_WID  = 20.0
ENGINE_ACC      = 450.0
#REVERSE_ACC     = 700.0
#BRAKE_DECEL     = 1400.0
#DRAG            = 0.35
#ROLLING         = 1.6
STEER_SENS      = 1/50
# Added for debug wheel kinematics (not used to alter dynamics)
MAX_STEER_ANGLE = math.radians(30.0)  # visual front wheel steering angle
# simple wheel placement relative to body center (x: forward, y: right)
WHEEL_X_OFF = CAR_LEN * 0.35
WHEEL_Y_OFF = CAR_WID * 0.45
#DRIFT_SENS      = 1/8000
OVERSTEER       = 1.5/100
#MAX_SPEED       = 1200.0
#ANGLE_DAMP      = 25

# Simple physics constants (default values, will be overridden by specs)
MASS = 5  # effective mass-like divisor used previously
BRAKE_COEFF = 600.0  # braking strength (N/kg) opposing wheel long. speed in wheel frame
CORNERING_STIFFNESS = 2  # lateral force per unit lateral speed (wheel frame)
LATERAL_FORCE_MAX = 2000.0  # clamp for lateral force magnitude (visual + stability)
INERTIA_Z = MASS * (CAR_LEN**2 + CAR_WID**2) / 12.0  # rough box inertia (module-level default only)

# New: rolling resistance and aerodynamic drag
GRAVITY = 9.81
ROLLING_RES_COEFF = 0.015  # typical car tire rolling resistance coefficient
AERO_DRAG_COEFF = 0.005    # combined 0.5*rho*CdA scaling (tune to taste)
BRAKE_DRAG_COEFF = 800.0    # body-level brake drag (opposes velocity)

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


# ── Spatial hash grid for broadphase collision ─────────────────────────────
class SpatialHash:
    """Grid-based spatial index for convex polygons."""
    __slots__ = ('cell_size', 'inv_cell', 'cells')

    def __init__(self, cell_size=80.0):
        self.cell_size = cell_size
        self.inv_cell = 1.0 / cell_size
        self.cells = {}  # (cx, cy) -> list[int]  (polygon indices)

    def build(self, polygons):
        """Index all polygons by their AABB cells."""
        self.cells.clear()
        inv = self.inv_cell
        cells = self.cells
        for idx, poly in enumerate(polygons):
            if len(poly) < 3:
                continue
            min_x = min_y = float('inf')
            max_x = max_y = float('-inf')
            for px, py in poly:
                if px < min_x: min_x = px
                if px > max_x: max_x = px
                if py < min_y: min_y = py
                if py > max_y: max_y = py
            cx0 = int(min_x * inv)
            cx1 = int(max_x * inv)
            cy0 = int(min_y * inv)
            cy1 = int(max_y * inv)
            for cx in range(cx0, cx1 + 1):
                for cy in range(cy0, cy1 + 1):
                    key = (cx, cy)
                    bucket = cells.get(key)
                    if bucket is None:
                        cells[key] = [idx]
                    else:
                        bucket.append(idx)

    def query_point(self, x, y):
        """Return polygon indices whose cell contains this point."""
        return self.cells.get((int(x * self.inv_cell), int(y * self.inv_cell)), ())


class CollisionMesh:
    """Wraps a list of polygons with a spatial hash for fast broadphase."""
    __slots__ = ('polygons', 'spatial_hash')

    def __init__(self, polygons, cell_size=80.0):
        self.polygons = list(polygons)
        self.spatial_hash = SpatialHash(cell_size)
        self.spatial_hash.build(self.polygons)

    def __bool__(self):
        return len(self.polygons) > 0

    def __len__(self):
        return len(self.polygons)

    def __iter__(self):
        return iter(self.polygons)

    def query_point(self, x, y):
        """Yield polygons near this point (broadphase filter)."""
        polys = self.polygons
        seen = set()
        for idx in self.spatial_hash.query_point(x, y):
            if idx not in seen:
                seen.add(idx)
                yield polys[idx]


def _point_in_polygon(px, py, polygon):
    """Ray-casting point-in-polygon test."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _wall_pushout(px, py, polygon):
    """If point is inside polygon, return (push_x, push_y, depth) toward nearest edge.
    Returns (0, 0, 0) if outside."""
    if not _point_in_polygon(px, py, polygon):
        return 0.0, 0.0, 0.0
    n = len(polygon)
    min_dist_sq = float('inf')
    nearest_x, nearest_y = px, py
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        ex, ey = x2 - x1, y2 - y1
        edge_len_sq = ex * ex + ey * ey
        if edge_len_sq < 1e-8:
            continue
        t = max(0.0, min(1.0, ((px - x1) * ex + (py - y1) * ey) / edge_len_sq))
        cx = x1 + t * ex
        cy = y1 + t * ey
        dx, dy = px - cx, py - cy
        d_sq = dx * dx + dy * dy
        if d_sq < min_dist_sq:
            min_dist_sq = d_sq
            nearest_x, nearest_y = cx, cy
    # Use squared distance for the zero-check; only sqrt once at the end
    if min_dist_sq < 1e-12:
        return 0.0, 0.0, 0.0
    dx = nearest_x - px
    dy = nearest_y - py
    depth = math.sqrt(min_dist_sq)
    return dx, dy, depth


def extract_specs_values(specs: dict) -> dict:
    """Extract physics values from new specs format with fallback to defaults."""
    try:
        # Primary source: real car dimensions in mm (converted to px at 16 cm/pix)
        dimensions = specs.get("specs", {}).get("dimensions", {})
        length_mm = dimensions.get("length")
        width_mm = dimensions.get("width")
        wheelbase_mm = dimensions.get("wheelbase")

        # Backward-compatible fallback for older/custom files using physics.wheels size directly in px
        fallback_len_px = specs.get("physics", {}).get("wheels", {}).get("length", 38.0)
        fallback_wid_px = specs.get("physics", {}).get("wheels", {}).get("width", 20.0)

        car_len = (length_mm / MM_PER_PIXEL) if isinstance(length_mm, (int, float)) else float(fallback_len_px)
        car_wid = (width_mm / MM_PER_PIXEL) if isinstance(width_mm, (int, float)) else float(fallback_wid_px)
        wheelbase = (wheelbase_mm / MM_PER_PIXEL) if isinstance(wheelbase_mm, (int, float)) else (car_len * 0.70)
        
        # Extract mass and performance metrics
        mass = specs.get("specs", {}).get("mass", 1150)  # in kg
        # Convert kg to mass units: assuming ~1150kg = MASS 5, so scale factor is ~230kg/unit
        mass_units = max(1.0, mass / 230.0)  # ensure minimum of 1.0
        
        # Extract engine acceleration - approximate from horsepower if not present
        # Using horsepower-to-acceleration approximation: ~1 unit acc per 5 hp
        hp = specs.get("specs", {}).get("horsepower", 200)
        engine_acc = (hp / 5.0) * 10.0  # scale factor to match old ENGINE_ACC ~450
        
        # Extract braking - max_torque and bias
        max_torque = specs.get("physics", {}).get("braking", {}).get("max_torque", 3800)
        brake_coeff = (max_torque / 3800.0) * 600.0  # normalize relative to 3800 base
        handbrake_force = specs.get("physics", {}).get("braking", {}).get("handbrake_force", 1.0)
        
        # Extract cornering stiffness
        cornering_stiffness = specs.get("physics", {}).get("cornering_stiffness", 0.80)
        # Scale to match old values which ranged 0.8-2.0, multiply by 2.5 to get in range ~1.5-2.5
        cornering_stiffness = cornering_stiffness * 2.5
        
        # Wheels stiffness factor 
        stiffness_factor = specs.get("physics", {}).get("wheels", {}).get("stiffness_factor", 0.85)
        front_grip = specs.get("physics", {}).get("wheels", {}).get("front_grip", 1.0)
        rear_grip  = specs.get("physics", {}).get("wheels", {}).get("rear_grip",  1.0)
        
        # Drivetrain - can be under specs or at root level
        drivetrain = specs.get("specs", {}).get("drivetrain", specs.get("drivetrain", "RWD"))
        
        # Extract engine parameters for RpmParams
        max_rpm = specs.get("engine", {}).get("max_rpm", 7000.0)
        gear_ratios = tuple(specs.get("engine", {}).get("gear_ratios", [3.166, 1.481, 1.1, 0.8]))
        final_drive = specs.get("engine", {}).get("final_drive", 4.1)
        engine_sound_id = specs.get("engine", {}).get("sound_id", "v8")
        
        # Extract palette colors
        palette_colors = specs.get("specs", {}).get("default_pallet", [[255, 0, 0], [0, 255, 0], [0, 0, 255]])
        palette_tuple = (tuple(palette_colors[0]), tuple(palette_colors[1]), tuple(palette_colors[2]))
        
        return {
            "CAR_LEN": car_len,
            "CAR_WID": car_wid,
            "WHEELBASE": wheelbase,
            "ENGINE_ACC": engine_acc,
            "MASS": mass_units,
            "BRAKE_COEFF": brake_coeff,
            "HANDBRAKE_FORCE": handbrake_force,
            "CORNERING_STIFFNESS": cornering_stiffness,
            "STIFFNESS_FACTOR": stiffness_factor,
            "FRONT_GRIP": front_grip,
            "REAR_GRIP": rear_grip,
            "DRIVETRAIN": drivetrain,
            "MAX_RPM": max_rpm,
            "GEAR_RATIOS": gear_ratios,
            "FINAL_DRIVE": final_drive,
            "ENGINE_SOUND_ID": str(engine_sound_id),
            "PALETTE_COLORS": palette_tuple
        }
    except (KeyError, TypeError, IndexError):
        # Fallback to defaults if specs are malformed
        return {
            "CAR_LEN": 38.0,
            "CAR_WID": 20.0,
            "WHEELBASE": 26.6,
            "ENGINE_ACC": 450.0,
            "MASS": 5,
            "BRAKE_COEFF": 600.0,
            "HANDBRAKE_FORCE": 1.0,
            "CORNERING_STIFFNESS": 2.0,
            "STIFFNESS_FACTOR": 0.85,
            "FRONT_GRIP": 1.0,
            "REAR_GRIP": 1.0,
            "DRIVETRAIN": "RWD",
            "MAX_RPM": 7000.0,
            "GEAR_RATIOS": (3.166, 1.481, 1.1, 0.8),
            "FINAL_DRIVE": 4.1,
            "ENGINE_SOUND_ID": "v8",
            "PALETTE_COLORS": ((255, 0, 0), (0, 255, 0), (0, 0, 255))
        }


def get_car_engine_sound_id(car_type: str) -> str:
    spec_path = normalize_asset_path("cars", car_type, "specs.json")
    with open(spec_path, "r", encoding="utf-8") as fh:
        specs = json.load(fh)
    return str(specs.get("engine", {}).get("sound_id", "v8"))

class Car:
    def __init__(self, x, y, name, is_ai=False, car_type=None):
        self.x, self.y = float(x), float(y)
        self.vx, self.vy = 0.0, 0.0
        self.angle = 0.0
        self.v_angle = 0.0
        self.name = name
        self.drift_ratio = 0.0
        self.is_ai = is_ai
        self.car_type = car_type if car_type is not None else const.CAR_ID
        self.car_name = const.get_car_name(const.CAR_ID)
        self.drift_points = [(0,0),(0,0),(0,0),(0,0)]
        self.drift_points_old = [(0,0),(0,0),(0,0),(0,0)]
        self.has_grip = (1.0, 1.0, 1.0, 1.0)  # wheel grip coefficient (FL, FR, RL, RR)
        self.is_reversing = False
        self.steering_multiplier = 1.0
        # Target angle steering system
        self.target_angle = 0.0
        # Last checkpoint position for respawn (set when entering a checkpoint rect)
        self.last_checkpoint_coordinates = None  # (x, y, angle) or None
        # Per-wheel debug data populated each step
        self.wheel_debug = {
            "wheels": []  # list of dicts per wheel
        }

        self.time_since_mouvement = 0
        
        # Network stats (measured locally, sent to other players via relay)
        self.ping_ms = None   # RTT/2 to relay server, in ms
        self.pl_pct = None    # packet loss %, measured from sq gaps + spike detection
        
        spec_path = normalize_asset_path("cars", self.car_type, "specs.json")
        with open(spec_path, "r", encoding="utf-8") as fh:
            self.specs = json.load(fh)
        
        # Extract specs values and create RpmParams
        specs_vals = extract_specs_values(self.specs)
        self._cached_specs_vals = specs_vals  # cache for per-frame use in step()
        self.rpm_params = RpmParams(
            redline_rpm=specs_vals["MAX_RPM"],
            gear_ratios=specs_vals["GEAR_RATIOS"],
            final_drive=specs_vals["FINAL_DRIVE"]
        )
        self.engine_sound_id = specs_vals["ENGINE_SOUND_ID"]
        self.palette_colors = specs_vals["PALETTE_COLORS"]
        self._init_spring_points(specs_vals)

    def _init_spring_points(self, specs_vals=None):
        """Create spring collision points around the car perimeter (local frame)."""
        if specs_vals is None:
            specs_vals = extract_specs_values(self.specs)
        halfL = specs_vals["CAR_LEN"] * 0.5
        halfW = specs_vals["CAR_WID"] * 0.5
        quatL = specs_vals["CAR_LEN"] * 0.25
        quatW = specs_vals["CAR_WID"] * 0.25
        self.spring_points_local = [
            (+halfL,  +halfW),
            (+halfL,  +quatW),
            (+halfL,  0.0),
            (+halfL,  -quatW),
            (+halfL,  -halfW),
            (+quatL,  -halfW),
            (0.0,     -halfW),
            (-quatL,  -halfW),
            (-halfL,  -halfW),
            (-halfL,  -quatW),
            (-halfL,  0.0),
            (-halfL,  +quatW),
            (-halfL,  +halfW),
            (-quatL,  +halfW),
            (0.0,     +halfW),
            (+quatL,  +halfW),
        ]

    def set_car_type(self, car_type):
        """Change car type at runtime and reload specs."""
        self.car_type = car_type
        spec_path = normalize_asset_path("cars", self.car_type, "specs.json")
        with open(spec_path, "r", encoding="utf-8") as fh:
            self.specs = json.load(fh)
        
        # Update RpmParams and palette colors for new car
        specs_vals = extract_specs_values(self.specs)
        self._cached_specs_vals = specs_vals  # refresh cache
        self.rpm_params = RpmParams(
            redline_rpm=specs_vals["MAX_RPM"],
            gear_ratios=specs_vals["GEAR_RATIOS"],
            final_drive=specs_vals["FINAL_DRIVE"]
        )
        self.engine_sound_id = specs_vals["ENGINE_SOUND_ID"]
        self.palette_colors = specs_vals["PALETTE_COLORS"]
        self._init_spring_points(specs_vals)

    def step(self, inputs, dt, players, bounds, cam=None, collision_mesh=None):        
        # Use cached specs values (updated only on set_car_type or __init__)
        specs_vals = self._cached_specs_vals
        CAR_LEN = specs_vals["CAR_LEN"]
        CAR_WID = specs_vals["CAR_WID"]
        WHEELBASE = specs_vals["WHEELBASE"]
        ENGINE_ACC = specs_vals["ENGINE_ACC"]
        MASS = specs_vals["MASS"]
        BRAKE_COEFF = specs_vals["BRAKE_COEFF"]
        HANDBRAKE_FORCE = specs_vals["HANDBRAKE_FORCE"]
        CORNERING_STIFFNESS = specs_vals["CORNERING_STIFFNESS"]
        TRANSMITION_SETUP = specs_vals["DRIVETRAIN"]
        FRONT_GRIP = specs_vals["FRONT_GRIP"]
        REAR_GRIP  = specs_vals["REAR_GRIP"]
        max_impact_speed = 0.0

        # Support both normalized (0..1+) and tiny legacy values (e.g. 0.009 intended as 0.9).
        hb_force = HANDBRAKE_FORCE if HANDBRAKE_FORCE >= 0.05 else HANDBRAKE_FORCE * 100.0
        hb_force = clamp(hb_force, 0.2, 1.5)

        # Inputs
        throttle_input = clamp(inputs.get("th", 0.0), -1.0, 1.0)
        raw_steering_input = clamp(inputs.get("st", 0.0), -1.0, 1.0)
        brake_input = clamp(inputs.get("br", 0.0), 0.0, 1.0)

        if self.is_ai:
            if self.vx**2 + self.vy**2 > 25 or self.last_checkpoint_coordinates is None:
                self.time_since_mouvement = time.time()
            if time.time() - self.time_since_mouvement > const.AI_RESET_DELAY and self.last_checkpoint_coordinates is not None:
                lx, ly, la = self.last_checkpoint_coordinates
                self.x, self.y, self.angle = lx, ly, la
                self.vx, self.vy = 0.0, 0.0
                self.v_angle = 0.0
                self.time_since_mouvement = time.time()
        
        # Update target angle based on steering mode
        if const.CURSOR_FOLLOW and cam is not None:
            # Mouse/cursor mode: directly set target angle to point at cursor
            import pygame
            mouse_pos = pygame.mouse.get_pos()
            # Convert mouse position to world coordinates
            world_mouse_x = mouse_pos[0] + cam.x - const.WINDOW_WIDTH / 2
            world_mouse_y = mouse_pos[1] + cam.y - const.WINDOW_HEIGHT / 2
            
            # Calculate angle from car to mouse
            dx = world_mouse_x - self.x
            dy = world_mouse_y - self.y
            self.target_angle = math.atan2(dy, dx)
        else:
            # Keyboard/joystick mode: accumulate steering input
            target_angle_change_rate = 2.0  # radians per second
            self.target_angle += raw_steering_input * target_angle_change_rate * dt
            # Normalize target angle to [-pi, pi]
            self.target_angle = ((self.target_angle + math.pi) % (2 * math.pi)) - math.pi
            
            # Clamp target angle to maximum difference from current angle
            max_angle_difference = math.radians(45)  # Maximum 45 degrees difference
            angle_diff = ((self.target_angle - self.angle + math.pi) % (2 * math.pi)) - math.pi
            if abs(angle_diff) > max_angle_difference:
                # Clamp to maximum allowed difference
                self.target_angle = self.angle + math.copysign(max_angle_difference, angle_diff)
                # Normalize again
                self.target_angle = ((self.target_angle + math.pi) % (2 * math.pi)) - math.pi
                
        # Orientation and basis vectors
        forward_x, forward_y = math.cos(self.angle), math.sin(self.angle)
        right_x, right_y = -forward_y, forward_x

        # Velocity in body frame (x: forward, y: right)
        body_forward_speed = self.vx * forward_x + self.vy * forward_y
        body_lateral_speed = self.vx * right_x + self.vy * right_y
        self.is_reversing = body_forward_speed < -5.0

        # Calculate steering input to reach target angle
        angle_error = ((self.target_angle - self.angle + math.pi) % (2 * math.pi)) - math.pi
        steering_input = clamp(angle_error * 2.0, -1.0, 1.0) * math.copysign(1, body_forward_speed)  # P controller with gain 2.0

        # Understeer tuning from previous-frame front grip state.
        front_understeer = (self.has_grip[0] < 0.5) or (self.has_grip[1] < 0.5)
        # Smoothly adjust steering multiplier based on understeer using rates per second
        grow_rate = 3.0   # per second increase when no understeer
        decay_rate = 6.0  # per second decrease when understeer
        if front_understeer:
            self.steering_multiplier -= decay_rate * dt
        else:
            self.steering_multiplier += grow_rate * dt
        
        self.steering_multiplier = clamp(self.steering_multiplier, 0.2, 1.0)

        # Drift angle/ratio (difference between velocity vector and heading)
        speed_norm = math.sqrt(body_forward_speed**2 + body_lateral_speed**2 + 1e-4)
        vel_dir_f = body_forward_speed / speed_norm
        vel_dir_r = body_lateral_speed / speed_norm
        drift_angle = ((math.atan2(vel_dir_f, vel_dir_r) - math.pi/2 + math.pi) % (2*math.pi) - math.pi)
        self.drift_ratio = clamp(abs(drift_angle) * clamp(abs(body_forward_speed) - 10.0, 0.0, 1.0), 0.0, 1.0)

        # Wheel configuration (local positions in body frame) - compute from current car dimensions
        wheel_x_off = WHEELBASE * 0.5
        wheel_y_off = CAR_WID * 0.45
        wheel_local_positions = [
            ( +wheel_x_off, +wheel_y_off),  # Front Left (FL)
            ( +wheel_x_off, -wheel_y_off),  # Front Right (FR)
            ( -wheel_x_off, +wheel_y_off),  # Rear Left (RL)
            ( -wheel_x_off, -wheel_y_off),  # Rear Right (RR)
        ]

        wheel_steer_angle = 0
        steer_bias = 0.0
        if TRANSMITION_SETUP == "RWD":
            steer_bias = physics_controls.get_value('steer_bias')
        elif TRANSMITION_SETUP in ["AWD", "AWDS", "FWD"]:
            steer_bias = physics_controls.get_value('steer_bias') * 0.1

        if vel_dir_f > 0:
            wheel_steer_angle = -drift_angle*0.8* steer_bias

        wheel_steer_angle += steering_input * MAX_STEER_ANGLE * self.steering_multiplier

        fl_steer = fr_steer = wheel_steer_angle
        if TRANSMITION_SETUP == "AWDS":
            rl_steer = -0.2 * fl_steer
            rr_steer = -0.2 * fr_steer
        else:
            rl_steer = 0.0
            rr_steer = 0.0
        wheel_angles = (fl_steer, fr_steer, rl_steer, rr_steer)

        # Accumulators for net forces/torque (body frame)
        total_force_body_x = 0.0
        total_force_body_y = 0.0
        total_torque_z = 0.0
        wheel_debug_list = [] if const.DEBUG else None
        grip_per_wheel = []

        for index, (wx_local, wy_local) in enumerate(wheel_local_positions):
            # Velocity at wheel contact in body frame: v + omega x r
            wheel_speed_x_body = body_forward_speed - self.v_angle * wy_local
            wheel_speed_y_body = body_lateral_speed + self.v_angle * wx_local

            # Per-wheel steering angle (Ackermann front, optional rear steer for AWDS).
            local_wheel_angle = wheel_angles[index]
            cwa, swa = math.cos(local_wheel_angle), math.sin(local_wheel_angle)

            # Transform to wheel frame (longitudinal x, lateral y)
            wheel_speed_long = wheel_speed_x_body * cwa + wheel_speed_y_body * swa
            wheel_speed_lat  = -wheel_speed_x_body * swa + wheel_speed_y_body * cwa
            
            # Longitudinal force: engine power distribution based on drivetrain
            # Front wheels (index 0, 1) have no engine power for RWD
            # Rear wheels (index 2, 3) get full engine power for RWD
            # All wheels get power for AWD/AWDS (divided by 2 to balance)
            if index in TRANSMITION_SETUP_DICT[TRANSMITION_SETUP]:  # Powered wheels
                longitudinal_force = throttle_input * ENGINE_ACC / (2.0 if TRANSMITION_SETUP in ("AWD", "AWDS") else 1.0)
            else:  # Non-powered wheels
                longitudinal_force = 0

            # Real handbrake behavior: rear-wheel lock tendency (not full chassis brake).
            is_rear_wheel = index in (2, 3)
            if is_rear_wheel and brake_input > 0.01:
                lock_strength = BRAKE_COEFF * (0.10 + 0.08 * hb_force)
                longitudinal_force += -wheel_speed_long * lock_strength * brake_input
                # Cap rear lock force so handbrake induces yaw/slip rather than hard stop.
                rear_lock_cap = 300.0 * (0.8 + 0.4 * hb_force)
                longitudinal_force = clamp(longitudinal_force, -rear_lock_cap, rear_lock_cap)

            # Keep longitudinal force bounded for numerical stability.
            longitudinal_force = clamp(longitudinal_force, -LATERAL_FORCE_MAX * 1.5, LATERAL_FORCE_MAX * 1.5)

            lat_grip = (100-abs(wheel_speed_lat))/(100-20)

            # Keep straight-line grip high: penalize longitudinal slip mismatch, not raw speed.
            throttle_penalty = 0.03 * abs(throttle_input) if index in TRANSMITION_SETUP_DICT[TRANSMITION_SETUP] else 0.0
            long_slip = abs(wheel_speed_long - body_forward_speed)
            wheel_long_penalty = clamp(long_slip / 40.0, 0.0, 0.25)
            long_grip = 1.0 - throttle_penalty - wheel_long_penalty

            # Handbrake reduces rear-wheel grip strongly (locked/released sliding behavior).
            if is_rear_wheel and brake_input > 0.01:
                long_grip *= clamp(1.0 - 0.65 * brake_input, 0.18, 1.0)
                lat_grip *= clamp(1.0 - 0.55 * brake_input, 0.22, 1.0)

            has_grip = clamp(clamp(lat_grip, 0.0, 1.0) * clamp(long_grip, 0.0, 1.0), 0.1, 1.0)
            axle_grip = FRONT_GRIP if index in (0, 1) else REAR_GRIP
            grip_per_wheel.append(has_grip)

            lateral_force = -wheel_speed_lat * CORNERING_STIFFNESS*5 * has_grip * axle_grip
            lateral_force = clamp(lateral_force, -LATERAL_FORCE_MAX, LATERAL_FORCE_MAX)

            # Back to body frame (rotate by wheel angle)
            force_body_x = longitudinal_force * cwa - lateral_force * swa
            force_body_y = longitudinal_force * swa + lateral_force * cwa

            total_force_body_x += force_body_x
            total_force_body_y += force_body_y

            # Torque about center (2D cross: r x F = x*Fy - y*Fx)
            total_torque_z += wx_local * force_body_y - wy_local * force_body_x

            # Prepare debug info (world position, wheel angle, forces, slip) - only if requested
            if const.DEBUG:
                # World position of wheel
                rx = wx_local * forward_x + wy_local * right_x
                ry = wx_local * forward_y + wy_local * right_y
                wheel_world_pos = (self.x + rx, self.y + ry)
                slip_angle = math.atan2(wheel_speed_lat, max(0.1, abs(wheel_speed_long)))
                wheel_debug_list.append({
                    "index": index,
                    "local_pos": (wx_local, wy_local),
                    "world_pos": wheel_world_pos,
                    "wheel_angle": local_wheel_angle,
                    "v_wheel": (wheel_speed_long, wheel_speed_lat),
                    "F_long": longitudinal_force,
                    "F_lat": lateral_force,
                    "slip": slip_angle,
                })

        self.has_grip = tuple(grip_per_wheel)

        # Convert total body forces to world frame
        total_force_world_x = total_force_body_x * forward_x + total_force_body_y * right_x
        total_force_world_y = total_force_body_x * forward_y + total_force_body_y * right_y

        # Rolling resistance, aerodynamic drag, and body-level braking (all oppose velocity)
        speed_world = math.hypot(self.vx, self.vy)
        rolling_x = rolling_y = drag_x = drag_y = brake_x = brake_y = 0.0
        if speed_world > 1e-4:
            # Rolling resistance ~ constant magnitude opposing motion
            Frr_mag = ROLLING_RES_COEFF * MASS * GRAVITY
            nx, ny = self.vx / speed_world, self.vy / speed_world
            rolling_x = -Frr_mag * nx
            rolling_y = -Frr_mag * ny

            # Aerodynamic drag ~ v^2, implemented as -k * |v| * v
            k = AERO_DRAG_COEFF * speed_world
            drag_x = -k * self.vx
            drag_y = -k * self.vy

            # Handbrake should not freeze the whole car body; keep global drag very small.
            B = BRAKE_DRAG_COEFF * brake_input * 0.02
            brake_x = -B * nx
            brake_y = -B * ny

            total_force_world_x += rolling_x + drag_x + brake_x
            total_force_world_y += rolling_y + drag_y + brake_y

        # Spring-based collision forces from collision mesh
        spring_debug = []
        if collision_mesh:
            SPRING_K = 100.0
            SPRING_DAMP = 0.0
            # Reduce collision spring strength for AI cars to avoid them getting stuck
            # inside tight point-based collision meshes. This makes spawned AIs 'softer'
            # against walls so they can recover instead of slowly spinning in place.
            ai_collision_scale = 0.25 if getattr(self, 'is_ai', False) else 1.0
            SPRING_K *= ai_collision_scale
            SPRING_DAMP *= ai_collision_scale
            # Use spatial hash if available (CollisionMesh), else fall back to raw list
            _use_spatial = hasattr(collision_mesh, 'query_point')
            for lx, ly in self.spring_points_local:
                # Transform local rest position to world
                wx = self.x + lx * forward_x - ly * forward_y
                wy = self.y + lx * forward_y + ly * forward_x
                displaced_x, displaced_y = wx, wy
                polys_to_check = collision_mesh.query_point(wx, wy) if _use_spatial else collision_mesh
                for polygon in polys_to_check:
                    if len(polygon) < 3:
                        continue
                    push_x, push_y, depth = _wall_pushout(wx, wy, polygon)
                    if depth > 0:
                        # The displaced position is the nearest edge point
                        displaced_x = wx + push_x
                        displaced_y = wy + push_y
                        # Spring force pushes car away from wall
                        fx = SPRING_K * push_x
                        fy = SPRING_K * push_y
                        # Damping: oppose velocity along push direction
                        nx = push_x / depth
                        ny = push_y / depth
                        v_normal = self.vx * nx + self.vy * ny
                        fx -= SPRING_DAMP * v_normal * nx
                        fy -= SPRING_DAMP * v_normal * ny
                        total_force_world_x += fx
                        total_force_world_y += fy
                        # Torque from collision force at spring point
                        rx = lx * forward_x - ly * forward_y
                        ry = lx * forward_y + ly * forward_x
                        total_torque_z += rx * fy - ry * fx
                spring_debug.append((wx, wy, displaced_x, displaced_y))
        self.spring_debug = spring_debug

        # Player-to-player collision (spring-based, half-force for desync fairness)
        if players:
            P2P_K = 150.0
            P2P_DAMP = 5.0
            # Default half-extents for other players (no specs available for remotes)
            other_halfL = CAR_LEN * 0.5
            other_halfW = CAR_WID * 0.5
            other_corners_local = [
                (+other_halfL, +other_halfW),
                (+other_halfL, -other_halfW),
                (-other_halfL, -other_halfW),
                (-other_halfL, +other_halfW),
            ]
            for pid, pdata in players.items():
                ox = pdata.get("x", 0.0)
                oy = pdata.get("y", 0.0)
                # Skip self entry to avoid colliding with own remote snapshot
                if pid == self.name:
                    continue
                oa = pdata.get("a", 0.0)
                # Skip if too far (broad phase)
                dx_broad = self.x - ox
                dy_broad = self.y - oy
                if dx_broad * dx_broad + dy_broad * dy_broad > (CAR_LEN + other_halfL * 2) ** 2:
                    continue
                # Build other player's world-space polygon
                oca, osa = math.cos(oa), math.sin(oa)
                other_poly = []
                for clx, cly in other_corners_local:
                    other_poly.append((ox + clx * oca - cly * osa,
                                       oy + clx * osa + cly * oca))
                # Test each of our spring points against their body
                for lx, ly in self.spring_points_local:
                    wx = self.x + lx * forward_x - ly * forward_y
                    wy = self.y + lx * forward_y + ly * forward_x
                    push_x, push_y, depth = _wall_pushout(wx, wy, other_poly)
                    if depth > 0:
                        nx = push_x / depth
                        ny = push_y / depth
                        # Half force: each player computes their own half
                        fx = 0.5 * P2P_K * push_x
                        fy = 0.5 * P2P_K * push_y
                        # Relative velocity damping
                        ovx = pdata.get("vx", 0.0)
                        ovy = pdata.get("vy", 0.0)
                        rel_vn = (self.vx - ovx) * nx + (self.vy - ovy) * ny
                        fx -= 0.5 * P2P_DAMP * rel_vn * nx
                        fy -= 0.5 * P2P_DAMP * rel_vn * ny
                        total_force_world_x += fx
                        total_force_world_y += fy
                        rx = lx * forward_x - ly * forward_y
                        ry = lx * forward_y + ly * forward_x
                        total_torque_z += rx * fy - ry * fx

        # World-edge spring forces
        if bounds and len(bounds) >= 2:
            world_w, world_h = bounds
            EDGE_K = 100.0
            for lx, ly in self.spring_points_local:
                wx = self.x + lx * forward_x - ly * forward_y
                wy = self.y + lx * forward_y + ly * forward_x
                rx = lx * forward_x - ly * forward_y
                ry = lx * forward_y + ly * forward_x
                efx, efy = 0.0, 0.0
                if wx < 0:
                    efx = EDGE_K * -wx
                elif wx > world_w:
                    efx = EDGE_K * (world_w - wx)
                if wy < 0:
                    efy = EDGE_K * -wy
                elif wy > world_h:
                    efy = EDGE_K * (world_h - wy)
                if efx != 0.0 or efy != 0.0:
                    total_force_world_x += efx
                    total_force_world_y += efy
                    total_torque_z += rx * efy - ry * efx

        # Integrate linear motion
        accel_x = total_force_world_x / MASS
        accel_y = total_force_world_y / MASS
        self.vx += accel_x * dt
        self.vy += accel_y * dt
        # Cap reverse speed at 80 px/s
        body_fwd = self.vx * forward_x + self.vy * forward_y
        if body_fwd < -80.0:
            excess = body_fwd + 80.0
            self.vx -= excess * forward_x
            self.vy -= excess * forward_y
        self.x  += self.vx * dt
        self.y  += (self.vy * dt) * _SQRT2  # compensate for isometric view at 45deg

        # Integrate yaw (angular) motion
        inertia_z = MASS * (CAR_LEN**2 + CAR_WID**2) / 12.0
        angular_accel = total_torque_z / max(1e-4, inertia_z)
        self.v_angle += angular_accel * dt
        
        # Apply deadzone to angular velocity to prevent drift from numerical errors
        # When rotating very slowly, snap to zero
        if abs(self.v_angle) < 0.01:  # deadzone threshold (radians/sec)
            self.v_angle = 0.0

        
        self.angle   += self.v_angle * dt

        # Hard position correction: push car out if any spring point is still inside geometry
        if collision_mesh:
            ca2, sa2 = math.cos(self.angle), math.sin(self.angle)
            inertia_z_corr = MASS * (CAR_LEN**2 + CAR_WID**2) / 12.0
            RESTITUTION = 0.2  # 0 = no bounce, 1 = perfect bounce
            for _iter in range(4):
                worst_depth = 0.0
                total_push_x, total_push_y = 0.0, 0.0
                contacts = 0
                contact_offsets = []  # (rx, ry) world-frame offsets from car center
                for lx, ly in self.spring_points_local:
                    wx = self.x + lx * ca2 - ly * sa2
                    wy = self.y + lx * sa2 + ly * ca2
                    polys_to_check = collision_mesh.query_point(wx, wy) if _use_spatial else collision_mesh
                    for polygon in polys_to_check:
                        if len(polygon) < 3:
                            continue
                        push_x, push_y, depth = _wall_pushout(wx, wy, polygon)
                        if depth > 0:
                            total_push_x += push_x
                            total_push_y += push_y
                            contacts += 1
                            contact_offsets.append((lx * ca2 - ly * sa2, lx * sa2 + ly * ca2))
                            if depth > worst_depth:
                                worst_depth = depth
                if contacts == 0:
                    break
                avg_px = total_push_x / contacts
                avg_py = total_push_y / contacts
                avg_len_sq = avg_px * avg_px + avg_py * avg_py
                if avg_len_sq < 1e-12:
                    break
                avg_len = math.sqrt(avg_len_sq)
                nx = avg_px / avg_len
                ny = avg_py / avg_len
                self.x += nx * worst_depth
                self.y += ny * worst_depth
                # Reflect velocity off the wall (bounce)
                v_into = self.vx * nx + self.vy * ny
                if v_into < 0:
                    max_impact_speed = max(max_impact_speed, -v_into)
                    impulse_x = -(1.0 + RESTITUTION) * v_into * nx
                    impulse_y = -(1.0 + RESTITUTION) * v_into * ny
                    self.vx += impulse_x
                    self.vy += impulse_y
                    # Angular impulse: sum of r x J for each contact point
                    ang_impulse = 0.0
                    for crx, cry in contact_offsets:
                        ang_impulse += crx * impulse_y - cry * impulse_x
                    self.v_angle += ang_impulse / max(1e-4, inertia_z_corr)

        # Hard position correction for world edges
        if bounds and len(bounds) >= 2:
            world_w, world_h = bounds
            ca2, sa2 = math.cos(self.angle), math.sin(self.angle)
            inertia_z_edge = MASS * (CAR_LEN**2 + CAR_WID**2) / 12.0
            EDGE_REST = 0.3
            for lx, ly in self.spring_points_local:
                wx = self.x + lx * ca2 - ly * sa2
                wy = self.y + lx * sa2 + ly * ca2
                push_nx, push_ny, pen = 0.0, 0.0, 0.0
                if wx < 0:
                    push_nx, pen = 1.0, -wx
                elif wx > world_w:
                    push_nx, pen = -1.0, wx - world_w
                if wy < 0:
                    push_ny = 1.0
                    pen = max(pen, -wy)
                elif wy > world_h:
                    push_ny = -1.0
                    pen = max(pen, wy - world_h)
                if pen > 0:
                    plen = math.sqrt(push_nx * push_nx + push_ny * push_ny)
                    if plen > 1e-6:
                        push_nx /= plen
                        push_ny /= plen
                    self.x += push_nx * pen
                    self.y += push_ny * pen
                    v_into = self.vx * push_nx + self.vy * push_ny
                    if v_into < 0:
                        max_impact_speed = max(max_impact_speed, -v_into)
                        imp_x = -(1.0 + EDGE_REST) * v_into * push_nx
                        imp_y = -(1.0 + EDGE_REST) * v_into * push_ny
                        self.vx += imp_x
                        self.vy += imp_y
                        crx = lx * ca2 - ly * sa2
                        cry = lx * sa2 + ly * ca2
                        self.v_angle += (crx * imp_y - cry * imp_x) / max(1e-4, inertia_z_edge)

        # Hard position correction for player-to-player overlap (half push for desync fairness)
        if players:
            ca2, sa2 = math.cos(self.angle), math.sin(self.angle)
            inertia_z_p2p = MASS * (CAR_LEN**2 + CAR_WID**2) / 12.0
            P2P_REST = 0.3
            other_halfL = CAR_LEN * 0.5
            other_halfW = CAR_WID * 0.5
            other_corners_local = [
                (+other_halfL, +other_halfW),
                (+other_halfL, -other_halfW),
                (-other_halfL, -other_halfW),
                (-other_halfL, +other_halfW),
            ]
            for pid, pdata in players.items():
                ox = pdata.get("x", 0.0)
                oy = pdata.get("y", 0.0)
                # Skip self entry (avoid self-collision when remotes includes this car)
                if pid == self.name:
                    continue
                oa = pdata.get("a", 0.0)
                dx_broad = self.x - ox
                dy_broad = self.y - oy
                if dx_broad * dx_broad + dy_broad * dy_broad > (CAR_LEN + other_halfL * 2) ** 2:
                    continue
                oca, osa = math.cos(oa), math.sin(oa)
                other_poly = [(ox + clx * oca - cly * osa, oy + clx * osa + cly * oca)
                              for clx, cly in other_corners_local]
                ovx = pdata.get("vx", 0.0)
                ovy = pdata.get("vy", 0.0)
                for lx, ly in self.spring_points_local:
                    wx = self.x + lx * ca2 - ly * sa2
                    wy = self.y + lx * sa2 + ly * ca2
                    push_x, push_y, depth = _wall_pushout(wx, wy, other_poly)
                    if depth > 0:
                        # depth already guaranteed > 1e-6 by _wall_pushout
                        nx = push_x / depth
                        ny = push_y / depth
                        # Push out only half — other player pushes their half
                        self.x += nx * depth * 0.5
                        self.y += ny * depth * 0.5
                        # Use relative velocity so a car following at the same speed
                        # doesn't receive a huge impulse from its own forward motion.
                        v_into = (self.vx - ovx) * nx + (self.vy - ovy) * ny
                        if v_into < 0:
                            max_impact_speed = max(max_impact_speed, -v_into)
                            imp_x = -(1.0 + P2P_REST) * v_into * nx * 0.5
                            imp_y = -(1.0 + P2P_REST) * v_into * ny * 0.5
                            self.vx += imp_x
                            self.vy += imp_y
                            crx = lx * ca2 - ly * sa2
                            cry = lx * sa2 + ly * ca2
                            self.v_angle += (crx * imp_y - cry * imp_x) / max(1e-4, inertia_z_p2p)

        # Save wheel debug for renderer (including body-level forces) - only if computed
        if const.DEBUG:
            self.wheel_debug["wheels"] = wheel_debug_list
            self.wheel_debug["body_forces"] = {
                "rolling": (rolling_x, rolling_y),
                "aero_drag": (drag_x, drag_y),
                "brake": (brake_x, brake_y),
            }

        ca, sa = math.cos(self.angle), math.sin(self.angle)
        halfL, halfW = CAR_LEN * 0.5, CAR_WID * 0.5
        pts = [(+halfL, +halfW),
               (+halfL, -halfW),
               (-halfL, -halfW),
               (-halfL, +halfW)]
        wpts = []
        for px, py in pts:
            rx = px * ca - py * sa
            ry = px * sa + py * ca
            wpts.append((int(self.x + rx), int(self.y + ry)))

        wheel_world_points = []
        for wx_local, wy_local in wheel_local_positions:
            rx = wx_local * ca - wy_local * sa
            ry = wx_local * sa + wy_local * ca
            wheel_world_points.append((int(self.x + rx), int(self.y + ry)))

        return max_impact_speed

        self.drift_points_old = self.drift_points
        self.drift_points = tuple(wheel_world_points)

    # wheel_debug already updated inside step above