import json, math
import drift.config.const as const
from drift.tools.paths import normalize_asset_path
from drift.core.rpm import RpmParams

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

# Isometric perspective correction factor for 45° rendering (16cm/pix scale)
# Corrects collision mesh dimensions to match visual appearance
ISOMETRIC_CORRECTION = 1.0 / math.sqrt(2)  # ≈ 0.707
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
WALL_RESTITUTION = 0.3
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
steering_multiplier = 1.0  # persistent understeer/oversteer steering state across frames

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


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
    def __init__(self, x, y, name, is_ai=False, car_type="ae86", car_name="AE86"):
        self.x, self.y = float(x), float(y)
        self.vx, self.vy = 0.0, 0.0
        self.angle = 0.0
        self.v_angle = 0.0
        self.name = name
        self.drift_ratio = 0.0
        self.is_ai = is_ai
        self.car_type = car_type
        self.car_name = car_name
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
        
        spec_path = normalize_asset_path("cars", self.car_type, "specs.json")
        with open(spec_path, "r", encoding="utf-8") as fh:
            self.specs = json.load(fh)
        
        # Extract specs values and create RpmParams
        specs_vals = extract_specs_values(self.specs)
        self.rpm_params = RpmParams(
            redline_rpm=specs_vals["MAX_RPM"],
            gear_ratios=specs_vals["GEAR_RATIOS"],
            final_drive=specs_vals["FINAL_DRIVE"]
        )
        self.engine_sound_id = specs_vals["ENGINE_SOUND_ID"]
        self.palette_colors = specs_vals["PALETTE_COLORS"]
        
    def set_car_type(self, car_type):
        """Change car type at runtime and reload specs."""
        self.car_type = car_type
        spec_path = normalize_asset_path("cars", self.car_type, "specs.json")
        with open(spec_path, "r", encoding="utf-8") as fh:
            self.specs = json.load(fh)
        
        # Update RpmParams and palette colors for new car
        specs_vals = extract_specs_values(self.specs)
        self.rpm_params = RpmParams(
            redline_rpm=specs_vals["MAX_RPM"],
            gear_ratios=specs_vals["GEAR_RATIOS"],
            final_drive=specs_vals["FINAL_DRIVE"]
        )
        self.engine_sound_id = specs_vals["ENGINE_SOUND_ID"]
        self.palette_colors = specs_vals["PALETTE_COLORS"]

    def step(self, inputs, dt, players, bounds, compute_debug=False, cursor_follow=False, cam=None):        
        global steering_multiplier
        # Load specs values using new format
        specs_vals = extract_specs_values(self.specs)
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

        # Support both normalized (0..1+) and tiny legacy values (e.g. 0.009 intended as 0.9).
        hb_force = HANDBRAKE_FORCE if HANDBRAKE_FORCE >= 0.05 else HANDBRAKE_FORCE * 100.0
        hb_force = clamp(hb_force, 0.2, 1.5)

        # Inputs
        throttle_input = clamp(inputs.get("th", 0.0), -1.0, 1.0)
        raw_steering_input = clamp(inputs.get("st", 0.0), -1.0, 1.0)
        brake_input = clamp(inputs.get("br", 0.0), 0.0, 1.0)
        
        # Update target angle based on steering mode
        if cursor_follow and cam is not None:
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
        steering_multiplier = steering_multiplier * 0.95 if front_understeer else steering_multiplier * 1.05
        steering_multiplier = min(1.0, max(0.2, steering_multiplier))
        self.steering_multiplier = steering_multiplier
        #steering_input *= steering_multiplier

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
            steer_bias = const.STEER_BIAS 
        if TRANSMITION_SETUP in ["AWD", "AWDS", "FWD"]:
            steer_bias = const.STEER_BIAS*0.1

        if vel_dir_f > 0:
            wheel_steer_angle = -drift_angle*0.8* steer_bias

        wheel_steer_angle += steering_input * MAX_STEER_ANGLE * steering_multiplier

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
        wheel_debug_list = [] if compute_debug else None
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
            if compute_debug:
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
        self.y  += (self.vy * dt) * math.sqrt(2)  # compensate for isometric view at 45deg

        # Integrate yaw (angular) motion
        inertia_z = MASS * (CAR_LEN**2 + CAR_WID**2) / 12.0
        angular_accel = total_torque_z / max(1e-4, inertia_z)
        self.v_angle += angular_accel * dt
        # print(angular_accel * dt)
        
        # Apply deadzone to angular velocity to prevent drift from numerical errors
        # When rotating very slowly, snap to zero
        if abs(self.v_angle) < 0.01:  # deadzone threshold (radians/sec)
            self.v_angle = 0.0

        
        self.angle   += self.v_angle * dt

        # Save wheel debug for renderer (including body-level forces) - only if computed
        if compute_debug:
            self.wheel_debug["wheels"] = wheel_debug_list
            self.wheel_debug["body_forces"] = {
                "rolling": (rolling_x, rolling_y),
                "aero_drag": (drag_x, drag_y),
                "brake": (brake_x, brake_y),
            }
        self._handle_track_bounds(dt, bounds)

        # OBB vs OBB collisions with other cars (players dict contains x,y,a)
        for pid, d in players.items():
            if d["name"] == self.name:
                continue
            # Build oriented boxes for self and the other car
            my_pts = self._obb_corners(self.x, self.y, self.angle)
            other_pts = self._obb_corners(d["x"], d["y"], d.get("a", 0.0))
            collides, mtv = self._sat_mtv(my_pts, other_pts, (self.x, self.y), (d["x"], d["y"]))
            if collides:
                # Push self out along MTV and damp velocity along the collision normal
                nx, ny = mtv
                self.x += nx
                self.y += ny
                # Reflect velocity along normal component with some restitution
                n_len = math.hypot(nx, ny) or 1.0
                nxn, nyn = nx / n_len, ny / n_len
                v_dot_n = self.vx * nxn + self.vy * nyn
                if v_dot_n < 0:
                    # bounce component
                    self.vx -= (1.0 + WALL_RESTITUTION) * v_dot_n * nxn
                    self.vy -= (1.0 + WALL_RESTITUTION) * v_dot_n * nyn
                
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

        self.drift_points_old = self.drift_points
        self.drift_points = tuple(wheel_world_points)

    # wheel_debug already updated inside step above
            
    
    def _handle_track_bounds(self, dt, bounds):
        minx, maxx = TRACK_MARGIN, bounds[0] - TRACK_MARGIN
        miny, maxy = TRACK_MARGIN, bounds[1] - TRACK_MARGIN
        hit = False
        if self.x < minx:
            self.x = minx
            self.vx = -self.vx * WALL_RESTITUTION
            hit = True
        if self.x > maxx:
            self.x = maxx
            self.vx = -self.vx * WALL_RESTITUTION
            hit = True
        if self.y < miny:
            self.y = miny
            self.vy = -self.vy * WALL_RESTITUTION
            hit = True
        if self.y > maxy:
            self.y = maxy
            self.vy = -self.vy * WALL_RESTITUTION
            hit = True
        if hit:
            self.v_angle *= 0.5

    # (wheel debug and world transform now computed directly inside step)

    # --- OBB collision helpers (SAT) ---
    def _obb_corners(self, cx, cy, ang):
        ca, sa = math.cos(ang), math.sin(ang)
        # Load car dimensions from specs and apply isometric perspective correction
        specs_vals = extract_specs_values(self.specs)
        car_len = specs_vals["CAR_LEN"]
        car_wid = specs_vals["CAR_WID"]
        
        # Apply isometric perspective correction (1/√2 ≈ 0.707) for 45° rendering
        # Then apply collision mesh scaling factors (0.7 for length, 0.5 for width)
        hl = car_len * 0.7 * ISOMETRIC_CORRECTION
        hw = car_wid * 0.5 * ISOMETRIC_CORRECTION
        
        local = [(+hl, +hw), (+hl, -hw), (-hl, -hw), (-hl, +hw)]
        world = []
        for px, py in local:
            rx = px * ca - py * sa
            ry = px * sa + py * ca
            world.append((cx + rx, cy + ry))
        return world

    def _axes_from_polygon(self, pts):
        axes = []
        for i in range(len(pts)):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % len(pts)]
            # Edge vector
            ex, ey = x2 - x1, y2 - y1
            # Normalized perpendicular (axis)
            nx, ny = -ey, ex
            length = math.hypot(nx, ny) or 1.0
            axes.append((nx / length, ny / length))
        return axes

    def _project(self, axis, pts):
        ax, ay = axis
        mins = maxs = pts[0][0] * ax + pts[0][1] * ay
        for x, y in pts[1:]:
            p = x * ax + y * ay
            if p < mins: mins = p
            if p > maxs: maxs = p
        return mins, maxs

    def _interval_overlap(self, a_min, a_max, b_min, b_max):
        return min(a_max, b_max) - max(a_min, b_min)

    def _sat_mtv(self, ptsA, ptsB, centerA, centerB):
        # Gather axes from both polygons
        axes = self._axes_from_polygon(ptsA) + self._axes_from_polygon(ptsB)
        min_overlap = float('inf')
        best_axis = (0.0, 0.0)
        for ax in axes:
            a_min, a_max = self._project(ax, ptsA)
            b_min, b_max = self._project(ax, ptsB)
            overlap = self._interval_overlap(a_min, a_max, b_min, b_max)
            if overlap <= 0:
                return False, (0.0, 0.0)
            if overlap < min_overlap:
                min_overlap = overlap
                best_axis = ax
        # Direction from A to B to orient the MTV
        dirABx = centerB[0] - centerA[0]
        dirABy = centerB[1] - centerA[1]
        if best_axis[0] * dirABx + best_axis[1] * dirABy < 0:
            best_axis = (-best_axis[0], -best_axis[1])
        # MTV for A to move out of B
        mtv = (-best_axis[0] * min_overlap, -best_axis[1] * min_overlap)
        return True, mtv