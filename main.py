#!/usr/bin/env python3
"""
Top-down drift game client with camera (zoom & pan)
Refactored to remove magic numbers and reduce spaghetti code.
"""

import pygame, socket, json, time, random, string, sys, math, uuid, argparse # global imports
import camera, car, button as btn, lightspray # local imports

# ======= CONFIGURATION =======
RELAY_PUBLIC_ENDPOINT = "william-allow.gl.at.ply.gg:4800"

# World dimensions
WINDOW_WIDTH, WINDOW_HEIGHT = 1000, 700
TRACK_MARGIN = 40
TRACK_COLOR = (35, 40, 50)
TRACK_BORDER_COLOR = (80, 90, 100)
TRACK_BORDER_WIDTH = 4
FPS = 75
SEND_HZ = 60.0       # client -> relay state rate
PING_HZ = 1/5        # keepalive (~5 s)

# Colors
BLACK = (0, 0, 0)
DARK_NAVY_BLUE = (5, 15, 28)
GREY_20 = (20,20,28)
GREY_180 = (180, 180, 180)
GREY_200 = (200, 200, 200)
WHITE_240 = (240,240,240)
WHITE = (255, 255, 255)
COLOR_BODY_DEFAULT = (250,210,120)
COLOR_NOSE_DEFAULT = (255,120,120)
COLOR_BODY_REMOTE  = (255,200,120)
COLOR_MY_CAR       = (200,230,255)
HEADLIGHT_COLOR = (200, 200, 200)

# key binds
UP_KEY = [pygame.K_UP, pygame.K_z]
DOWN_KEY = [pygame.K_DOWN, pygame.K_s]
LEFT_KEY = [pygame.K_LEFT, pygame.K_q]
RIGHT_KEY = [pygame.K_RIGHT, pygame.K_d]
BRAKE_KEY = pygame.K_SPACE
ESCAPE_KEY = pygame.K_ESCAPE
RESET_KEY = pygame.K_r
HOST_KEY = pygame.K_h
JOIN_KEY = pygame.K_j

# car
CAR_LEN = 58.0
CAR_WID  = 30.0
TIRE_MARK_SMOKE = (255,255,255,100) # tire mark color at first step (smoke)
TIRE_MARK_GROUND = (220, 220, 220, 220) # tire mark color at second step on the ground
HEADLIGHT_LEN = 150
HEADLIGHT_FOV = 25 # degrees per headlight cone (narrow beams)
GLOW_RADIUS = 10 # soft round glow around the car

# visual const
TOP_LINE_Y = 30
BOTTOM_LINE_Y = WINDOW_HEIGHT-20
BTN_WIDTH, BTN_HEIGHT = 200, 100
FONT_SMALL_SIZE = 18
FONT_MEDIUM_SIZE = 26
FONT_BIG_SIZE = 40
TITLE_Y = 3
TIP1_Y = 8
TIP2_Y = 8
RELAY_Y = WINDOW_HEIGHT-16

# username & room code
ROOM_ALPHABET = string.ascii_uppercase + string.digits
JOIN_CODE_LEN = 4
MAX_CODE_LENGTH = 12
KEY_REPEAT_DELAY = 250
KEY_REPEAT_INTERVAL = 35
MIN_NAME_LENGTH = 3
MAX_NAME_LENGTH = 12
PROFANITY_SET = {"NIGGER", "NIGGA", "NIGA"}

VIEW_ANGLE = 70 * math.pi / 180.0  # radians

# =============================

def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x

def rand_code(n=JOIN_CODE_LEN):
    return "".join(random.choice(ROOM_ALPHABET) for _ in range(n))

def rand_name():
    return "Player" + "".join(random.choice(string.digits) for _ in range(4))

def car_local_to_world(cx, cy, angle, lx, ly):
    """Convert a local (lx, ly) point on the car to world coords."""
    ca, sa = math.cos(angle), math.sin(angle)
    return (cx + lx * ca - ly * sa,
            cy + lx * sa + ly * ca)

def draw_car(surface, x, y, angle, name,
             color_body=COLOR_BODY_DEFAULT,
             color_nose=COLOR_NOSE_DEFAULT, car_sprite=[]):
    ca, sa = math.cos(angle), math.sin(angle)
    halfL, halfW = CAR_LEN * 0.5, CAR_WID * 0.5
    pts = [(+halfL, +halfW),
           (+halfL, -halfW),
           (-halfL, -halfW),
           (-halfL, +halfW)]
    wpts = []
    for px, py in pts:
        rx = px * ca - py * sa
        ry = px * sa + py * ca
        wpts.append((int(x + rx), int(y + ry)))

    snapped_angle = round(angle / (math.pi / 16)) * (math.pi / 16)

    show_angle = (-snapped_angle + math.pi/2) % (2*math.pi) / (2*math.pi)
    sprite_index = int(show_angle * 32) % 32
    surface.blit(car_sprite[sprite_index], (int(x-75/2), int(y-75/2))) 

    if name:
        font = pygame.font.SysFont(None, 22)
        text = font.render(name, True, (230,230,255))
        surface.blit(text, (int(x-text.get_width()/2), int(y-40)))
    return (wpts[2], wpts[3])  # rear left and right

def draw_track(screen):
    pygame.draw.rect(screen, DARK_NAVY_BLUE, (0, TOP_LINE_Y, WINDOW_WIDTH, BOTTOM_LINE_Y-TOP_LINE_Y))
    pygame.draw.line(screen, WHITE, (0, TOP_LINE_Y), (WINDOW_WIDTH, TOP_LINE_Y))
    pygame.draw.line(screen, WHITE, (0, BOTTOM_LINE_Y), (WINDOW_WIDTH, BOTTOM_LINE_Y))

    # pygame.draw.rect(screen, TRACK_COLOR, (0,0,WINDOW_WIDTH,WINDOW_HEIGHT))
    # pygame.draw.rect(screen, TRACK_BORDER_COLOR,
    #                  (TRACK_MARGIN, TRACK_MARGIN,
    #                   WINDOW_WIDTH - 2 * TRACK_MARGIN,
    #                   WINDOW_HEIGHT - 2 * TRACK_MARGIN),
    #                  width=TRACK_BORDER_WIDTH)

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

def get_text_input(surface, title_text, tip_text, font_big, font_small, allowed_set=None):
    pygame.key.set_repeat(KEY_REPEAT_DELAY, KEY_REPEAT_INTERVAL)
    text = ""
    while True:
        surface.fill((20,20,25))
        draw_track(surface)
        title = font_big.render(title_text, True, (230,230,240))
        surface.blit(title, (WINDOW_WIDTH//2 - title.get_width()//2, WINDOW_HEIGHT//2 - 70))
        disp_text = text if text else "(empty)"
        inp = font_big.render(disp_text, True, (180,255,180))
        surface.blit(inp, (WINDOW_WIDTH//2 - inp.get_width()//2, WINDOW_HEIGHT//2 - 10))
        tip = font_small.render(tip_text, True, (180,180,180))
        surface.blit(tip, (WINDOW_WIDTH//2 - tip.get_width()//2, WINDOW_HEIGHT//2 + 40))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit(0)
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN:
                    return text or None
                if ev.key == ESCAPE_KEY:
                    return None
                if ev.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                else:
                    ch = ev.unicode.upper() if allowed_set is not None else ev.unicode
                    if allowed_set is None or (ch in allowed_set):
                        if len(text) < MAX_CODE_LENGTH:
                            text += ch

def get_code_input(surface, font_big, font_small):
    return get_text_input(surface,
                          "Enter ROOM CODE (A-Z/0-9)",
                          "Enter = OK   Esc = cancel",
                          font_big, font_small, allowed_set=ROOM_ALPHABET)

def get_name_input(surface, font_big, font_small):
    pygame.key.set_repeat(KEY_REPEAT_DELAY, KEY_REPEAT_INTERVAL)
    text = ""
    error_msg = ""
    while True:
        surface.fill((20,20,25))
        draw_track(surface)
        title = font_big.render("Enter your name", True, (230,230,240))
        surface.blit(title, (WINDOW_WIDTH//2 - title.get_width()//2, WINDOW_HEIGHT//2 - 70))
        disp_text = text if text else "(empty)"
        inp = font_big.render(disp_text, True, (180,255,180))
        surface.blit(inp, (WINDOW_WIDTH//2 - inp.get_width()//2, WINDOW_HEIGHT//2 - 10))
        tip = font_small.render("Enter : OK  -  Esc : cancel", True, (180,180,180))
        surface.blit(tip, (WINDOW_WIDTH//2 - tip.get_width()//2, WINDOW_HEIGHT//2 + 40))
        if error_msg:
            error_surf = font_big.render(error_msg, True, (230,80,80))
            surface.blit(error_surf, (WINDOW_WIDTH//2 - error_surf.get_width()//2, WINDOW_HEIGHT//2 - 120))
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
                if ev.key == ESCAPE_KEY:
                    return None
                if ev.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                    error_msg = ""
                else:
                    ch = ev.unicode
                    if ch.isprintable() and len(text) < MAX_NAME_LENGTH:
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
            POS_SMOOTHING_MULTIPLIER = 300.0
            ANGLE_SMOOTHING_MULTIPLIER = 300.0
            alpha_pos = min(1.0, dt * POS_SMOOTHING_MULTIPLIER)
            alpha_angle = min(1.0, dt * ANGLE_SMOOTHING_MULTIPLIER)
            for pid, d in players.items():
                if pid == my_id:
                    continue
                tx, ty, ta, tdr = float(d["x"]), float(d["y"]), float(d["a"]), float(d["drift_ratio"])
                name = d.get("name", f"Player{pid}")
                if pid not in remotes:
                    remotes[pid] = {"x": tx, "y": ty, "a": ta, "name": name, "drift_ratio": tdr}
                else:
                    cur = remotes[pid]
                    cur["x"] += (tx - cur["x"]) * alpha_pos
                    cur["y"] += (ty - cur["y"]) * alpha_pos
                    cur["drift_ratio"] += (tdr - cur["drift_ratio"]) * alpha_pos
                    da = ((ta - cur["a"] + math.pi) % (2 * math.pi)) - math.pi
                    cur["a"] = (cur["a"] + da * alpha_angle) % (2 * math.pi)
                    cur["name"] = name
            for pid in list(remotes.keys()):
                if pid not in players:
                    remotes.pop(pid, None)
        elif t == "error":
            return msg.get("msg", "error")
    return None

def send_network_state(sock, code, my_id, car):
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

def read_inputs(joysticks):
    keys = pygame.key.get_pressed()
    th = (1 if any(keys[key] for key in UP_KEY) else 0) - (1 if any(keys[key] for key in DOWN_KEY) else 0)
    st = (1 if any(keys[key] for key in RIGHT_KEY) else 0) - (1 if any(keys[key] for key in LEFT_KEY) else 0)
    br = 1.0 if keys[BRAKE_KEY] else 0.0
    if th != 0:
        th = 1.0 if th > 0 else -1.0
    if st != 0:
        st = 1.0 if st > 0 else -1.0

    if joysticks and joysticks[0] != []:
        js = joysticks[0]
        steering = js.get_axis(0)
        throttle = (js.get_axis(5)+1)/2
        breaks = (js.get_axis(4)+1)/2
        st = steering if steering != 0 else st
        th = throttle if throttle != 0 else th
        br = breaks if breaks != 0 else br
    return {"th": th, "st": st, "br": br}

def draw_menu(screen, font_big, font_medium):
    title = font_big.render("Menu", True, WHITE_240)
    screen.blit(title, (WINDOW_WIDTH//2 - title.get_width()//2, 7))
    tip1 = font_medium.render("H : Host room", True, GREY_200)
    tip2 = font_medium.render("J : Join room", True, GREY_200)
    screen.blit(tip1, (int(WINDOW_WIDTH * 0.3 - tip1.get_width() // 2), 13))
    screen.blit(tip2, (int(WINDOW_WIDTH * 0.7 - tip2.get_width() // 2), 13))

def handle_menu_events(screen, font_big, font_small, ev, stage, my_name, my_id, code, sock, error_msg):
    if ev.key == HOST_KEY:  # Host room
        my_name = get_name_input(screen, font_big, font_small)
        code = rand_code()
        try:
            sock = connect_to_relay()
            join_pkt = {"t": "create", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
            stage = "playing"
        except Exception as ex:
            stage = "error"
            error_msg = f"Net error: {ex}"
    elif ev.key == JOIN_KEY:  # Join room
        my_name = get_name_input(screen, font_big, font_small)
        jcode = get_code_input(screen, font_big, font_small)
        try:
            sock = connect_to_relay()
            code = jcode.upper()
            join_pkt = {"t": "join", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
            stage = "playing"
        except Exception as ex:
            stage = "error"
            error_msg = f"Net error: {ex}"

    return stage, my_name, code, sock, error_msg

def handle_game_events(screen, ev, stage, remotes, sock, code, my_name, my_id, my_car, font_big, font_small, error_msg):
    if ev.type == pygame.KEYDOWN:
        if stage == "menu":
            stage, my_name, code, sock, error_msg = handle_menu_events(screen, font_big, font_small, ev, stage, my_name, my_id, code, sock, error_msg)
        elif stage == "playing" and ev.key == ESCAPE_KEY: # open settings menu
                stage = "settings"          
        elif stage == "settings" and ev.key == ESCAPE_KEY: # leave settings menu
                stage = "playing"
        elif stage == "error" and ev.key == RESET_KEY:
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
                my_car = car.Car(spawnx, spawny, my_name)

    return ev, stage, remotes, sock, code, my_car, error_msg

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["host", "join"])
    parser.add_argument("--code")
    parser.add_argument("--name")
    args, unknown = parser.parse_known_args()

    pygame.init()
    pygame.joystick.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Top-Down Drift — Client Trust (Pi relay)")
    clock = pygame.time.Clock()
    font_small = pygame.font.SysFont(None, FONT_SMALL_SIZE)
    font_medium = pygame.font.SysFont(None, FONT_MEDIUM_SIZE)
    font_big = pygame.font.SysFont(None, FONT_BIG_SIZE)
    
    # bg_map = pygame.image.load("assets/map/01.png").convert_alpha()

    # Load car sprites
    au86_sprite = []
    for i in range(32):
        img = pygame.image.load(f"assets/AE86/{i:04}.png").convert_alpha()
        au86_sprite.append(img)

    stage = "menu"  # menu | playing | settings | keys | error
    error_msg = ""
    remotes = {}

    my_name = rand_name()
    my_id = str(uuid.uuid4())[:8]
    code = None
    sock = None
    last_state_send = 0.0
    last_ping = 0.0

    spraymap = lightspray.Spray(WINDOW_WIDTH, WINDOW_HEIGHT, HEADLIGHT_COLOR)
    lights_on = True

    spawnx = random.randint(TRACK_MARGIN + 200, WINDOW_WIDTH - TRACK_MARGIN - 200)
    spawny = random.randint(TRACK_MARGIN + 120, WINDOW_HEIGHT - TRACK_MARGIN - 120)
    my_car = car.Car(spawnx, spawny, my_name)

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
    drift_points_old_remotes = {}

    joysticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
    for js in joysticks:
        js.init()

    # Create a camera object; mouse wheel will adjust zoom and middle mouse drag will pan.
    cam = camera.Camera(WINDOW_WIDTH, WINDOW_HEIGHT, zoom=1.0)
    dragging = False

    def leave_room(sock, code, my_id, remotes):
        if sock and code:
            try:
                sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                sock.close()
            except Exception:
                pass
        remotes.clear()
        # stage, sock, code, remotes
        return "menu", None, None, remotes

    def show_key_binds(): # to do
        print("Showing key binds...")

    buttons = [
        btn.Button("Leave Room", WINDOW_WIDTH//2-BTN_WIDTH//2, WINDOW_HEIGHT*0.4, BTN_WIDTH, BTN_HEIGHT, (200, 0, 0), (255, 50, 50), lambda: leave_room(sock, code, my_id, remotes)),
        btn.Button("Key Binds", WINDOW_WIDTH//2-BTN_WIDTH//2, WINDOW_HEIGHT*0.6, BTN_WIDTH, BTN_HEIGHT, (50, 50, 200), (100, 100, 255), show_key_binds),
    ]

    while True:
        dt = clock.tick(FPS) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                if sock and code:
                    try: sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                    except Exception: pass
                pygame.quit()
                sys.exit(0)

            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_l:
                lights_on = not lights_on
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

            ev, stage, remotes, sock, code, my_car, error_msg = handle_game_events(screen, ev, stage, remotes, sock, code, my_name, my_id, my_car, font_big, font_small, error_msg)

        if sock:
            err = handle_network_messages(sock, remotes, dt, my_id)
            if err:
                stage = "error"
                error_msg = err

        if sock and code:
            now = time.time()
            if now - last_state_send >= 1.0 / SEND_HZ:
                last_state_send = now
                send_network_state(sock, code, my_id, my_car)
            if now - last_ping >= 1.0 / PING_HZ:
                last_ping = now
                send_ping(sock, code)

        my_car.step(read_inputs(joysticks), dt, remotes)
        cam.update(my_car)

        # Draw game world onto an off-screen surface.
        world_surf = pygame.Surface((WINDOW_WIDTH, WINDOW_HEIGHT))
        world_surf.fill(GREY_20)
        draw_track(world_surf)
        # world_surf.blit(bg_map, (0, 0))
        world_surf.blit(tire_mark, (0,0))
        drift_points = draw_car(world_surf, my_car.x, my_car.y, my_car.angle, my_car.name,
                                  color_body=COLOR_MY_CAR, car_sprite=au86_sprite)
        if my_car.drift_ratio > 0.8 and drift_points_old:
            pygame.draw.line(tire_mark, TIRE_MARK_SMOKE, drift_points[0], drift_points_old[0], 3)
            pygame.draw.line(tire_mark, TIRE_MARK_SMOKE, drift_points[1], drift_points_old[1], 3)
        drift_points_old = drift_points
        tire_mark.fill(TIRE_MARK_GROUND, special_flags=pygame.BLEND_RGBA_MULT)

        if stage == "menu":
            title = font_big.render("Menu", True, WHITE_240)
            world_surf.blit(title, (WINDOW_WIDTH//2 - title.get_width()//2, TITLE_Y))
            tip1 = font_medium.render("H : Host room", True, GREY_200)
            tip2 = font_medium.render("J : Join room", True, GREY_200)
            relay = font_small.render(f"Relay: {RELAY_PUBLIC_ENDPOINT}", True, GREY_180)
            world_surf.blit(tip1, (int(WINDOW_WIDTH*.3 - tip1.get_width()//2), TIP1_Y))
            world_surf.blit(tip2, (int(WINDOW_WIDTH*.7 - tip2.get_width()//2), TIP2_Y))
            world_surf.blit(relay, (WINDOW_WIDTH//2 - relay.get_width()//2, RELAY_Y))

        if stage == "playing":
            title = font_big.render("Waiting for players", True, WHITE_240)
            world_surf.blit(title, (WINDOW_WIDTH//2 - title.get_width()//2, TITLE_Y))
            hud = font_small.render(f"Room: {code}", True, GREY_180)
            world_surf.blit(hud, (10, RELAY_Y))
            for pid, d in remotes.items():
                drift_points_remote = draw_car(world_surf, d["x"], d["y"], d["a"], d.get("name", f"Player{pid}"),
                                               color_body=COLOR_BODY_REMOTE, car_sprite=au86_sprite)
                if d["drift_ratio"] > 0.8 and pid in drift_points_old_remotes:
                    old_pts = drift_points_old_remotes[pid]
                    pygame.draw.line(tire_mark, (255,255,255,100), drift_points_remote[0], old_pts[0], 3)
                    pygame.draw.line(tire_mark, (255,255,255,100), drift_points_remote[1], old_pts[1], 3)
                drift_points_old_remotes[pid] = drift_points_remote

        if stage == "settings":
            title = font_big.render("Settings", True, WHITE_240)
            world_surf.blit(title, (WINDOW_WIDTH//2 - title.get_width()//2, TITLE_Y))
            for button in buttons: button.draw(world_surf)
            # world_surf.blit(btn_screen, (0, 0))

        if stage == "error":
            errh = font_big.render("ERROR", True, (255,120,120))
            world_surf.blit(errh, (WINDOW_WIDTH//2 - errh.get_width()//2, WINDOW_HEIGHT//2 - 40))
            msg = font_small.render(error_msg, True, (255,200,200))
            world_surf.blit(msg, (WINDOW_WIDTH//2 - msg.get_width()//2, WINDOW_HEIGHT//2))
            tip = font_small.render("Press R to restart", True, GREY_200)
            world_surf.blit(tip, (WINDOW_WIDTH//2 - tip.get_width()//2, WINDOW_HEIGHT//2 + 40))

        # ----- Pixel lighting -----
        if lights_on:
            spraymap.surface.fill((0, 0, 0, 0)) # transparent bg

            # two pixelated headlight cones from front-left and front-right
            halfL, halfW = CAR_LEN * 0.5, CAR_WID * 0.5
            hl_base_L = car_local_to_world(my_car.x, my_car.y, my_car.angle,  halfL*0.85, -halfW*0.35)
            hl_base_R = car_local_to_world(my_car.x, my_car.y, my_car.angle,  halfL*0.85,  halfW*0.35)

            spraymap.add_cone(hl_base_L[0], hl_base_L[1], my_car.angle, HEADLIGHT_LEN, fov=HEADLIGHT_FOV)
            spraymap.add_cone(hl_base_R[0], hl_base_R[1], my_car.angle, HEADLIGHT_LEN, fov=HEADLIGHT_FOV)

            # Multiply lightmap over the world (white = keep, dark = darken)
            world_surf.blit(spraymap.render(), (0, 0), special_flags=pygame.BLEND_RGBA_ADD)

        # Apply camera transform (zoom & pan) and blit to screen.
        final_surf = cam.apply(world_surf)
        screen.blit(final_surf, (0,0))
        pygame.display.flip()

if __name__ == "__main__":
    main()
