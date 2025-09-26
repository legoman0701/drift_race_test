#!/usr/bin/env python3
"""
Top-down drift game client (client-trust network via Pi relay)
Refactored to remove magic numbers and reduce spaghetti code.
"""

import pygame, socket, json, time, random, string, sys, math, uuid, argparse

# ======= CONFIGURATION =======
# Relay endpoint
RELAY_PUBLIC_ENDPOINT = "william-allow.gl.at.ply.gg:4800"

# Window and track settings
WINDOW_WIDTH, WINDOW_HEIGHT = 1000, 700
TRACK_MARGIN = 40
TRACK_COLOR = (35, 40, 50)
TRACK_BORDER_COLOR = (80, 90, 100)
TRACK_BORDER_WIDTH = 4

# Gameplay rates
FPS = 75
SEND_HZ = 60.0       # client -> relay state rate
PING_HZ = 1/5        # keepalive (~5 s)

# Join room code parameters
JOIN_CODE_LEN = 4
ROOM_ALPHABET = string.ascii_uppercase + string.digits
MAX_CODE_LENGTH = 12

# Car constants
CAR_LEN = 58.0
CAR_WID  = 30.0
ENGINE_ACC      = 950.0
REVERSE_ACC     = 700.0
BRAKE_DECEL     = 1400.0
DRAG            = 0.35
ROLLING         = 1.6
LATERAL_GRIP    = 3.2
STEER_SENS      = 1/50
DRIFT_SENS      = 1/8000
OVERSTEER       = 1.5/100
MAX_SPEED       = 1200.0
WALL_RESTITUTION = 0.3
ANGLE_DAMP      = 25

# Input repetition settings
KEY_REPEAT_DELAY = 250
KEY_REPEAT_INTERVAL = 35

# Name input
MIN_NAME_LENGTH = 3
MAX_NAME_LENGTH = 12
PROFANITY_SET = {"NIGGER", "NIGGA", "NIGA"}

# Colors
BLACK = (0, 0, 0)
GREY_20 = (20,20,28)
GREY_180 = (180, 180, 180)
GREY_200 = (200, 200, 200)
WHITE_240 = (240,240,240)
WHITE = (255, 255, 255)

COLOR_BODY_DEFAULT = (250,210,120)
COLOR_NOSE_DEFAULT = (255,120,120)
COLOR_BODY_REMOTE  = (255,200,120)
COLOR_MY_CAR       = (200,230,255)

# =============================

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

def rand_code(n=JOIN_CODE_LEN):
    return "".join(random.choice(ROOM_ALPHABET) for _ in range(n))

def rand_name():
    return "Player" + "".join(random.choice(string.digits) for _ in range(4))

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
        # Unpack input controls
        th = clamp(inputs.get("th", 0.0), -1.0, 1.0)
        st = clamp(inputs.get("st", 0.0), -1.0, 1.0)
        br = 1.0 if inputs.get("br", 0.0) else 0.0

        # Calculate forward and lateral axes
        fx, fy = math.cos(self.angle), math.sin(self.angle)
        rx, ry = -fy, fx

        # Get current velocity components
        v_forward = self.vx * fx + self.vy * fy
        v_lateral = self.vx * rx + self.vy * ry

        # Compute accelerations
        a_forward = th * ENGINE_ACC
        a_lateral = -v_lateral * LATERAL_GRIP
        
        # Update acceleration in world coordinates
        acc_fx = fx * a_forward + rx * a_lateral
        acc_fy = fy * a_forward + ry * a_lateral
        
        self.vx += acc_fx * dt
        self.vy += acc_fy * dt
        self.x  += self.vx * dt
        self.y  += self.vy * dt

        # Update angular velocity and angle
        drift_moment = (STEER_SENS * st * math.copysign(v_forward, th) + (OVERSTEER * -self.v_angle))
        drift_moment +=  math.copysign(self.v_angle/100, st)
        
        self.drift_ratio = clamp(abs(v_lateral)/200, 0, 1)
        
        self.v_angle += drift_moment
        
        self.angle += ((STEER_SENS * st * v_forward)*(1-self.drift_ratio) + self.v_angle*self.drift_ratio * dt) * dt

        # Check track boundaries
        self._handle_track_bounds(dt)

        # Collision with other players (simplified circle overlap)
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

def draw_car(surface, x, y, angle, name,
             color_body=COLOR_BODY_DEFAULT,
             color_nose=COLOR_NOSE_DEFAULT):
    ca, sa = math.cos(angle), math.sin(angle)
    halfL, halfW = CAR_LEN * 0.5, CAR_WID * 0.5
    # Car rectangle points
    pts = [(+halfL, +halfW),
           (+halfL, -halfW),
           (-halfL, -halfW),
           (-halfL, +halfW)]
    wpts = []
    for px, py in pts:
        rx = px * ca - py * sa
        ry = px * sa + py * ca
        wpts.append((int(x + rx), int(y + ry)))
    pygame.draw.polygon(surface, color_body, wpts)
    # Draw the nose
    nose = (x + ca * halfL, y + sa * halfL)
    lft = (x + ca * (halfL * 0.4) - sa * (halfW * 0.9),
           y + sa * (halfL * 0.4) + ca * (halfW * 0.9))
    rgt = (x + ca * (halfL * 0.4) + sa * (halfW * 0.9),
           y + sa * (halfL * 0.4) - ca * (halfW * 0.9))
    pygame.draw.polygon(surface, color_nose,
                        [(int(nose[0]), int(nose[1])),
                         (int(lft[0]), int(lft[1])),
                         (int(rgt[0]), int(rgt[1]))])
    if name:
        font = pygame.font.SysFont(None, 22)
        text = font.render(name, True, (230,230,255))
        surface.blit(text, (int(x) + 12, int(y) - 10))

    return (wpts[2], wpts[3])  # return rear left and right points

def draw_track(surface):
    pygame.draw.rect(surface, TRACK_COLOR, (0,0,WINDOW_WIDTH,WINDOW_HEIGHT))
    pygame.draw.rect(surface, TRACK_BORDER_COLOR,
                     (TRACK_MARGIN, TRACK_MARGIN,
                      WINDOW_WIDTH - 2 * TRACK_MARGIN,
                      WINDOW_HEIGHT - 2 * TRACK_MARGIN),
                     width=TRACK_BORDER_WIDTH)

def recv_jsons(sock):
    msgs = []
    while True:
        try:
            data = sock.recv(8192)
            if not data:
                break
            try:
                msgs.append(json.loads(data.decode("utf-8")))
            except Exception:
                pass
        except BlockingIOError:
            break
        except Exception:
            break
    return msgs

def connect_to_relay():
    host, port_str = RELAY_PUBLIC_ENDPOINT.rsplit(":", 1)
    port = int(port_str)
    addr_info = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_DGRAM)[0]
    s = socket.socket(*addr_info[:3])
    s.setblocking(False)
    s.connect(addr_info[4])
    return s

def get_text_input(screen, title_text, tip_text, font_big, font_small, allowed_set=None):
    pygame.key.set_repeat(KEY_REPEAT_DELAY, KEY_REPEAT_INTERVAL)
    text = ""
    while True:
        screen.fill((20,20,25))
        draw_track(screen)
        title = font_big.render(title_text, True, (230,230,240))
        screen.blit(title, (WINDOW_WIDTH//2 - title.get_width()//2, WINDOW_HEIGHT//2 - 70))
        disp_text = text if text else "(empty)"
        inp = font_big.render(disp_text, True, (180,255,180))
        screen.blit(inp, (WINDOW_WIDTH//2 - inp.get_width()//2, WINDOW_HEIGHT//2 - 10))
        tip = font_small.render(tip_text, True, (180,180,180))
        screen.blit(tip, (WINDOW_WIDTH//2 - tip.get_width()//2, WINDOW_HEIGHT//2 + 40))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit(0)
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN:
                    return text or None
                if ev.key == pygame.K_ESCAPE:
                    return None
                if ev.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                else:
                    ch = ev.unicode.upper() if allowed_set is not None else ev.unicode
                    if allowed_set is None or (ch in allowed_set):
                        if len(text) < MAX_CODE_LENGTH:
                            text += ch

def get_code_input(screen, font_big, font_small):
    return get_text_input(screen,
                          "Enter ROOM CODE (A-Z/0-9)",
                          "Enter = OK   Esc = cancel",
                          font_big, font_small, allowed_set=ROOM_ALPHABET)

def get_name_input(screen, font_big, font_small):
    pygame.key.set_repeat(KEY_REPEAT_DELAY, KEY_REPEAT_INTERVAL)
    text = ""
    error_msg = ""
    while True:
        screen.fill((20,20,25))
        draw_track(screen)
        title = font_big.render("Enter your name", True, (230,230,240))
        screen.blit(title, (WINDOW_WIDTH//2 - title.get_width()//2, WINDOW_HEIGHT//2 - 70))
        disp_text = text if text else "(empty)"
        inp = font_big.render(disp_text, True, (180,255,180))
        screen.blit(inp, (WINDOW_WIDTH//2 - inp.get_width()//2, WINDOW_HEIGHT//2 - 10))
        tip = font_small.render("Enter : OK  -  Esc : cancel", True, (180,180,180))
        screen.blit(tip, (WINDOW_WIDTH//2 - tip.get_width()//2, WINDOW_HEIGHT//2 + 40))
        if error_msg:
            error_surf = font_big.render(error_msg, True, (230,80,80))
            screen.blit(error_surf, (WINDOW_WIDTH//2 - error_surf.get_width()//2, WINDOW_HEIGHT//2 - 120))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit(0)
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN:
                    if text.upper() in PROFANITY_SET:
                        error_msg = "Inappropriate name. Choose another."
                        continue
                    if len(text) < MIN_NAME_LENGTH:
                        error_msg = "Name must be at least 3 characters long."
                        continue
                    return text
                if ev.key == pygame.K_ESCAPE:
                    return None # switch to menu page
                if ev.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                    error_msg = ""
                else:
                    ch = ev.unicode
                    if (ch.isprintable()) and (len(text) < MAX_NAME_LENGTH):
                        text += ch
                        error_msg = ""

def handle_network_messages(sock, remotes, dt, my_id):
    players = {}
    for msg in recv_jsons(sock):
        t = msg.get("t")
        if t == "join_ok":
            pass
        elif t == "world":
            players = msg.get("players", {}) or {}
            alpha_pos = min(1.0, dt * 10.0)
            alpha_angle = min(1.0, dt * 10.0)
            # Update remote players (smoothing)
            # You can adjust these constants to change the smoothing amount.
            POS_SMOOTHING_MULTIPLIER = 300.0   # Increase for faster positional smoothing
            ANGLE_SMOOTHING_MULTIPLIER = 300.0 # Increase for faster angular smoothing

            alpha_pos = min(1.0, dt * POS_SMOOTHING_MULTIPLIER)
            alpha_angle = min(1.0, dt * ANGLE_SMOOTHING_MULTIPLIER)
            for pid, d in players.items(): # pid: player id
                if pid == my_id:
                    continue
                tx, ty, ta = float(d["x"]), float(d["y"]), float(d["a"])
                name = d.get("name", f"Player{pid}")
                if pid not in remotes:
                    remotes[pid] = {"x": tx, "y": ty, "a": ta, "name": name}
                else:
                    cur = remotes[pid]
                    cur["x"] += (tx - cur["x"]) * alpha_pos
                    cur["y"] += (ty - cur["y"]) * alpha_pos
                    # Angle smoothing with wrap-around
                    da = ((ta - cur["a"] + math.pi) % (2 * math.pi)) - math.pi
                    cur["a"] = (cur["a"] + da * alpha_angle) % (2 * math.pi)
                    cur["name"] = name
            # Remove players that are no longer present
            for pid in list(remotes.keys()):
                if pid not in players:
                    remotes.pop(pid, None)
        elif t == "error":
            return msg.get("msg", "error")
    return None

def send_network_state(sock, code, my_id, car): # send pos and trigger world broadcoast
    pkt = {
        "t": "state",
        "code": code,
        "id": my_id,
        "x": round(car.x, 2),
        "y": round(car.y, 2),
        "a": round(car.angle, 4),
        "vx": round(car.vx, 2),
        "vy": round(car.vy, 2),
        "drift_ratio": round(car.drift_ratio, 2)
    }
    try:
        sock.send(json.dumps(pkt).encode("utf-8"))
    except Exception:
        pass

def send_ping(sock, code):
    try:
        sock.send(json.dumps({"t": "ping", "code": code}).encode("utf-8"))
    except Exception:
        pass

def read_inputs():
    keys = pygame.key.get_pressed()
    th = (keys[pygame.K_z] or keys[pygame.K_UP]) - (keys[pygame.K_s] or keys[pygame.K_DOWN])
    st = (keys[pygame.K_d] or keys[pygame.K_RIGHT]) - (keys[pygame.K_q] or keys[pygame.K_LEFT])
    br = 1.0 if keys[pygame.K_SPACE] else 0.0
    if th != 0:
        th = 1.0 if th > 0 else -1.0
    if st != 0:
        st = 1.0 if st > 0 else -1.0
    return {"th": th, "st": st, "br": br}

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["host", "join"])
    parser.add_argument("--code")
    parser.add_argument("--name")
    args, unknown = parser.parse_known_args()


    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Top-Down Drift — Client Trust (Pi relay)")
    clock = pygame.time.Clock()
    font_small = pygame.font.SysFont(None, 20)
    font_medium = pygame.font.SysFont(None, 30)
    font_big = pygame.font.SysFont(None, 46)

    stage = "menu"  # menu | playing | error
    error_msg = ""
    remotes = {}

    my_name = rand_name()
    my_id = str(uuid.uuid4())[:8]
    code = None
    sock = None
    last_state_send = 0.0
    last_ping = 0.0

    spawnx = random.randint(TRACK_MARGIN + 200, WINDOW_WIDTH - TRACK_MARGIN - 200)
    spawny = random.randint(TRACK_MARGIN + 120, WINDOW_HEIGHT - TRACK_MARGIN - 120)
    my_car = Car(spawnx, spawny, my_name)

    if args.mode == "host" and args.code and args.name:
        my_name = args.name
        my_car.name = my_name
        code = args.code
        try:
            sock = connect_to_relay()
            join_pkt = {"t": "create", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
            stage = "playing"
        except Exception as ex:
            stage = "error"
            error_msg = f"Net error: {ex}"
    elif args.mode == "join" and args.code and args.name:
        my_name = args.name
        my_car.name = my_name
        code = args.code
        try:
            sock = connect_to_relay()
            join_pkt = {"t": "join", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
            join_ok_received = False
            timeout = time.time() + 1.0
            while not join_ok_received and time.time() < timeout:
                for msg in recv_jsons(sock):
                    if msg.get("t") == "join_ok":
                        join_ok_received = True
                        break
            if not join_ok_received:
                raise Exception("Failed to connect: no join confirmation received")
            stage = "playing"
        except Exception as ex:
            stage = "error"
            error_msg = f"Net error: {ex}"

    tire_mark = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT), pygame.SRCALPHA)
    tire_mark.fill((255, 255, 255, 0))

    drift_points_old = []

    while True:
        dt = clock.tick(FPS) / 1000.0
        for ev in pygame.event.get(): # event handling
            if ev.type == pygame.QUIT: # send "bye" packet then quit
                if sock and code:
                    try:
                        sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                    except Exception:
                        pass
                pygame.quit()
                sys.exit(0)
            if stage == "menu" and ev.type == pygame.KEYDOWN: # menu page
                if ev.key == pygame.K_h:  # Host: create room
                    new_name = get_name_input(screen, font_big, font_small) # player enter name
                    if new_name is not None: # save name
                        my_name = new_name
                        my_car.name = my_name
                        code = rand_code() # room code
                        try:
                            sock = connect_to_relay() # connect to relay
                            join_pkt = {"t": "create", "code": code, "name": my_name, "id": my_id} # <-- changed here
                            sock.send(json.dumps(join_pkt).encode("utf-8"))
                            stage = "playing" # switch to playing page
                        except Exception as ex:
                            stage = "error" # switch to error page
                            error_msg = f"Net error: {ex}"
                elif ev.key == pygame.K_j:  # Join room
                    new_name = get_name_input(screen, font_big, font_small) # player enter name
                    if new_name is not None: # save name
                        my_name = new_name
                        my_car.name = my_name
                        jcode = get_code_input(screen, font_big, font_small) # player enter room code
                        if not jcode:
                            continue
                        try:
                            sock = connect_to_relay() # connect to relay
                            code = jcode.upper()
                            join_pkt = {"t": "join", "code": code, "name": my_name, "id": my_id} # unchanged
                            sock.send(json.dumps(join_pkt).encode("utf-8"))
                            join_ok_received = False
                            timeout = time.time() + 1.0  # wait up to 5 seconds
                            while not join_ok_received and time.time() < timeout:
                                for msg in recv_jsons(sock):
                                    if msg.get("t") == "join_ok":
                                        join_ok_received = True
                                        break

                            if not join_ok_received:
                                raise Exception("Failed to connect: no join confirmation received")
                            stage = "playing" # switch to playing page

                        except Exception as ex:
                            stage = "error" # switch to error page
                            error_msg = f"Net error: {ex}"

            elif stage == "error" and ev.type == pygame.KEYDOWN:
                    if  ev.key == pygame.K_r:
                        stage = "menu"
                        error_msg = ""
                        remotes.clear()
                        if sock:
                            try:
                                sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                            except Exception:
                                pass
                            sock.close()
                            sock = None
                        code = None
                        spawnx = random.randint(TRACK_MARGIN + 200, WINDOW_WIDTH - TRACK_MARGIN - 200)
                        spawny = random.randint(TRACK_MARGIN + 120, WINDOW_HEIGHT - TRACK_MARGIN - 120)
                        my_car = Car(spawnx, spawny, my_name)

        # Process networking : read msgs
        if sock:
            err = handle_network_messages(sock, remotes, dt, my_id) # update remote players' list
            if err: # if error
                stage = "error" # switch to error page
                error_msg = err

        # Networking Out: send state & ping at defined intervals
        if sock and code:
            now = time.time()
            if now - last_state_send >= 1.0 / SEND_HZ:
                last_state_send = now
                send_network_state(sock, code, my_id, my_car)
            if now - last_ping >= 1.0 / PING_HZ:
                last_ping = now
                send_ping(sock, code)

        my_car.step(read_inputs(), dt, remotes) # Update car physics with local input

        # Draw screen and track
        screen.fill(GREY_20)
        draw_track(screen)

        # Menu draws
        if stage == "menu":
            title = font_big.render("Menu", True, WHITE_240)
            screen.blit(title, (WINDOW_WIDTH//2 - title.get_width()//2, 7))
            tip1 = font_medium.render("H : Host room", True, GREY_200)
            tip2 = font_medium.render("J : Join room", True, GREY_200)
            relay = font_small.render(f"Relay: {RELAY_PUBLIC_ENDPOINT}", True, GREY_180)
            screen.blit(tip1, (WINDOW_WIDTH*.3 - tip1.get_width()//2, 13))
            screen.blit(tip2, (WINDOW_WIDTH*.7 - tip2.get_width()//2, 13))
            screen.blit(relay, (WINDOW_WIDTH//2 - relay.get_width()//2, WINDOW_HEIGHT-30))

        # Always draw my car


        screen.blit(tire_mark, (0,0))
        drift_points = draw_car(screen, my_car.x, my_car.y, my_car.angle, my_car.name, color_body=COLOR_MY_CAR)
        if my_car.drift_ratio > 0.8 and drift_points_old != []:
            pygame.draw.line(tire_mark, (255,255,255,100), drift_points[0], drift_points_old[0], 3)
            pygame.draw.line(tire_mark, (255,255,255,100), drift_points[1], drift_points_old[1], 3)
            # Fade tire marks
        drift_points_old = drift_points
        tire_mark.fill((255, 255, 255, 250), special_flags=pygame.BLEND_RGBA_MULT)
        

        # Game playing: draw room code and remote players
        if stage == "playing":
            hud = font_small.render(f"Room: {code}", True, GREY_180)
            screen.blit(hud, (10, WINDOW_HEIGHT - 30))
            for pid, d in remotes.items():
                print(d["drift_ratio"])
                draw_car(screen, d["x"], d["y"], d["a"], d.get("name", f"Player{pid}"),
                         color_body=COLOR_BODY_REMOTE)

        if stage == "error":
            errh = font_big.render("ERROR", True, (255,120,120))
            screen.blit(errh, (WINDOW_WIDTH//2 - errh.get_width()//2, WINDOW_HEIGHT//2 - 40))
            msg = font_small.render(error_msg, True, (255,200,200))
            screen.blit(msg, (WINDOW_WIDTH//2 - msg.get_width()//2, WINDOW_HEIGHT//2))
            tip = font_small.render("Press R to restart", True, GREY_200)
            screen.blit(tip, (WINDOW_WIDTH//2 - tip.get_width()//2, WINDOW_HEIGHT//2 + 40))

        pygame.display.flip()

if __name__ == "__main__":
    main()
