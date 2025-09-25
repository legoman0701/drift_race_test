#!/usr/bin/env python3
# game_client_trust.py — Top-down drift with CLIENT-TRUST networking via Pi relay
# Every client simulates itself locally and sends its state each tick.
# The Raspberry Pi relay aggregates states and broadcasts snapshots to everyone.

import pygame, socket, json, time, random, string, sys, math, uuid

# ======= CONFIG — Raspberry Pi relay (Playit public endpoint) =======
RELAY_PUBLIC_ENDPOINT = "william-allow.gl.at.ply.gg:4800"  # <-- your Pi's Playit UDP endpoint
# ====================================================================

# Window & game config
WIDTH, HEIGHT = 1000, 700
TRACK_MARGIN = 40
SEND_HZ = 30.0       # client -> relay state rate
PING_HZ = 0.2        # keepalive (~5 s)
JOIN_CODE_LEN = 6
ALPHABET = string.ascii_uppercase + string.digits

# Car & physics constants
CAR_LEN = 58.0
CAR_WID  = 30.0
ENGINE_ACC   = 950.0
REVERSE_ACC  = 700.0
BRAKE_DECEL  = 1400.0
DRAG   = 0.35
ROLLING = 1.6
LATERAL_GRIP = 3.2
STEER_SENS   = 2.8 / 240.0
OVERSTEER    = 0.0015
OMEGA_DAMP   = 25
MAX_SPEED    = 1200.0
WALL_RESTITUTION = 0.3

def rand_code(n=JOIN_CODE_LEN): return "".join(random.choice(ALPHABET) for _ in range(n))
def rand_name(): return "Player" + "".join(random.choice(string.digits) for _ in range(4))
def clamp(x, lo, hi): return lo if x < lo else hi if x > hi else x

class Car:
    __slots__ = ("x","y","vx","vy","ang","omega","name")
    def __init__(self, x, y, name):
        self.x, self.y = float(x), float(y)
        self.vx, self.vy = 0.0, 0.0
        self.ang = 0.0
        self.omega = 0.0
        self.name = name

    def step(self, inp, dt):
        th = clamp(inp.get("th", 0.0), -1.0, 1.0)
        st = clamp(inp.get("st", 0.0), -1.0, 1.0)
        br = 1.0 if inp.get("br", 0.0) else 0.0

        ca, sa = math.cos(self.ang), math.sin(self.ang)
        fx, fy = ca, sa
        rx, ry = -sa, ca

        v_fwd = self.vx*fx + self.vy*fy
        v_lat = self.vx*rx + self.vy*ry

        acc_fx = acc_fy = 0.0
        if th > 0:
            acc_fx += fx * (th * ENGINE_ACC); acc_fy += fy * (th * ENGINE_ACC)
        elif th < 0:
            acc_fx += fx * (th * REVERSE_ACC); acc_fy += fy * (th * REVERSE_ACC)

        acc_fx += -self.vx * DRAG
        acc_fy += -self.vy * DRAG

        acc_fx += -fx * (v_fwd * ROLLING)
        acc_fy += -fy * (v_fwd * ROLLING)
        acc_fx += -rx * (v_lat * LATERAL_GRIP)
        acc_fy += -ry * (v_lat * LATERAL_GRIP)

        speed = math.hypot(self.vx, self.vy)
        if br and speed > 1e-3:
            acc_fx += -(self.vx / speed) * BRAKE_DECEL
            acc_fy += -(self.vy / speed) * BRAKE_DECEL

        self.vx += acc_fx * dt; self.vy += acc_fy * dt
        spd = math.hypot(self.vx, self.vy)
        if spd > MAX_SPEED:
            s = MAX_SPEED / spd; self.vx *= s; self.vy *= s
        self.x += self.vx * dt; self.y += self.vy * dt

        self.omega += (STEER_SENS * st * v_fwd) + (OVERSTEER * v_lat) - (OMEGA_DAMP * self.omega * dt)
        self.ang = (self.ang + self.omega * dt) % (2*math.pi)

        minx, maxx = TRACK_MARGIN, WIDTH - TRACK_MARGIN
        miny, maxy = TRACK_MARGIN, HEIGHT - TRACK_MARGIN
        hit = False
        if self.x < minx: self.x = minx; self.vx = -self.vx * WALL_RESTITUTION; hit = True
        if self.x > maxx: self.x = maxx; self.vx = -self.vx * WALL_RESTITUTION; hit = True
        if self.y < miny: self.y = miny; self.vy = -self.vy * WALL_RESTITUTION; hit = True
        if self.y > maxy: self.y = maxy; self.vy = -self.vy * WALL_RESTITUTION; hit = True
        if hit: self.omega *= 0.5

def draw_car(surface, x, y, ang, name, color_body=(250,210,120), color_nose=(255,120,120)):
    ca, sa = math.cos(ang), math.sin(ang)
    halfL, halfW = CAR_LEN*0.5, CAR_WID*0.5
    pts = [(+halfL,+halfW),(+halfL,-halfW),(-halfL,-halfW),(-halfL,+halfW)]
    wpts = []
    for px, py in pts:
        rx = px*ca - py*sa; ry = px*sa + py*ca
        wpts.append((int(x+rx), int(y+ry)))
    pygame.draw.polygon(surface, color_body, wpts)
    nose = (x + ca*halfL, y + sa*halfL)
    lft  = (x + ca*(halfL*0.4) - sa*(halfW*0.9), y + sa*(halfL*0.4) + ca*(halfW*0.9))
    rgt  = (x + ca*(halfL*0.4) + sa*(halfW*0.9), y + sa*(halfL*0.4) - ca*(halfW*0.9))
    pygame.draw.polygon(surface, color_nose, [(int(nose[0]),int(nose[1])), (int(lft[0]),int(lft[1])), (int(rgt[0]),int(rgt[1]))])
    if name:
        font = pygame.font.SysFont(None, 22)
        surface.blit(font.render(name, True, (230,230,255)), (int(x)+12, int(y)-10))

def draw_track(surface):
    pygame.draw.rect(surface, (35,40,50), (0,0,WIDTH,HEIGHT))
    pygame.draw.rect(surface, (80,90,100), (TRACK_MARGIN, TRACK_MARGIN, WIDTH-2*TRACK_MARGIN, HEIGHT-2*TRACK_MARGIN), width=4)

def recv_jsons(sock):
    msgs = []
    while True:
        try:
            data = sock.recv(8192)
            if not data: break
            try: msgs.append(json.loads(data.decode("utf-8")))
            except: pass
        except BlockingIOError:
            break
        except Exception:
            break
    return msgs

def connect_to_relay():
    host_s, port_s = RELAY_PUBLIC_ENDPOINT.rsplit(":", 1)
    port_i = int(port_s)
    fam, stype, proto, canon, sa = socket.getaddrinfo(host_s, port_i, socket.AF_UNSPEC, socket.SOCK_DGRAM)[0]
    s = socket.socket(fam, stype, proto)
    s.setblocking(False)
    s.connect(sa)
    return s

def get_code_input(screen, big, font):
    pygame.key.set_repeat(250,35)
    t = ""
    while True:
        screen.fill((20,20,25))
        draw_track(screen)
        surf = big.render("Enter ROOM CODE (A-Z/0-9)", True, (230,230,240))
        screen.blit(surf, (WIDTH//2 - surf.get_width()//2, HEIGHT//2 - 70))
        inp = big.render(t or "(empty)", True, (180,255,180))
        screen.blit(inp, (WIDTH//2 - inp.get_width()//2, HEIGHT//2 - 10))
        tip = font.render("Enter = OK   Esc = cancel", True, (180,180,180))
        screen.blit(tip, (WIDTH//2 - tip.get_width()//2, HEIGHT//2 + 40))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit(0)
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN: return t if t else None
                if ev.key == pygame.K_ESCAPE: return None
                if ev.key == pygame.K_BACKSPACE: t = t[:-1]
                else:
                    ch = ev.unicode.upper()
                    if ch in ALPHABET and len(t) < 12: t += ch

def get_name_input(screen, big, font):
    pygame.key.set_repeat(250,35)
    t = ""
    while True:
        screen.fill((20,20,25))
        draw_track(screen)
        surf = big.render("Enter your name", True, (230,230,240))
        screen.blit(surf, (WIDTH//2 - surf.get_width()//2, HEIGHT//2 - 70))
        inp = big.render(t or "(empty)", True, (180,255,180))
        screen.blit(inp, (WIDTH//2 - inp.get_width()//2, HEIGHT//2 - 10))
        tip = font.render("Enter = OK   Esc = cancel", True, (180,180,180))
        screen.blit(tip, (WIDTH//2 - tip.get_width()//2, HEIGHT//2 + 40))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); sys.exit(0)
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN:
                    return t if t else None
                if ev.key == pygame.K_ESCAPE:
                    return None
                if ev.key == pygame.K_BACKSPACE:
                    t = t[:-1]
                else:
                    ch = ev.unicode
                    if ch.isprintable() and len(t) < 12:
                        t += ch

def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Top-Down Drift — Client-Trust (Pi relay)")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 28)
    big  = pygame.font.SysFont(None, 46)

    stage = "menu"   # menu | playing | error
    error_msg = ""

    my_name = rand_name()
    my_id = str(uuid.uuid4())[:8]

    # Room + net
    code = None
    sock = None
    last_state_send = 0.0
    last_ping = 0.0

    # My local car (simulated here)
    spawnx = random.randint(TRACK_MARGIN+200, WIDTH-TRACK_MARGIN-200)
    spawny = random.randint(TRACK_MARGIN+120, HEIGHT-TRACK_MARGIN-120)
    my_car = Car(spawnx, spawny, my_name)

    # Remote players smoothing cache: pid -> {"x","y","a","name"}
    remotes = {}

    def read_inputs():
        keys = pygame.key.get_pressed()
        th = (keys[pygame.K_w] or keys[pygame.K_UP]) - (keys[pygame.K_s] or keys[pygame.K_DOWN])
        st = (keys[pygame.K_d] or keys[pygame.K_RIGHT]) - (keys[pygame.K_a] or keys[pygame.K_LEFT])
        br = 1.0 if keys[pygame.K_SPACE] else 0.0
        th = 1.0 if th > 0 else -1.0 if th < 0 else 0.0
        st = 1.0 if st > 0 else -1.0 if st < 0 else 0.0
        return {"th": th, "st": st, "br": br}

    while True:
        dt = clock.tick(60) / 1000.0

        # events
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                try:
                    if sock and code:
                        sock.send(json.dumps({"t":"bye","code":code,"id":my_id}).encode("utf-8"))
                except: pass
                pygame.quit(); return

            if stage == "menu" and e.type == pygame.KEYDOWN:
                if e.key == pygame.K_h:  # "Host" = create room
                    new_name = get_name_input(screen, big, font)
                    if new_name is not None:
                        my_name = new_name
                    code = rand_code()
                    try:
                        sock = connect_to_relay()
                        # Join room
                        sock.send(json.dumps({"t":"join","code":code,"name":my_name,"id":my_id}).encode("utf-8"))
                        stage = "playing"
                    except Exception as ex:
                        stage = "error"; error_msg = f"Net error: {ex}"
                if e.key == pygame.K_j:
                    new_name = get_name_input(screen, big, font)
                    if new_name is not None:
                        my_name = new_name
                    jcode = get_code_input(screen, big, font)
                    if not jcode: continue
                    try:
                        sock = connect_to_relay()
                        code = jcode.upper()
                        sock.send(json.dumps({"t":"join","code":code,"name":my_name,"id":my_id}).encode("utf-8"))
                        stage = "playing"
                    except Exception as ex:
                        stage = "error"; error_msg = f"Net error: {ex}"

        # simulate local car (always, so menu shows movement too)
        my_car.step(read_inputs(), dt)

        # networking in
        if sock:
            for msg in recv_jsons(sock):
                t = msg.get("t")
                if t == "join_ok":
                    pass
                elif t == "world":
                    players = msg.get("players", {}) or {}
                    # update remotes
                    alpha_pos = min(1.0, dt * 10.0)
                    alpha_ang = min(1.0, dt * 10.0)
                    # insert/update others
                    for pid, d in players.items():
                        if pid == my_id:  # we show our own locally; but keep name in case
                            continue
                        tx, ty, ta = float(d["x"]), float(d["y"]), float(d["a"])
                        nm = d.get("name", f"Player{pid}")
                        cur = remotes.get(pid)
                        if cur is None:
                            remotes[pid] = {"x": tx, "y": ty, "a": ta, "name": nm}
                        else:
                            cur["x"] += (tx - cur["x"]) * alpha_pos
                            cur["y"] += (ty - cur["y"]) * alpha_pos
                            da = ((ta - cur["a"] + math.pi) % (2*math.pi)) - math.pi
                            cur["a"] = (cur["a"] + da * alpha_ang) % (2*math.pi)
                            cur["name"] = nm
                    # remove disappeared pids
                    for pid in list(remotes.keys()):
                        if pid not in players:
                            remotes.pop(pid, None)
                elif t == "error":
                    stage = "error"; error_msg = msg.get("msg","error")

        # networking out (send our state at SEND_HZ)
        if sock and code:
            now = time.time()
            if now - last_state_send >= 1.0 / SEND_HZ:
                last_state_send = now
                pkt = {
                    "t":"state","code":code,"id":my_id,
                    "x": round(my_car.x,2),"y": round(my_car.y,2),"a": round(my_car.ang,4),
                    "vx": round(my_car.vx,2),"vy": round(my_car.vy,2)
                }
                try: sock.send(json.dumps(pkt).encode("utf-8"))
                except: pass
            if now - last_ping >= (1.0 / PING_HZ):
                last_ping = now
                try: sock.send(json.dumps({"t":"ping","code":code}).encode("utf-8"))
                except: pass

        # draw
        screen.fill((18,20,28))
        draw_track(screen)

        if stage == "menu":
            title = big.render("Top-Down Drift — Client Trust", True, (240,240,250))
            screen.blit(title, (WIDTH//2 - title.get_width()//2, 120))
            tip1 = font.render("H = Create room (change name)   •   J = Join room", True, (200,200,210))
            tip2 = font.render(f"Relay: {RELAY_PUBLIC_ENDPOINT}", True, (180,180,180))
            screen.blit(tip1, (WIDTH//2 - tip1.get_width()//2, 180))
            screen.blit(tip2, (WIDTH//2 - tip2.get_width()//2, 210))

        # Draw my car always (menu + playing)
        draw_car(screen, my_car.x, my_car.y, my_car.ang, my_name, color_body=(200,230,255))

        if stage == "playing":
            # show room code
            hud = font.render(f"Room: {code}", True, (180,180,180))
            screen.blit(hud, (10, HEIGHT-30))
            # Draw remotes
            for pid, d in remotes.items():
                draw_car(screen, d["x"], d["y"], d["a"], d.get("name", f"Player{pid}"),
                         color_body=(255,200,120))

        if stage == "error":
            errh = big.render("ERROR", True, (255,120,120))
            screen.blit(errh, (WIDTH//2 - errh.get_width()//2, HEIGHT//2 - 40))
            msg = font.render(error_msg, True, (255,200,200))
            screen.blit(msg, (WIDTH//2 - msg.get_width()//2, HEIGHT//2))
            tip = font.render("Restart to try again.", True, (200,200,200))
            screen.blit(tip, (WIDTH//2 - tip.get_width()//2, HEIGHT//2 + 40))

        pygame.display.flip()

if __name__ == "__main__":
    main()
