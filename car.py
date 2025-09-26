import math

# world
WINDOW_WIDTH, WINDOW_HEIGHT = 1000, 700
TRACK_MARGIN = 40

# car
CAR_LEN = 58.0
CAR_WID  = 30.0
ENGINE_ACC      = 950.0
#REVERSE_ACC     = 700.0
#BRAKE_DECEL     = 1400.0
#DRAG            = 0.35
#ROLLING         = 1.6
LATERAL_GRIP    = 10
STEER_SENS      = 1/50
#DRIFT_SENS      = 1/8000
OVERSTEER       = 1.5/100
#MAX_SPEED       = 1200.0
WALL_RESTITUTION = 0.3
#ANGLE_DAMP      = 25

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

class Car:
    __slots__ = ("x", "y", "vx", "vy", "angle", "v_angle", "name", "drift_ratio")
    def __init__(self, x, y, name):
        self.x, self.y = float(x), float(y)
        self.vx, self.vy = 0.0, 0.0
        self.angle = 0.0
        self.v_angle = 0.0
        self.name = name
        self.drift_ratio = 0 

    def step(self, inputs, dt, players):
        th = clamp(inputs.get("th", 0.0), -1.0, 1.0)
        st = clamp(inputs.get("st", 0.0), -1.0, 1.0)
        br = inputs.get("br", 0.0)

        fx, fy = math.cos(self.angle), math.sin(self.angle)
        rx, ry = -fy, fx

        v_forward = self.vx * fx + self.vy * fy
        v_lateral = self.vx * rx + self.vy * ry
        
        self.drift_ratio = clamp(abs(v_lateral)/200, 0, 1)

        a_forward = th * ENGINE_ACC
        a_lateral = -v_lateral * LATERAL_GRIP * (1-self.drift_ratio/2) * (1-br)
        
        acc_fx = fx * a_forward + rx * a_lateral
        acc_fy = fy * a_forward + ry * a_lateral
        
        acc_fx += -self.vx - self.vx*br
        acc_fy += -self.vy - self.vy*br
        
        self.vx += acc_fx * dt
        self.vy += acc_fy * dt
        self.x  += self.vx * dt
        self.y  += self.vy * dt

        drift_moment = (STEER_SENS * st * math.copysign(v_forward, th) + (OVERSTEER * -self.v_angle))
        drift_moment +=  math.copysign(self.v_angle/100, st)
        self.v_angle += drift_moment
        
        self.angle += ((STEER_SENS * st * v_forward)*(1-self.drift_ratio) + self.v_angle*self.drift_ratio * dt) * dt

        self._handle_track_bounds(dt)

        for pid, d in players.items():
            if d["name"] == self.name:
                continue
            dx = d["x"] - self.x
            dy = d["y"] - self.y
            dist2 = dx * dx + dy * dy
            if dist2 < (CAR_LEN * CAR_LEN):
                self._handle_collision(dx, dy, dist2)
    
    def _handle_track_bounds(self, dt):
        minx, maxx = TRACK_MARGIN, WINDOW_WIDTH - TRACK_MARGIN
        miny, maxy = TRACK_MARGIN, WINDOW_HEIGHT - TRACK_MARGIN
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

    def _handle_collision(self, dx, dy, dist2):
        dist = math.sqrt(dist2) if dist2 > 0 else 0.01
        overlap = (CAR_LEN - dist) / 2.0
        self.x -= (dx / dist) * overlap*0.9
        self.y -= (dy / dist) * overlap*0.9
        self.vx -= (dx / dist) * overlap * 5
        self.vy -= (dy / dist) * overlap * 5