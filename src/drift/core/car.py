import json, math
import drift.config.const as const
from drift.tools.paths import normalize_asset_path

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
# car
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

# Simple physics constants
MASS = 5  # effective mass-like divisor used previously
BRAKE_COEFF = 600.0  # braking strength (N/kg) opposing wheel long. speed in wheel frame
CORNERING_STIFFNESS = 2  # lateral force per unit lateral speed (wheel frame)
LATERAL_FORCE_MAX = 2000.0  # clamp for lateral force magnitude (visual + stability)
ANGULAR_DAMP = 25.0  # simple yaw damping (increased to prevent unwanted rotation)
INERTIA_Z = MASS * (CAR_LEN**2 + CAR_WID**2) / 24.0  # rough box inertia

# New: rolling resistance and aerodynamic drag
GRAVITY = 9.81
ROLLING_RES_COEFF = 0.015  # typical car tire rolling resistance coefficient
AERO_DRAG_COEFF = 0.005    # combined 0.5*rho*CdA scaling (tune to taste)
BRAKE_DRAG_COEFF = 800.0    # body-level brake drag (opposes velocity)

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

class Car:
    def __init__(self, x, y, name, is_ai=False, car_type="ae86"):
        self.x, self.y = float(x), float(y)
        self.vx, self.vy = 0.0, 0.0
        self.angle = 0.0
        self.v_angle = 0.0
        self.name = name
        self.drift_ratio = 0.0
        self.is_ai = is_ai
        self.car_type = car_type
        self.drift_points = [(0,0),(0,0)]
        self.drift_points_old = [(0,0),(0,0)]
        self.has_grip = (1.0, 1.0, 1.0, 1.0)  # wheel grip coefficient (FL, FR, RL, RR)
        # Target angle steering system
        self.target_angle = 0.0
        # Per-wheel debug data populated each step
        self.wheel_debug = {
            "wheels": []  # list of dicts per wheel
        }
        
        spec_path = normalize_asset_path("cars", self.car_type, "specs.json")
        with open(spec_path, "r", encoding="utf-8") as fh:
            self.specs = json.load(fh)
        
    def set_car_type(self, car_type):
        """Change car type at runtime and reload specs."""
        self.car_type = car_type
        spec_path = normalize_asset_path("cars", self.car_type, "specs.json")
        with open(spec_path, "r", encoding="utf-8") as fh:
            self.specs = json.load(fh)

    def step(self, inputs, dt, players, bounds, compute_debug=False, cursor_follow=False, cam=None):        
        CAR_LEN = self.specs["dimensions"]["CAR_LEN"]
        CAR_WID  = self.specs["dimensions"]["CAR_WID"]
        ENGINE_ACC      = self.specs["performance"]["ENGINE_ACC"]
        MASS = self.specs["performance"]["MASS"]
        BRAKE_COEFF = self.specs["performance"]["BRAKE_COEFF"]
        CORNERING_STIFFNESS = self.specs["performance"]["CORNERING_STIFFNESS"]
        TRANSMITION_SETUP = self.specs["drivetrain"]["layout"]

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
            target_angle_change_rate = 3.0  # radians per second
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
        
        # Calculate steering input to reach target angle
        angle_error = ((self.target_angle - self.angle + math.pi) % (2 * math.pi)) - math.pi
        steering_input = clamp(angle_error * 2.0, -1.0, 1.0)  # P controller with gain 2.0

        # Orientation and basis vectors
        forward_x, forward_y = math.cos(self.angle), math.sin(self.angle)
        right_x, right_y = -forward_y, forward_x

        # Velocity in body frame (x: forward, y: right)
        body_forward_speed = self.vx * forward_x + self.vy * forward_y
        body_lateral_speed = self.vx * right_x + self.vy * right_y

        # Calculate steering input to reach target angle
        angle_error = ((self.target_angle - self.angle + math.pi) % (2 * math.pi)) - math.pi
        steering_input = clamp(angle_error * 2.0, -1.0, 1.0) * math.copysign(1, body_forward_speed)  # P controller with gain 2.0

        # Drift angle/ratio (difference between velocity vector and heading)
        speed_norm = math.sqrt(body_forward_speed**2 + body_lateral_speed**2 + 1e-4)
        vel_dir_f = body_forward_speed / speed_norm
        vel_dir_r = body_lateral_speed / speed_norm
        drift_angle = ((math.atan2(vel_dir_f, vel_dir_r) - math.pi/2 + math.pi) % (2*math.pi) - math.pi)
        self.drift_ratio = clamp(abs(drift_angle) * clamp(abs(body_forward_speed) - 10.0, 0.0, 1.0), 0.0, 1.0)

        # Wheel configuration (local positions in body frame) - compute from current car dimensions
        wheel_x_off = CAR_LEN * 0.35
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
        if TRANSMITION_SETUP == "AWD":
            steer_bias = const.STEER_BIAS*0.1
        if TRANSMITION_SETUP == "AWDS":
            steer_bias = const.STEER_BIAS*0.1

        if vel_dir_f > 0:
            wheel_steer_angle = -drift_angle*0.8* steer_bias

        if TRANSMITION_SETUP == "RWD" and vel_dir_f > 0:
            wheel_steer_angle += (steering_input * MAX_STEER_ANGLE)/clamp(speed_norm/50, 1.0, 5.0)
        else:
            wheel_steer_angle += steering_input * MAX_STEER_ANGLE

        #temporaly disabled its less realistic but feels better
        #wheel_steer_angle = clamp(wheel_steer_angle, -MAX_STEER_ANGLE, MAX_STEER_ANGLE)

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

            # Wheel heading relative to body (front wheels steer, rear wheels steer for AWDS)
            if index in (0, 1):  # Front wheels
                local_wheel_angle = wheel_steer_angle
            elif TRANSMITION_SETUP == "AWDS":  # Rear wheels with AWDS (All-Wheel Steering)
                local_wheel_angle = wheel_steer_angle * -0.2  # Opposite direction, 20% of front
            else:  # Rear wheels for other drivetrains
                local_wheel_angle = 0.0
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


            lat_grip = (100-abs(wheel_speed_lat))/(100-20)
            long_grip = (100-abs(longitudinal_force))/(100-20)

            has_grip = clamp(clamp(lat_grip, 0.0, 1.0) * clamp(long_grip, 0.0, 1.0), 0.1, 1.0)
            grip_per_wheel.append(has_grip)

            lateral_force = -wheel_speed_lat * CORNERING_STIFFNESS*5 * has_grip
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

            # Body-level brake drag (simple model): magnitude scales with brake input
            B = BRAKE_DRAG_COEFF * brake_input
            brake_x = -B * nx
            brake_y = -B * ny

            total_force_world_x += rolling_x + drag_x + brake_x
            total_force_world_y += rolling_y + drag_y + brake_y

        # Integrate linear motion
        accel_x = total_force_world_x / MASS
        accel_y = total_force_world_y / MASS
        self.vx += accel_x * dt
        self.vy += accel_y * dt
        self.x  += self.vx * dt
        self.y  += (self.vy * dt) * math.sqrt(2)  # compensate for isometric view at 45deg

        # Integrate yaw (angular) motion with simple damping
        angular_accel = (total_torque_z - ANGULAR_DAMP * self.v_angle) / max(1e-4, INERTIA_Z)
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

        self.drift_points_old = self.drift_points
        self.drift_points = (wpts[2], wpts[3])

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
        # Use extended half-length for collisions as requested
        hl, hw = CAR_LEN * 0.7, CAR_WID * 0.5
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