import math
import time
import json
import pygame
from typing import Dict, Any, Optional, Tuple

import const
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

    if name:
        font = pygame.font.SysFont(None, 22)
        text = font.render(name, True, (230, 230, 255))
        surface.blit(text, (int(x - text.get_width() / 2), int(y - 40)))


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
