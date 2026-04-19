import math
from drift.core.helpers import clamp

# ---------------------------------------------------------------------------
#  Tuning constants  (defaults -- overridden per-drivetrain below)
# ---------------------------------------------------------------------------

TARGET_DRIFT_ANGLE = math.radians(35.0)   # desired sustained slip angle
MAX_DRIFT_ANGLE    = math.radians(55.0)   # absolute cap before recovery kicks in

# Steering PID (angle keeper)
STEER_KP = 2.8       # proportional gain on slip-angle error
STEER_KD = 0.45      # derivative gain (damps yaw oscillation)

# Throttle PID (radius keeper)
THROTTLE_KP = 0.012  # proportional gain on lateral error (pixels)
THROTTLE_KD = 0.004  # derivative gain on lateral error rate

# Transition thresholds
CURVATURE_DRIFT_THRESHOLD  = 0.006   # curvature (1/px) to start drifting
CURVATURE_STRAIGHT_THRESHOLD = 0.002 # curvature below which we straighten out
COUNTER_STEER_YAW_RATE     = 4.5     # rad/s angular velocity spin threshold

# Handbrake tap timing
HB_TAP_DURATION  = 0.06   # seconds the handbrake is held per tap
HB_TAP_COOLDOWN  = 0.25   # minimum seconds between taps
HB_TAP_STRENGTH  = 1.0    # handbrake intensity during a tap (0-1)

# Lookahead distances along the polyline
LOOKAHEAD_BASE        = 250.0  # primary target point (same as old AI)
LOOKAHEAD_CURVATURE   = 500.0  # further ahead for curvature sensing
LOOKAHEAD_SHORT       = 120.0  # short lookahead for tight corrections

# Throttle limits
THROTTLE_BASE_DRIFT   = 0.65   # base throttle while drifting
THROTTLE_BASE_GRIP    = 0.85   # base throttle in straight-line mode
THROTTLE_MIN          = 0.08   # never fully lift (keeps momentum)
THROTTLE_MAX          = 1.0

# Drift angle fade speeds (rad/s)
DRIFT_ANGLE_RAMP_UP   = 2.5    # how fast targetDriftAngle ramps to full
DRIFT_ANGLE_RAMP_DOWN  = 3.5   # how fast it fades on straights

# ---------------------------------------------------------------------------
#  Per-drivetrain tuning profiles
# ---------------------------------------------------------------------------
# Each profile overrides the defaults above where the drivetrain behaves
# differently.  Values not listed use the module-level defaults.

_DRIVETRAIN_PROFILES = {
    "RWD": {
        "target_drift_angle": math.radians(38.0),
        "steer_kp": 2.8,
        "steer_kd": 0.45,
        "throttle_base_drift": 0.60,
        "throttle_kp": 0.012,
        "curvature_drift": 0.006,
        "hb_tap_duration": 0.06,
        "hb_tap_cooldown": 0.25,
        "initiate_steer_offset": math.radians(15.0),
        "initiate_throttle": 0.55,
        # RWD breaks traction via throttle+handbrake easily
    },
    "FWD": {
        "target_drift_angle": math.radians(25.0),
        "steer_kp": 3.2,
        "steer_kd": 0.50,
        "throttle_base_drift": 0.50,
        "throttle_kp": 0.010,
        "curvature_drift": 0.007,
        "hb_tap_duration": 0.08,
        "hb_tap_cooldown": 0.20,
        "initiate_steer_offset": math.radians(20.0),
        "initiate_throttle": 0.40,
        # FWD relies more on handbrake; limited drift angle
    },
    "AWD": {
        "target_drift_angle": math.radians(30.0),
        "steer_kp": 3.0,
        "steer_kd": 0.50,
        "throttle_base_drift": 0.55,
        "throttle_kp": 0.011,
        "curvature_drift": 0.005,
        "hb_tap_duration": 0.07,
        "hb_tap_cooldown": 0.18,
        "initiate_steer_offset": math.radians(18.0),
        "initiate_throttle": 0.60,
        # AWD needs more aggressive taps but recovers quicker
    },
    "AWDS": {
        "target_drift_angle": math.radians(32.0),
        "steer_kp": 3.0,
        "steer_kd": 0.48,
        "throttle_base_drift": 0.58,
        "throttle_kp": 0.011,
        "curvature_drift": 0.005,
        "hb_tap_duration": 0.07,
        "hb_tap_cooldown": 0.18,
        "initiate_steer_offset": math.radians(18.0),
        "initiate_throttle": 0.60,
    },
}


def _get_profile(drivetrain):
    """Return the tuning profile dict for the given drivetrain string."""
    return _DRIVETRAIN_PROFILES.get(drivetrain, _DRIVETRAIN_PROFILES["RWD"])


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

def _angle_diff(a, b):
    """Signed shortest difference a - b, wrapped to [-pi, pi]."""
    return ((a - b + math.pi) % (2.0 * math.pi)) - math.pi


def _proj_on_segment(px, py, ax, ay, bx, by):
    """Project point (px,py) onto segment (a->b). Returns (cx,cy,t)."""
    vx, vy = bx - ax, by - ay
    denom = vx * vx + vy * vy
    if denom < 1e-12:
        return ax, ay, 0.0
    t = clamp(((px - ax) * vx + (py - ay) * vy) / denom, 0.0, 1.0)
    return ax + vx * t, ay + vy * t, t


def _walk_along_path(path_poly, seg_idx, t_on_seg, distance):
    """Walk *distance* units forward along the polyline from (seg_idx, t).
    Returns (x, y, final_seg_idx)."""
    remaining = distance
    idx = seg_idx
    t = clamp(t_on_seg, 0.0, 0.999999)
    n = len(path_poly)
    cx, cy = 0.0, 0.0

    while remaining > 0:
        if idx >= n - 1:
            idx = 0
            t = 0.0
        a = path_poly[idx]
        b = path_poly[idx + 1]
        vx, vy = b[0] - a[0], b[1] - a[1]
        seg_len = math.hypot(vx, vy)
        if seg_len < 1e-6:
            idx += 1
            t = 0.0
            continue
        dist_to_end = (1.0 - t) * seg_len
        if remaining <= dist_to_end + 1e-6:
            frac = (t * seg_len + remaining) / seg_len
            cx = a[0] + vx * frac
            cy = a[1] + vy * frac
            remaining = 0.0
        else:
            remaining -= dist_to_end
            idx = (idx + 1) % (n - 1) if idx + 1 < n - 1 else 0
            t = 0.0
            cx, cy = b[0], b[1]

    return cx, cy, idx


def _path_tangent_at(path_poly, seg_idx):
    """Unit tangent vector at the given segment index."""
    n = len(path_poly)
    if n < 2:
        return 1.0, 0.0
    a = path_poly[seg_idx % (n - 1)]
    b = path_poly[(seg_idx + 1) % n]
    dx, dy = b[0] - a[0], b[1] - a[1]
    l = math.hypot(dx, dy)
    if l < 1e-12:
        return 1.0, 0.0
    return dx / l, dy / l


# ---------------------------------------------------------------------------
#  DriftAI  -- stateful per-car controller
# ---------------------------------------------------------------------------

class DriftAI:
    """PID-based sustained-drift AI controller.

    Outputs raw (th, st, br) controls identical to what a human player would
    produce -- goes through the same target_angle accumulation pipeline in
    car.step().  No direct target_angle writes, no unfair advantage.

    Adapts behaviour based on the car's drivetrain (RWD / FWD / AWD / AWDS).
    br = handbrake (short taps only), negative th = actual brakes.
    """

    def __init__(self):
        # Drift phase: "grip" | "initiate" | "drift" | "recover"
        self.phase = "grip"
        self.initiation_timer = 0.0

        # Active drift angle (ramped toward target)
        self.active_drift_angle = 0.0
        self.drift_direction = 0  # +1 left, -1 right, 0 undecided

        # PID memory
        self.prev_lateral_error = 0.0

        # Path tracking hint (avoids O(n) search every frame)
        self._seg_hint = 0

        # Handbrake tap state
        self._hb_tap_active = False   # currently in a tap?
        self._hb_tap_timer = 0.0      # time remaining in current tap
        self._hb_cooldown = 0.0       # cooldown before next tap allowed

        # Cached drivetrain string + profile (refreshed lazily)
        self._drivetrain = None
        self._profile = _get_profile("RWD")

        # Debug snapshot -- populated every compute() call for visualization
        self.dbg = {
            "slip_angle": 0.0,
            "angular_vel": 0.0,
            "curvature": 0.0,
            "lateral_error": 0.0,
            "signed_perp_dist": 0.0,
            "speed": 0.0,
            "la_x": 0.0, "la_y": 0.0,           # primary lookahead
            "la_far_x": 0.0, "la_far_y": 0.0,   # curvature lookahead
            "la_short_x": 0.0, "la_short_y": 0.0,# short lookahead
            "near_x": 0.0, "near_y": 0.0,        # nearest point on path
            "tan_angle": 0.0,
            "desired_heading": 0.0,
            "turn_dir": 0,
            "seg_width": 200.0,
            "controls": {"th": 0.0, "st": 0.0, "br": 0.0},
        }

    # ------------------------------------------------------------------
    #  Public entry point
    # ------------------------------------------------------------------

    def compute(self, path_poly, car, dt):
        """Compute controls for one physics tick.

        Parameters
        ----------
        path_poly : list[(x, y, width?)]
        car       : Car instance (read-only -- we never write car state)
        dt        : float  seconds

        Returns
        -------
        dict  {"th": float, "st": float, "br": float}
        """
        if not path_poly or len(path_poly) < 3:
            return {"th": 0.1, "st": 0.0, "br": 0.0}

        # -- 0. Refresh drivetrain profile if car changed -----------------
        car_dt = getattr(car, "_cached_specs_vals", {}).get("DRIVETRAIN", "RWD")
        if car_dt != self._drivetrain:
            self._drivetrain = car_dt
            self._profile = _get_profile(car_dt)
        prof = self._profile

        # -- 1. Project onto path ----------------------------------------
        px, py = car.x, car.y
        best_d2 = float("inf")
        best_idx = 0
        best_t = 0.0

        # Local search around hint for speed
        n = len(path_poly)
        search_lo = max(0, self._seg_hint - 30)
        search_hi = min(n - 1, self._seg_hint + 60)
        for i in range(search_lo, search_hi):
            ax, ay = path_poly[i][0], path_poly[i][1]
            bx, by = path_poly[i + 1][0], path_poly[i + 1][1]
            cx, cy, t = _proj_on_segment(px, py, ax, ay, bx, by)
            d2 = (px - cx) ** 2 + (py - cy) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best_idx = i
                best_t = t

        # Fallback: full scan if hint was stale (wrap-around or teleport)
        if best_d2 > 200.0 ** 2:
            for i in range(n - 1):
                ax, ay = path_poly[i][0], path_poly[i][1]
                bx, by = path_poly[i + 1][0], path_poly[i + 1][1]
                cx, cy, t = _proj_on_segment(px, py, ax, ay, bx, by)
                d2 = (px - cx) ** 2 + (py - cy) ** 2
                if d2 < best_d2:
                    best_d2 = d2
                    best_idx = i
                    best_t = t

        self._seg_hint = best_idx
        dist_to_path = math.sqrt(best_d2)

        # Track width at current segment
        seg_width = (path_poly[best_idx][2]
                     if len(path_poly[best_idx]) > 2 else 200.0)

        # -- 2. Lookahead points -----------------------------------------
        speed = math.hypot(car.vx, car.vy)
        # Scale lookahead with speed so AI looks further at high speed
        speed_factor = clamp(speed / 200.0, 0.5, 1.5)

        la_x, la_y, la_idx = _walk_along_path(
            path_poly, best_idx, best_t, LOOKAHEAD_BASE * speed_factor)
        la_far_x, la_far_y, la_far_idx = _walk_along_path(
            path_poly, best_idx, best_t, LOOKAHEAD_CURVATURE * speed_factor)
        la_short_x, la_short_y, _ = _walk_along_path(
            path_poly, best_idx, best_t, LOOKAHEAD_SHORT)

        # -- 3. Path tangent and curvature --------------------------------
        tan_x, tan_y = _path_tangent_at(path_poly, la_idx)
        tan_angle = math.atan2(tan_y, tan_x)

        tan_far_x, tan_far_y = _path_tangent_at(path_poly, la_far_idx)
        tan_far_angle = math.atan2(tan_far_y, tan_far_x)

        # Curvature ~ |delta_tangent_angle| / arc_length
        delta_tan = abs(_angle_diff(tan_far_angle, tan_angle))
        arc_len = max(
            (LOOKAHEAD_CURVATURE - LOOKAHEAD_BASE) * speed_factor, 50.0)
        curvature = delta_tan / arc_len

        # Turn direction from path curvature (cross product of tangents)
        cross_tan = tan_x * tan_far_y - tan_y * tan_far_x
        upcoming_turn_dir = 1 if cross_tan > 0 else (-1 if cross_tan < 0 else 0)

        # -- 4. Car state vectors ----------------------------------------
        fwd_x = math.cos(car.angle)
        fwd_y = math.sin(car.angle)
        right_x, right_y = -fwd_y, fwd_x

        body_fwd   = car.vx * fwd_x + car.vy * fwd_y
        body_lat   = car.vx * right_x + car.vy * right_y

        # Slip angle (beta): angle between heading and velocity
        if speed > 2.0:
            slip_angle = math.atan2(-body_lat, abs(body_fwd))
        else:
            slip_angle = 0.0

        angular_vel = car.v_angle  # rad/s yaw rate

        # -- 5. Lateral error (signed) -----------------------------------
        # Vector from car to lookahead target
        to_la_x = la_x - px
        to_la_y = la_y - py
        # Cross product: positive = target is to the left
        lateral_error = to_la_x * fwd_y - to_la_y * fwd_x

        # Also compute the perpendicular distance to the path centerline
        near_cx, near_cy, _ = _proj_on_segment(
            px, py,
            path_poly[best_idx][0], path_poly[best_idx][1],
            path_poly[min(best_idx + 1, n - 1)][0],
            path_poly[min(best_idx + 1, n - 1)][1])
        perp_dx = px - near_cx
        perp_dy = py - near_cy
        # Sign via cross product with tangent
        perp_cross = tan_x * perp_dy - tan_y * perp_dx
        signed_perp_dist = math.copysign(dist_to_path, perp_cross)

        # -- 6. Phase transitions ----------------------------------------
        self._update_phase(curvature, slip_angle, angular_vel, speed,
                           upcoming_turn_dir, signed_perp_dist, seg_width,
                           prof, dt)

        # -- 6b. Handbrake tap timer -------------------------------------
        self._hb_cooldown = max(0.0, self._hb_cooldown - dt)
        if self._hb_tap_active:
            self._hb_tap_timer -= dt
            if self._hb_tap_timer <= 0:
                self._hb_tap_active = False
                self._hb_cooldown = prof.get("hb_tap_cooldown", HB_TAP_COOLDOWN)

        # -- 7. Compute controls per phase -------------------------------
        st = 0.0
        th = 0.0
        br = 0.0

        if self.phase == "grip":
            st, th, br = self._grip_controls(
                car, px, py, la_x, la_y, la_short_x, la_short_y,
                tan_angle, speed, lateral_error, dist_to_path, seg_width,
                prof, dt)

        elif self.phase == "initiate":
            st, th, br = self._initiate_controls(
                car, tan_angle, upcoming_turn_dir, speed, prof, dt)

        elif self.phase == "drift":
            st, th, br = self._drift_controls(
                car, slip_angle, angular_vel, lateral_error,
                signed_perp_dist, seg_width, tan_angle, speed, prof, dt)

        elif self.phase == "recover":
            st, th, br = self._recover_controls(
                car, slip_angle, angular_vel, tan_angle, speed,
                lateral_error, prof, dt)

        # Clamp final outputs
        st = clamp(st, -1.0, 1.0)
        th = clamp(th, -1.0, 1.0)
        br = clamp(br, 0.0, 1.0)

        self.prev_lateral_error = lateral_error

        # -- 8. Populate debug snapshot ----------------------------------
        d = self.dbg
        d["slip_angle"] = slip_angle
        d["angular_vel"] = angular_vel
        d["curvature"] = curvature
        d["lateral_error"] = lateral_error
        d["signed_perp_dist"] = signed_perp_dist
        d["speed"] = speed
        d["la_x"] = la_x;  d["la_y"] = la_y
        d["la_far_x"] = la_far_x;  d["la_far_y"] = la_far_y
        d["la_short_x"] = la_short_x;  d["la_short_y"] = la_short_y
        d["near_x"] = near_cx;  d["near_y"] = near_cy
        d["tan_angle"] = tan_angle
        d["turn_dir"] = upcoming_turn_dir
        d["seg_width"] = seg_width
        d["controls"] = {"th": th, "st": st, "br": br}

        return {"th": th, "st": st, "br": br}

    # ------------------------------------------------------------------
    #  Phase state machine
    # ------------------------------------------------------------------

    def _update_phase(self, curvature, slip_angle, angular_vel, speed,
                      turn_dir, signed_perp_dist, seg_width, prof, dt):
        abs_slip = abs(slip_angle)
        abs_yaw = abs(angular_vel)
        curv_thresh = prof.get("curvature_drift", CURVATURE_DRIFT_THRESHOLD)

        if self.phase == "grip":
            # Transition to initiate when a sharp turn is coming and we have speed
            if (curvature > curv_thresh
                    and speed > 60.0
                    and turn_dir != 0):
                self.phase = "initiate"
                # Start handbrake tap immediately
                tap_dur = prof.get("hb_tap_duration", HB_TAP_DURATION)
                self.initiation_timer = tap_dur
                self._hb_tap_active = True
                self._hb_tap_timer = tap_dur
                self._hb_cooldown = 0.0
                self.drift_direction = turn_dir
                self.active_drift_angle = 0.0

        elif self.phase == "initiate":
            self.initiation_timer -= dt
            if self.initiation_timer <= 0:
                # Tap is over -- check if we broke traction
                if abs_slip > math.radians(8.0):
                    self.phase = "drift"
                else:
                    # Not enough slip -- allow a second tap if cooldown allows
                    if self._hb_cooldown <= 0 and speed > 40.0:
                        tap_dur = prof.get("hb_tap_duration", HB_TAP_DURATION)
                        self.initiation_timer = tap_dur
                        self._hb_tap_active = True
                        self._hb_tap_timer = tap_dur
                    else:
                        self.phase = "grip"

        elif self.phase == "drift":
            # Spin-out detection
            if abs_yaw > COUNTER_STEER_YAW_RATE and abs_slip > MAX_DRIFT_ANGLE:
                self.phase = "recover"
            # Curvature dropped -- straighten out
            elif curvature < CURVATURE_STRAIGHT_THRESHOLD and abs_slip < math.radians(10.0):
                self.phase = "grip"
                self.active_drift_angle = 0.0
                self.drift_direction = 0
            # Off-track detection
            elif abs(signed_perp_dist) > seg_width * 0.55:
                self.phase = "recover"
            # Update drift direction if the turn direction changed significantly
            if turn_dir != 0 and turn_dir != self.drift_direction:
                # Upcoming opposite turn -- start winding down
                if curvature > CURVATURE_DRIFT_THRESHOLD:
                    self.drift_direction = turn_dir

        elif self.phase == "recover":
            # Recovered once slip angle drops and yaw calms
            if abs_slip < math.radians(12.0) and abs_yaw < 1.5:
                self.phase = "grip"
                self.active_drift_angle = 0.0
                self.drift_direction = 0

    # ------------------------------------------------------------------
    #  Controls per phase
    # ------------------------------------------------------------------

    def _grip_controls(self, car, px, py, la_x, la_y, la_short_x, la_short_y,
                       tan_angle, speed, lateral_error, dist_to_path,
                       seg_width, prof, dt):
        """Normal path following -- no drifting."""
        # Aim toward the lookahead point
        dx = la_x - px
        dy = la_y - py
        desired_angle = math.atan2(dy, dx)
        angle_err = _angle_diff(desired_angle, car.angle)

        # Steering proportional to angle error
        st = clamp(angle_err * 2.5, -1.0, 1.0)

        # Throttle: reduce for large angle errors
        angle_penalty = clamp(abs(angle_err) * speed / 200.0, 0.0, 0.7)
        th = THROTTLE_BASE_GRIP - angle_penalty
        th = clamp(th, THROTTLE_MIN, THROTTLE_MAX)

        # Use negative throttle for actual braking when way off heading
        br = 0.0
        if abs(angle_err) > math.radians(40.0) and speed > 80.0:
            brake_amount = clamp(abs(angle_err) * speed / 500.0 - 0.15, 0.0, 0.6)
            th = -brake_amount  # negative throttle = real brakes

        return st, th, br

    def _initiate_controls(self, car, tan_angle, turn_dir, speed, prof, dt):
        """Break traction with a handbrake tap to start the drift."""
        steer_offset = prof.get("initiate_steer_offset", math.radians(15.0))
        desired_angle = tan_angle + turn_dir * steer_offset
        angle_err = _angle_diff(desired_angle, car.angle)
        st = clamp(angle_err * 3.0, -1.0, 1.0)

        init_th = prof.get("initiate_throttle", 0.55)
        th = clamp(init_th + 0.2 * (speed < 100.0), 0.0, 0.9)

        # Handbrake: only during active tap, otherwise 0
        br = HB_TAP_STRENGTH if self._hb_tap_active else 0.0

        return st, th, br

    def _drift_controls(self, car, slip_angle, angular_vel, lateral_error,
                        signed_perp_dist, seg_width, tan_angle, speed, prof, dt):
        """Sustained drift -- PID on slip angle (steering) and lateral
        error (throttle).  Uses drivetrain-specific gains."""

        target_da = prof.get("target_drift_angle", TARGET_DRIFT_ANGLE)
        p_steer_kp = prof.get("steer_kp", STEER_KP)
        p_steer_kd = prof.get("steer_kd", STEER_KD)
        p_throttle_kp = prof.get("throttle_kp", THROTTLE_KP)
        p_throttle_base = prof.get("throttle_base_drift", THROTTLE_BASE_DRIFT)

        # Ramp active drift angle toward target
        target = target_da * (1 if self.drift_direction != 0 else 0)
        if self.active_drift_angle < target:
            self.active_drift_angle = min(
                self.active_drift_angle + DRIFT_ANGLE_RAMP_UP * dt, target)
        elif self.active_drift_angle > target:
            self.active_drift_angle = max(
                self.active_drift_angle - DRIFT_ANGLE_RAMP_DOWN * dt, target)

        # ------ Steering PID (angle keeper) ------
        desired_heading = tan_angle + self.drift_direction * self.active_drift_angle
        heading_error = _angle_diff(desired_heading, car.angle)

        st_p = heading_error * p_steer_kp
        st_d = -angular_vel * p_steer_kd
        st = st_p + st_d

        # Counter-steer override: if yaw rate is dangerously high
        if abs(angular_vel) > COUNTER_STEER_YAW_RATE * 0.75:
            overshoot = abs(angular_vel) - COUNTER_STEER_YAW_RATE * 0.75
            counter = -math.copysign(overshoot * 0.8, angular_vel)
            st += counter

        # ------ Throttle PID (radius keeper) ------
        off_center = signed_perp_dist
        lat_d = (lateral_error - self.prev_lateral_error) / max(dt, 1e-4)

        th_adjust = -off_center * p_throttle_kp - lat_d * THROTTLE_KD
        th = p_throttle_base + th_adjust

        abs_slip = abs(slip_angle)
        if abs_slip > MAX_DRIFT_ANGLE * 0.85:
            th *= 0.4

        if abs_slip < self.active_drift_angle * 0.5 and speed > 40.0:
            th += 0.15

        th = clamp(th, THROTTLE_MIN, THROTTLE_MAX)
        br = 0.0

        # If slip angle collapsed mid-drift, request a handbrake tap
        # (not a sustained hold) to re-break traction.
        if (abs_slip < math.radians(5.0)
                and speed > 50.0
                and self.active_drift_angle > math.radians(10.0)):
            if not self._hb_tap_active and self._hb_cooldown <= 0:
                tap_dur = prof.get("hb_tap_duration", HB_TAP_DURATION)
                self._hb_tap_active = True
                self._hb_tap_timer = tap_dur
            # Reduce throttle during the tap to avoid fighting the lock
            if self._hb_tap_active:
                th = clamp(th * 0.5, THROTTLE_MIN, 0.4)

        # Apply handbrake only during active tap
        if self._hb_tap_active:
            br = HB_TAP_STRENGTH

        return st, th, br

    def _recover_controls(self, car, slip_angle, angular_vel, tan_angle,
                          speed, lateral_error, prof, dt):
        """Counter-steer and modulate throttle to recover from a spin."""
        # Aim back toward path tangent
        heading_error = _angle_diff(tan_angle, car.angle)
        st = heading_error * 2.0 - angular_vel * 0.6

        # Use negative throttle for actual braking during recovery
        brake_amount = clamp(abs(angular_vel) * 0.15 - 0.1, 0.0, 0.6)
        th = clamp(0.15 - abs(slip_angle) * 0.3 - brake_amount, -0.6, 0.3)
        br = 0.0  # no handbrake during recovery (would make spin worse)

        return st, th, br
