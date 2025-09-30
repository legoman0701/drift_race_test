import math
import time
import json
import pygame
from typing import Dict, Any, Optional, Tuple

import const
from car import CAR_LEN, CAR_WID
from helpers import clamp, rand_code
from inputs import get_name_input, get_code_input
from communication import connect_to_relay, recv_jsons


def draw_car(surface, x, y, angle, name,
             color_body=const.COLOR_BODY_DEFAULT,
             color_nose=const.COLOR_NOSE_DEFAULT, car_sprites_list=None, lights_on=False):
    if car_sprites_list is None:
        car_sprites_list = []
    for i, car_sprite in enumerate(car_sprites_list):
        if i == 2 and not lights_on:  # light spray
            continue
        show_angle = (-angle + math.pi / 2) % (2 * math.pi) / (2 * math.pi)
        sprite_index = int(show_angle * 32) % 32
        sprite_size = (car_sprite[sprite_index].get_width(), car_sprite[sprite_index].get_height())
        surface.blit(car_sprite[sprite_index], (int(x - sprite_size[0] / 2), int(y - sprite_size[1] / 2)))

    # Draw oriented collision rectangle overlay
    ca, sa = math.cos(angle), math.sin(angle)
    halfL, halfW = CAR_LEN * 0.7, CAR_WID * 0.5
    pts_local = [(+halfL, +halfW), (+halfL, -halfW), (-halfL, -halfW), (-halfL, +halfW)]
    wpts = []
    for px, py in pts_local:
        rx = px * ca - py * sa
        ry = px * sa + py * ca
        wpts.append((int(x + rx), int(y + ry)))
    try:
        pygame.draw.polygon(surface, (60, 220, 180), wpts, 1)
    except Exception:
        pass

    if name:
        scale = getattr(const, "UI_SCALE", 1.0)
        font = pygame.font.SysFont(None, max(1, int(22 * scale)))
        text = font.render(name, True, (230, 230, 255))
        surface.blit(text, (int(x - text.get_width() / 2), int(y - int(40 * scale))))

    # Return rear-wheel edge points for tire mark drawing by callers (indices 2 and 3)
    return (wpts[2], wpts[3])


def draw_track_ui(screen):
    pygame.draw.rect(screen, const.TRACK_BORDER_COLOR, (0, 0, const.WINDOW_WIDTH, const.TOP_LINE_Y))
    pygame.draw.rect(screen, const.TRACK_BORDER_COLOR, (0, const.BOTTOM_LINE_Y, const.WINDOW_WIDTH, const.WINDOW_HEIGHT - const.BOTTOM_LINE_Y))
    pygame.draw.line(screen, const.WHITE, (0, const.TOP_LINE_Y), (const.WINDOW_WIDTH, const.TOP_LINE_Y))
    pygame.draw.line(screen, const.WHITE, (0, const.BOTTOM_LINE_Y), (const.WINDOW_WIDTH, const.BOTTOM_LINE_Y))


def draw_menu(screen, font_big, font_medium):
    title = font_big.render("Menu", True, const.WHITE_240)
    screen.blit(title, (const.WINDOW_WIDTH // 2 - title.get_width() // 2, 7))
    tip1 = font_medium.render("H : Host room", True, const.GREY_200)
    tip2 = font_medium.render("J : Join room", True, const.GREY_200)
    screen.blit(tip1, (int(const.WINDOW_WIDTH * 0.3 - tip1.get_width() // 2), 13))
    screen.blit(tip2, (int(const.WINDOW_WIDTH * 0.7 - tip2.get_width() // 2), 13))


def handle_menu_events(screen, font_big, font_small, ev, stage, my_name, my_id, code, sock, error_msg, is_host_flag_ref):
    if ev.key == const.HOST_KEY:  # Host room
        my_name = get_name_input(screen, font_big, font_small, "host")
        code = rand_code()
        try:
            sock = connect_to_relay()
            join_pkt = {"t": "create", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
            # wait briefly for server confirmation
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
            if not join_ok_received:
                # Relay didn't confirm; fall back to offline mode
                try:
                    sock.close()
                except Exception:
                    pass
                sock = None
                code = "Offline"
                stage = "playing"
                is_host_flag_ref[0] = True  # offline single-player acts as host
            else:
                stage = "playing"
                is_host_flag_ref[0] = True
        except Exception:
            # Relay unreachable; fall back to offline mode
            try:
                if sock:
                    sock.close()
            except Exception:
                pass
            sock = None
            code = "Offline"
            stage = "playing"
            is_host_flag_ref[0] = True
    elif ev.key == const.JOIN_KEY:  # Join room
        my_name = get_name_input(screen, font_big, font_small, "join")
        jcode = get_code_input(screen, font_big, font_small)
        try:
            sock = connect_to_relay()
            code = jcode.upper()
            join_pkt = {"t": "join", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
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
            if not join_ok_received:
                # Relay didn't confirm; fall back to offline
                try:
                    sock.close()
                except Exception:
                    pass
                sock = None
                code = "Offline"
                stage = "playing"
                # Join offline: treat as single-player (not host for net features)
                is_host_flag_ref[0] = False
            else:
                stage = "playing"
                is_host_flag_ref[0] = False
        except Exception:
            # Relay unreachable; fall back to offline
            try:
                if sock:
                    sock.close()
            except Exception:
                pass
            sock = None
            code = "Offline"
            stage = "playing"
            is_host_flag_ref[0] = False

    return stage, my_name, code, sock, error_msg

def handle_game_events(screen, ev, stage, remotes, sock, code, my_name, my_id, my_car, font_big, font_small, error_msg, is_host_flag_ref):
    if ev.type == pygame.KEYDOWN:
        if stage == "menu":
            stage, my_name, code, sock, error_msg = handle_menu_events(screen, font_big, font_small, ev, stage, my_name, my_id, code, sock, error_msg, is_host_flag_ref)
            try:
                if stage == "playing" and my_car is not None:
                    my_car.name = my_name
            except NameError:
                pass
        elif stage == "playing" and ev.key == const.ESCAPE_KEY:  # open settings
            stage = "settings"
        elif stage == "settings" and ev.key == const.ESCAPE_KEY:  # close settings
            stage = "playing"
        elif stage == "error" and ev.key == const.RESET_KEY:
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
            import random
            spawnx = random.randint(const.TRACK_MARGIN + 200, const.WINDOW_WIDTH - const.TRACK_MARGIN - 200)
            spawny = random.randint(const.TRACK_MARGIN + 120, const.WINDOW_HEIGHT - const.TRACK_MARGIN - 120)
            import car
            my_car = car.Car(spawnx, spawny, my_name, is_ai=False)

    return ev, stage, remotes, sock, code, my_car, error_msg

def draw_controls_hud(ui_surf: pygame.Surface,
                      font_small: pygame.font.Font,
                      st: float,
                      th: float,
                      br: float,
                      rpm: Optional[float] = None,
                      rpm_redline: float = 8000.0) -> None:
    """Draw bottom-right HUD with RPM gauge, steering wheel, throttle and brake bars.

    Parameters
    - st: steering input in [-1, 1]
    - th: throttle input in [-1, 1] (negative means reverse)
    - br: brake input in [0, 1]
    - rpm: optional engine RPM; if None, a simple estimate is derived from throttle
    - rpm_redline: maximum RPM for gauge scaling
    """
    # Apply UI scaling
    s = getattr(const, "UI_SCALE", 1.0)
    def sc(v: float) -> int:
        return int(round(v * s))

    # Compute a simple RPM if not supplied (idle -> redline by throttle)
    if rpm is None:
        rpm = abs(clamp(th, -1.0, 1.0)) * rpm_redline
    rpm = clamp(rpm, 0.0, rpm_redline)

    # HUD layout
    pad = sc(12)
    hud_h = sc(120)
    wheel_size = sc(76)
    gauge_size = sc(76)  # analog RPM gauge, same size as steering wheel

    # Compute dynamic width: gauge + wheel + bars area
    bars_min_width = sc(110)
    hud_w = gauge_size + wheel_size + bars_min_width + sc(32)  # extra padding/margins

    x = const.WINDOW_WIDTH - hud_w - pad
    y = const.WINDOW_HEIGHT - hud_h - pad

    # semi-transparent background
    bg = pygame.Surface((hud_w, hud_h), pygame.SRCALPHA)
    bg.fill((10, 10, 14, 200))
    ui_surf.blit(bg, (x, y))

    # --- RPM Gauge (left) ---
    gcx = x + gauge_size // 2 + sc(10)
    gcy = y + hud_h // 2
    g_r_outer = gauge_size // 2
    g_r = g_r_outer - sc(8)
    # outer ring
    
    pygame.draw.circle(ui_surf, (40, 40, 48), (gcx, gcy), g_r_outer)
    pygame.draw.circle(ui_surf, (20, 20, 26), (gcx, gcy), g_r_outer - sc(2))
    pygame.draw.circle(ui_surf, (60, 60, 70), (gcx, gcy), g_r, max(1, sc(4)))

    # Gauge angles and mapping (sweep from ~210° to ~330°)
    a0 = math.radians(100.0)
    a1 = math.radians(330.0)
    def angle_for_rpm(val: float) -> float:
        f = 0.0 if rpm_redline <= 0 else clamp(val / rpm_redline, 0.0, 1.0)
        return a0 + (a1 - a0) * f

    # ticks (0..8 x1000)
    max_k = int(rpm_redline // 1000)
    for k in range(0, max_k + 1):
        frac = k / max(1, max_k)
        ang = a0 + (a1 - a0) * frac
        ca, sa = math.cos(ang), math.sin(ang)
        r0 = g_r - sc(8)
        r1 = g_r + sc(2)
        color = (220, 80, 80) if k >= max_k - 1 else (180, 180, 190)
        x0, y0 = int(gcx + ca * r0), int(gcy + sa * r0)
        x1, y1 = int(gcx + ca * r1), int(gcy + sa * r1)
        pygame.draw.line(ui_surf, color, (x0, y0), (x1, y1), max(1, sc(2 if k % 2 == 0 else 1)))

        # numeric labels: 1000->"1", 2000->"2", ... skip 0
        if k >= 1:
            r_label = g_r + sc(10)
            lx = int(gcx + ca * r_label)
            ly = int(gcy + sa * r_label)
            fs = pygame.font.SysFont(None, max(1, int(font_small.get_height() * s)))
            ts = fs.render(str(k), True, const.GREY_200)
            ui_surf.blit(ts, (lx - ts.get_width() // 2, ly - ts.get_height() // 2))

    # needle
    ang = angle_for_rpm(rpm)
    nx = int(gcx + math.cos(ang) * (g_r - sc(12)))
    ny = int(gcy + math.sin(ang) * (g_r - sc(12)))
    needle_color = (240, 80, 80) if rpm > rpm_redline * 0.9 else (240, 220, 220)
    pygame.draw.line(ui_surf, needle_color, (gcx, gcy), (nx, ny), max(1, sc(3)))
    pygame.draw.circle(ui_surf, (30, 30, 36), (gcx, gcy), sc(6))

    # gauge label
    fs = pygame.font.SysFont(None, max(1, int(font_small.get_height() * s)))
    lbl_rpm = fs.render("RPM", True, const.WHITE_240)
    ui_surf.blit(lbl_rpm, (gcx - lbl_rpm.get_width()//2, y + sc(6)))
    small = fs.render("x1000", True, const.GREY_180)
    ui_surf.blit(small, (gcx - small.get_width()//2, y + hud_h - sc(18)))

    # --- Steering wheel (middle) ---
    wcx = x + gauge_size + sc(20) + wheel_size // 2
    wcy = y + hud_h // 2
    wheel_r = wheel_size // 2 - sc(6)
    pygame.draw.circle(ui_surf, (40, 40, 48), (wcx, wcy), wheel_r + sc(6))  # rim shadow
    pygame.draw.circle(ui_surf, (20, 20, 26), (wcx, wcy), wheel_r + sc(4))
    pygame.draw.circle(ui_surf, (60, 60, 70), (wcx, wcy), wheel_r, max(1, sc(6)))   # rim

    # steering indicator (spoke)
    MAX_WHEEL_ANGLE = math.radians(270)  # visual rotation range
    angle = st * MAX_WHEEL_ANGLE - (math.pi / 2)  # negative so positive steering rotates clockwise visually
    sx = int(wcx + math.cos(angle) * (wheel_r - sc(10)))
    sy = int(wcy + math.sin(angle) * (wheel_r - sc(10)))
    pygame.draw.line(ui_surf, (200, 200, 220), (wcx, wcy), (sx, sy), max(1, sc(6)))
    # small center hub
    pygame.draw.circle(ui_surf, (30, 30, 36), (wcx, wcy), sc(8))

    # Labels
    fs = pygame.font.SysFont(None, max(1, int(font_small.get_height() * s)))
    lbl = fs.render("STEER", True, const.WHITE_240)
    ui_surf.blit(lbl, (wcx - lbl.get_width()//2, y + hud_h - sc(18)))

    # --- throttle and brake bars (right side) ---
    bar_x = x + gauge_size + wheel_size + sc(30)
    bar_w = hud_w - (gauge_size + wheel_size + sc(32))
    bar_h = sc(16)
    # Throttle bar (top)
    th_y = y + sc(25)
    pygame.draw.rect(ui_surf, (40, 40, 48), (bar_x, th_y, bar_w, bar_h), border_radius=sc(4))
    if th > 0:
        fg_w = int(bar_w * clamp(th, 0.0, 1.0))
        pygame.draw.rect(ui_surf, (80, 220, 100), (bar_x, th_y, fg_w, bar_h), border_radius=sc(4))
    else:
        # reverse/backwards shown as orange to the left of bar
        fg_w = int(bar_w * clamp(-th, 0.0, 1.0))
        pygame.draw.rect(ui_surf, (255, 160, 60), (bar_x + bar_w - fg_w, th_y, fg_w, bar_h), border_radius=sc(4))
    th_pct = int(th * 100) if th >= 0 else int(th * 100)
    fs = pygame.font.SysFont(None, max(1, int(font_small.get_height() * s)))
    lbl_th = fs.render(f"THR {th_pct:+d}%", True, const.WHITE_240)
    ui_surf.blit(lbl_th, (bar_x, th_y - sc(18)))

    # Brake bar (bottom)
    br_y = th_y + bar_h + sc(25)
    pygame.draw.rect(ui_surf, (40, 40, 48), (bar_x, br_y, bar_w, bar_h), border_radius=sc(4))
    fg_wb = int(bar_w * clamp(br, 0.0, 1.0))
    pygame.draw.rect(ui_surf, (220, 80, 80), (bar_x, br_y, fg_wb, bar_h), border_radius=sc(4))
    lbl_br = fs.render(f"BRK {int(br*100):d}%", True, const.WHITE_240)
    ui_surf.blit(lbl_br, (bar_x, br_y - sc(18)))

    # Optional thin border around HUD
    pygame.draw.rect(ui_surf, (80, 88, 100), (x, y, hud_w, hud_h), max(1, sc(1)))
