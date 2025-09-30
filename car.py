import math

# world
WINDOW_WIDTH, WINDOW_HEIGHT = 1000, 700
TRACK_MARGIN = 40

# car
CAR_LEN = 38.0
CAR_WID  = 20.0
ENGINE_ACC      = 450.0
#REVERSE_ACC     = 700.0
#BRAKE_DECEL     = 1400.0
#DRAG            = 0.35
#ROLLING         = 1.6
LATERAL_GRIP    = 4
STEER_SENS      = 1/50
#DRIFT_SENS      = 1/8000
OVERSTEER       = 1.5/100
#MAX_SPEED       = 1200.0
WALL_RESTITUTION = 0.3
#ANGLE_DAMP      = 25

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

class Car:
    __slots__ = ("x", "y", "vx", "vy", "angle", "v_angle", "name", "drift_ratio", "is_ai", "drift_points", "drift_points_old")
    def __init__(self, x, y, name, is_ai=False):
        self.x, self.y = float(x), float(y)
        self.vx, self.vy = 0.0, 0.0
        self.angle = 0.0
        self.v_angle = 0.0
        self.name = name
        self.drift_ratio = 0 
        self.is_ai = is_ai
        self.drift_points = [(0,0),(0,0)]
        self.drift_points_old = [(0,0),(0,0)]

    def step(self, inputs, dt, players, bounds):
        th = clamp(inputs.get("th", 0.0), -1.0, 1.0)
        st = clamp(inputs.get("st", 0.0), -1.0, 1.0)
        br = inputs.get("br", 0.0)

        fx, fy = math.cos(self.angle), math.sin(self.angle)
        rx, ry = -fy, fx

        v_forward = self.vx * fx + self.vy * fy
        v_lateral = self.vx * rx + self.vy * ry
        
        vel_vec = (v_forward/math.sqrt(v_forward**2+v_lateral**2+1e-4),
                   v_lateral/math.sqrt(v_forward**2+v_lateral**2+1e-4))
        
        angle = ((math.atan2(vel_vec[0], vel_vec[1])-math.pi/2 + math.pi)%(2*math.pi) - math.pi) * clamp(abs(v_forward)-10, 0, 1)
        
        self.drift_ratio = clamp(abs(angle), 0, 1)

        a_forward = th * ENGINE_ACC
        a_lateral = -v_lateral * LATERAL_GRIP * (1-self.drift_ratio/2) * (1-br)
        
        acc_fx = fx * a_forward + rx * a_lateral
        acc_fy = fy * a_forward + ry * a_lateral
        
        acc_fx += -self.vx - self.vx*br
        acc_fy += -self.vy - self.vy*br
        
        self.vx += acc_fx/1.2 * dt
        self.vy += acc_fy/1.2 * dt
        self.x  += self.vx * dt
        self.y  += (self.vy * dt)*math.sqrt(2) # compensate for isometric view at 45deg

        drift_moment = (STEER_SENS * st * math.copysign(v_forward, th) + (OVERSTEER * -self.v_angle))
        drift_moment +=  math.copysign(self.v_angle/100, st)
        self.v_angle += drift_moment
        
        self.angle += ((STEER_SENS * st * v_forward)*(1-self.drift_ratio) + self.v_angle*self.drift_ratio * dt) * dt

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