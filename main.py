#!/usr/bin/env python3
"""
Top-down drift game client with camera (zoom & pan)
Refactored to remove magic numbers and reduce spaghetti code.
"""

try: import pygame_ce as pygame
except Exception: import pygame ; print("failed to load pygame-ce")
import socket, json, time, random, string, sys, math, uuid, argparse # global imports
import camera, car, button as btn, path_finder # local imports
import const
from helpers import clamp, rand_code, rand_name, car_local_to_world
from ai import ai_algorithme
from inputs import get_text_input, get_code_input, get_name_input, read_inputs
from communication import connect_to_relay, handle_network_messages, send_network_state, send_ai_states, send_ping, recv_jsons
from ui import draw_car, draw_track_ui, draw_menu, handle_menu_events, handle_game_events

# ======= CONFIGURATION =======
RELAY_PUBLIC_ENDPOINT = const.RELAY_PUBLIC_ENDPOINT
# Host/Join role flag: set True when this client creates a room, False when joining
I_AM_HOST = False

ai_path_mode = False
mouse_follow_mode = False
flags = const.FLAGS

# =============================

    

def main():
    global I_AM_HOST  # ensure all references/assignments in this function use the module global
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["host", "join"])
    parser.add_argument("--code")
    parser.add_argument("--name")
    args, unknown = parser.parse_known_args()

    pygame.init()
    pygame.joystick.init()
    screen = pygame.display.set_mode((const.WINDOW_WIDTH, const.WINDOW_HEIGHT))
    pygame.display.set_caption("Drift Race Test")
    clock = pygame.time.Clock()
    font_small = pygame.font.SysFont(None, const.FONT_SMALL_SIZE)
    font_medium = pygame.font.SysFont(None, const.FONT_MEDIUM_SIZE)
    font_big = pygame.font.SysFont(None, const.FONT_BIG_SIZE)

    # Load car sprites
    ae86_sprite = []
    for i in range(32):
        img = pygame.image.load(f"assets/AE86/Diffuse/Image{i:04}.png").convert_alpha()
        ae86_sprite.append(img)
    
    shadow_sprite = []
    for i in range(32):
        img = pygame.image.load(f"assets/AE86/Shadow_Map/Image{i:04}.png").convert_alpha()
        shadow_sprite.append(img)
    
    light_spray_sprite = []
    for i in range(32):
        img = pygame.image.load(f"assets/AE86/Light_Spray/{i:04}.png").convert_alpha()
        light_spray_sprite.append(img)
        
    track_image = pygame.image.load(f"assets/Map/Map1.png").convert()

    stage = "menu"  # menu | playing | settings | keys | error
    error_msg = ""
    remotes = {}
    ai_cars = []
    path_poly = []

    my_name = rand_name()
    my_id = str(uuid.uuid4())[:8]
    code = None
    sock = None
    last_state_send = 0.0
    last_ping = 0.0

    lights_on = True

    spawnx = random.randint(const.TRACK_MARGIN + 200, const.WINDOW_WIDTH - const.TRACK_MARGIN - 200)
    spawny = random.randint(const.TRACK_MARGIN + 120, const.WINDOW_HEIGHT - const.TRACK_MARGIN - 120)
    my_car = car.Car(spawnx, spawny, my_name, is_ai=False)

    if args.mode == "host" and args.code and args.name:
        my_name = args.name
        my_car.name = my_name
        code = args.code
        try:
            sock = connect_to_relay()
            join_pkt = {"t": "create", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
            # Wait briefly for confirmation; otherwise offline fallback
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
            if join_ok_received:
                stage = "playing"
                I_AM_HOST = True  # set host flag for CLI host mode
            else:
                raise Exception("no join_ok")
        except Exception:
            # Offline fallback
            sock = None
            code = "Offline"
            stage = "playing"
            I_AM_HOST = True
    elif args.mode == "join" and args.code and args.name:
        my_name = args.name
        my_car.name = my_name
        code = args.code
        try:
            sock = connect_to_relay()
            code = code.upper()
            join_pkt = {"t": "join", "code": code, "name": my_name, "id": my_id}
            sock.send(json.dumps(join_pkt).encode("utf-8"))
            # Wait briefly for confirmation; otherwise offline fallback
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
            if join_ok_received:
                stage = "playing"
                I_AM_HOST = False  # set host flag for CLI join mode
            else:
                raise Exception("no join_ok")
        except Exception:
            # Offline fallback
            sock = None
            code = "Offline"
            stage = "playing"
            I_AM_HOST = False
    
    tire_mark = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), pygame.SRCALPHA)
    tire_mark.fill((255, 255, 255, 0))
    
    drift_points_old_remotes = {}

    joysticks = [pygame.joystick.Joystick(i) for i in range(pygame.joystick.get_count())]
    for js in joysticks:
        js.init()

    # Create a camera object; mouse wheel will adjust zoom and middle mouse drag will pan.
    cam = camera.Camera(const.WINDOW_WIDTH, const.WINDOW_HEIGHT, zoom=1.0)
    dragging = False
    host_ref = [I_AM_HOST]

    def leave_room(sock, code, my_id, remotes):
        global ai_path_mode, mouse_follow_mode
        if sock and code:
            try:
                sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                sock.close()
            except Exception:
                pass
        remotes.clear()
        ai_cars.clear()
        ai_path_mode = False
        mouse_follow_mode = False
        # stage, sock, code, remotes
        return "menu", None, None, remotes

    def show_key_binds(): # to do
        print("Showing key binds...")
        
    def switch_steering_mode():
        global mouse_follow_mode, ai_path_mode
        # toggle mouse follow; when enabling mouse follow, ensure AI path mode is disabled
        mouse_follow_mode = not mouse_follow_mode
        try:
            if mouse_follow_mode:
                ai_path_mode = False
        except Exception:
            pass
        # Close settings panel by returning the state tuple (new_stage, sock, code, remotes)
        try:
            return "playing", sock, code, remotes
        except Exception:
            return "playing", None, None, {}

    def switch_ai_path_mode():
        global ai_path_mode, mouse_follow_mode
        # toggle AI path mode; when enabling AI, ensure mouse follow is disabled
        ai_path_mode = not ai_path_mode
        try:
            if ai_path_mode:
                mouse_follow_mode = False
        except Exception:
            pass
        try:
            return "playing", sock, code, remotes
        except Exception:
            return "playing", None, None, {}

    buttons = [
    btn.Button("Leave Room", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.3, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, lambda: leave_room(sock, code, my_id, remotes)),
    btn.Button("Cursor Follow Mode", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.6, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, switch_steering_mode),
    btn.Button("AI Path Mode", const.WINDOW_WIDTH//2-const.BTN_WIDTH//2, const.WINDOW_HEIGHT*0.72, const.BTN_WIDTH, const.BTN_HEIGHT, const.RED, switch_ai_path_mode),
    ]

    while True:
        dt = clock.tick(const.FPS) / 1000.0
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                if sock and code:
                    try: sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
                    except Exception: pass
                pygame.quit()
                sys.exit(0)

            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_l:
                lights_on = not lights_on
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_n:
                if I_AM_HOST and stage == "playing":
                    ai_cars.append(
                        car.Car(
                            random.randint(const.TRACK_MARGIN + 200, const.WINDOW_WIDTH - const.TRACK_MARGIN - 200),
                            random.randint(const.TRACK_MARGIN + 120, const.WINDOW_HEIGHT - const.TRACK_MARGIN - 120),
                            name=f"AI-{len(ai_cars)+1}",
                            is_ai=True,
                        )
                    )
                
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

            ev, stage, remotes, sock, code, my_car, error_msg = handle_game_events(screen, ev, stage, remotes, sock, code, my_name, my_id, my_car, font_big, font_small, error_msg, host_ref)
            I_AM_HOST = host_ref[0]

        if sock:
            err = handle_network_messages(sock, remotes, dt, my_id, I_AM_HOST)
            if err:
                # Switch to offline on relay errors
                try:
                    sock.close()
                except Exception:
                    pass
                sock = None
                code = "Offline"
                remotes.clear()

        if sock and code and code != "Offline":
            now = time.time()
            if now - last_state_send >= 1.0 / const.SEND_HZ:
                last_state_send = now
                send_network_state(sock, code, my_id, my_car)
                if I_AM_HOST and ai_cars:
                    send_ai_states(sock, code, ai_cars)
            if now - last_ping >= 1.0 / const.PING_HZ:
                last_ping = now
                send_ping(sock, code)
                
        
        
        # Build world size tuple used by step()
        world_size = (const.WINDOW_WIDTH, const.WINDOW_HEIGHT) if stage != "playing" else (track_image.get_width(), track_image.get_height())

        # Prepare remotes view for the player: include network remotes + AI cars (so player can collide with AIs)
        remotes_with_ai_for_player = dict(remotes)
        if I_AM_HOST:
            for i, ai in enumerate(ai_cars, start=1):
                key = f"AI-{i}"
                remotes_with_ai_for_player[key] = {"x": ai.x, "y": ai.y, "a": ai.angle, "drift_ratio": ai.drift_ratio, "name": ai.name}

        # Update player car using remotes that include AIs
        # If AI path mode is enabled and a path is available, let the AI drive the player
        controls = None
        if ai_path_mode and path_poly:
            try:
                controls, ai_debug_surface = ai_algorithme(path_poly, my_car, ai_path_mode=True, surface=pygame.Surface((track_image.get_width(), track_image.get_height()), pygame.SRCALPHA), font_small=font_small)
            except Exception:
                controls = None
        if controls is None:
            controls = read_inputs(joysticks, my_car, cam, mouse_follow_mode, ai_path_mode)
        my_car.step(controls, dt, remotes_with_ai_for_player, world_size)

        # Prepare remotes view for AIs: include network remotes + all AIs + the local player (so AIs can detect collisions with player)
        remotes_with_ai_for_ais = dict(remotes)
        if I_AM_HOST:
            # add local player under a distinct key so AIs see it
            remotes_with_ai_for_ais[f"PLAYER-{my_id}"] = {"x": my_car.x, "y": my_car.y, "a": my_car.angle, "drift_ratio": my_car.drift_ratio, "name": my_car.name}
            for i, ai in enumerate(ai_cars, start=1):
                key = f"AI-{i}"
                remotes_with_ai_for_ais[key] = {"x": ai.x, "y": ai.y, "a": ai.angle, "drift_ratio": ai.drift_ratio, "name": ai.name}

        # Step AIs (each AI sees other AIs + network remotes + the player)
        if I_AM_HOST:
            for ai in ai_cars:
                ai.step(ai_algorithme(path_poly, ai), dt, remotes_with_ai_for_ais, world_size)
        cam.update(my_car, (const.WINDOW_WIDTH, const.WINDOW_HEIGHT) if stage != "playing" else (track_image.get_width(), track_image.get_height()))

        # Draw game world onto an off-screen surface.
        if stage != "playing":
            world_surf = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), flags)
            world_surf.fill(const.GREY_20)
        else:
            world_surf = pygame.Surface((track_image.get_width(), track_image.get_height()), flags)
            # Calculate the camera viewport in the track image coordinates.
            
            top_right_pos = cam.x-(const.WINDOW_WIDTH/2)/cam.zoom, cam.y-(const.WINDOW_HEIGHT/2)/cam.zoom
            camera_rect = pygame.Rect(top_right_pos[0],
                                      top_right_pos[1],
                                      const.WINDOW_WIDTH/cam.zoom,
                                      const.WINDOW_HEIGHT/cam.zoom)
            visible_track = track_image.subsurface(camera_rect)
            #pygame.draw.rect(world_surf, TRACK_COLOR, camera_rect)
            world_surf.blit(visible_track, top_right_pos)

        if tire_mark.get_width() != world_surf.get_width() or tire_mark.get_height() != world_surf.get_height():
            tire_mark = pygame.Surface((world_surf.get_width(), world_surf.get_height()), pygame.SRCALPHA)
            tire_mark.fill((255, 255, 255, 0))
            path_poly = path_finder.discover_track("assets/Map/Map1.png")
        
        ui_surf = pygame.Surface((const.WINDOW_WIDTH, const.WINDOW_HEIGHT), pygame.SRCALPHA)
        ui_surf.fill((0,0,0,0)) # transparent surface
        
        draw_track_ui(ui_surf)
        # world_surf.blit(bg_map, (0, 0))
        
        if my_car.drift_ratio > 0.5 and my_car.drift_points_old:
            pygame.draw.line(tire_mark, const.TIRE_MARK_SMOKE, my_car.drift_points[0], my_car.drift_points_old[0], 3)
            pygame.draw.line(tire_mark, const.TIRE_MARK_SMOKE, my_car.drift_points[1], my_car.drift_points_old[1], 3)
        
        for ai_car in ai_cars:
            draw_car(world_surf, ai_car.x, ai_car.y, ai_car.angle, ai_car.name,
                                  color_body=const.COLOR_BODY_DEFAULT, car_sprites_list=[shadow_sprite, ae86_sprite, light_spray_sprite], lights_on=lights_on)

            if ai_car.drift_ratio > 0.5 and ai_car.drift_points_old:
                pygame.draw.line(tire_mark, const.TIRE_MARK_SMOKE, ai_car.drift_points[0], ai_car.drift_points_old[0], 3)
                pygame.draw.line(tire_mark, const.TIRE_MARK_SMOKE, ai_car.drift_points[1], ai_car.drift_points_old[1], 3)

        # fade smoke to ground and draw visible segment
        tire_mark.fill(const.TIRE_MARK_GROUND, special_flags=pygame.BLEND_RGBA_MULT)
        top_right_pos = (cam.x - (const.WINDOW_WIDTH/2)/cam.zoom,
                         cam.y - (const.WINDOW_HEIGHT/2)/cam.zoom)
        camera_rect = pygame.Rect(top_right_pos[0],
                                  top_right_pos[1],
                                  const.WINDOW_WIDTH/cam.zoom,
                                  const.WINDOW_HEIGHT/cam.zoom)
        visible_tire_mark = tire_mark.subsurface(camera_rect)
        world_surf.blit(visible_tire_mark, top_right_pos)
        
        draw_car(world_surf, my_car.x, my_car.y, my_car.angle, my_car.name,
                                                                    color_body=const.COLOR_MY_CAR, car_sprites_list=[shadow_sprite, ae86_sprite, light_spray_sprite], lights_on=lights_on)
        

        if stage == "menu":
            cam.zoom = 1
            title = font_big.render("Menu", True, const.WHITE_240)
            ui_surf.blit(title, (const.WINDOW_WIDTH//2 - title.get_width()//2, const.TITLE_Y))
            tip1 = font_medium.render("H : Host room", True, const.GREY_200)
            tip2 = font_medium.render("J : Join room", True, const.GREY_200)
            relay = font_small.render(f"Relay: {RELAY_PUBLIC_ENDPOINT}", True, const.GREY_180)
            ui_surf.blit(tip1, (int(const.WINDOW_WIDTH*.3 - tip1.get_width()//2), const.TIP1_Y))
            ui_surf.blit(tip2, (int(const.WINDOW_WIDTH*.7 - tip2.get_width()//2), const.TIP2_Y))
            ui_surf.blit(relay, (const.WINDOW_WIDTH//2 - relay.get_width()//2, const.RELAY_Y))

        if stage == "playing":
            title = font_big.render("Waiting for players", True, const.WHITE_240)
            ui_surf.blit(title, (const.WINDOW_WIDTH//2 - title.get_width()//2, const.TITLE_Y))
            room_label = code if code else "Offline"
            hud = font_small.render(f"Room: {room_label}", True, const.GREY_180)
            ui_surf.blit(hud, (10, const.RELAY_Y))
            # HUD: steering wheel + throttle/brake % bars (bottom-right)
            inp = read_inputs(joysticks, my_car, cam, mouse_follow_mode, ai_path_mode)
            th = clamp(inp.get("th", 0.0), -1.0, 1.0)
            br = clamp(inp.get("br", 0.0), 0.0, 1.0)
            st = clamp(inp.get("st", 0.0), -1.0, 1.0)

            # HUD layout
            hud_w = 200
            hud_h = 96
            pad = 12
            x = const.WINDOW_WIDTH - hud_w - pad
            y = const.WINDOW_HEIGHT - hud_h - pad

            # semi-transparent background
            bg = pygame.Surface((hud_w, hud_h), pygame.SRCALPHA)
            bg.fill((10, 10, 14, 200))
            ui_surf.blit(bg, (x, y))

            # steering wheel (left side)
            wheel_size = 76
            wcx = x + wheel_size // 2 + 10
            wcy = y + hud_h // 2
            wheel_r = wheel_size // 2 - 6
            pygame.draw.circle(ui_surf, (40, 40, 48), (wcx, wcy), wheel_r + 6)  # rim shadow
            pygame.draw.circle(ui_surf, (20, 20, 26), (wcx, wcy), wheel_r + 4)
            pygame.draw.circle(ui_surf, (60, 60, 70), (wcx, wcy), wheel_r, 6)   # rim

            # steering indicator (spoke)
            MAX_WHEEL_ANGLE = math.radians(270)  # visual rotation range
            angle = st * MAX_WHEEL_ANGLE - (math.pi / 2)  # negative so positive steering rotates clockwise visually
            sx = int(wcx + math.cos(angle) * (wheel_r - 10))
            sy = int(wcy + math.sin(angle) * (wheel_r - 10))
            pygame.draw.line(ui_surf, (200, 200, 220), (wcx, wcy), (sx, sy), 6)
            # small center hub
            pygame.draw.circle(ui_surf, (30, 30, 36), (wcx, wcy), 8)

            # Labels
            lbl = font_small.render("STEER", True, const.WHITE_240)
            ui_surf.blit(lbl, (wcx - lbl.get_width()//2, y + hud_h - 18))

            # throttle and brake bars (right side)
            bar_x = x + wheel_size + 20
            bar_w = hud_w - (wheel_size + 32)
            bar_h = 16
            # Throttle bar (top)
            th_y = y + 18
            pygame.draw.rect(ui_surf, (40, 40, 48), (bar_x, th_y, bar_w, bar_h), border_radius=4)
            if th > 0:
                fg_w = int(bar_w * clamp(th, 0.0, 1.0))
                pygame.draw.rect(ui_surf, (80, 220, 100), (bar_x, th_y, fg_w, bar_h), border_radius=4)
            else:
                # reverse/backwards shown as orange to the left of bar
                fg_w = int(bar_w * clamp(-th, 0.0, 1.0))
                pygame.draw.rect(ui_surf, (255, 160, 60), (bar_x + bar_w - fg_w, th_y, fg_w, bar_h), border_radius=4)
            th_pct = int(th * 100) if th >= 0 else int(th * 100)
            lbl_th = font_small.render(f"THR {th_pct:+d}%", True, const.WHITE_240)
            ui_surf.blit(lbl_th, (bar_x, th_y - 18))

            # Brake bar (bottom)
            br_y = th_y + bar_h + 18
            pygame.draw.rect(ui_surf, (40, 40, 48), (bar_x, br_y, bar_w, bar_h), border_radius=4)
            fg_wb = int(bar_w * clamp(br, 0.0, 1.0))
            pygame.draw.rect(ui_surf, (220, 80, 80), (bar_x, br_y, fg_wb, bar_h), border_radius=4)
            lbl_br = font_small.render(f"BRK {int(br*100):d}%", True, const.WHITE_240)
            ui_surf.blit(lbl_br, (bar_x, br_y - 18))

            # Optional thin border around HUD
            pygame.draw.rect(ui_surf, (80, 88, 100), (x, y, hud_w, hud_h), 1)
            for pid, d in remotes.items():
                drift_points_remote = draw_car(world_surf, d["x"], d["y"], d["a"], d.get("name", f"Player{pid}"),
                                               color_body=const.COLOR_BODY_REMOTE, car_sprites_list=[shadow_sprite, ae86_sprite, light_spray_sprite], lights_on=lights_on)
                if d["drift_ratio"] > 0.8 and pid in drift_points_old_remotes:
                    old_pts = drift_points_old_remotes[pid]
                    if drift_points_remote != None:
                        pygame.draw.line(tire_mark, const.TIRE_MARK_SMOKE, drift_points_remote[0], old_pts[0], 3)
                        pygame.draw.line(tire_mark, const.TIRE_MARK_SMOKE, drift_points_remote[1], old_pts[1], 3)
                drift_points_old_remotes[pid] = drift_points_remote

        if stage == "settings":
            title = font_big.render("Settings", True, const.WHITE_240)
            ui_surf.blit(title, (const.WINDOW_WIDTH//2 - title.get_width()//2, const.TITLE_Y))
            # Draw buttons and capture any action results. If an action returns a tuple
            # with new state (stage, sock, code, remotes), apply it.
            for button in buttons:
                # Update button labels/colors for stateful buttons
                try:
                    if button.action == switch_steering_mode:
                        if mouse_follow_mode:
                            button.text = "Mouse Following : On"
                            button.color = const.GREEN
                        else:
                            button.text = "Mouse Following : Off"
                            button.color = const.RED
                    if button.action == switch_ai_path_mode:
                        if ai_path_mode:
                            button.text = "AI Path Mode : On"
                            button.color = const.GREEN
                        else:
                            button.text = "AI Path Mode : Off"
                            button.color = const.RED
                except Exception:
                    pass
                res = button.draw(ui_surf)
                if isinstance(res, tuple) and len(res) == 4:
                    # expected return: (new_stage, new_sock, new_code, new_remotes)
                    new_stage, new_sock, new_code, new_remotes = res
                    stage = new_stage
                    sock = new_sock
                    code = new_code
                    remotes = new_remotes
            # world_surf.blit(btn_screen, (0, 0))

        if stage == "error":
            errh = font_big.render("ERROR", True, (255,120,120))
            ui_surf.blit(errh, (const.WINDOW_WIDTH//2 - errh.get_width()//2, const.WINDOW_HEIGHT//2 - 40))
            msg = font_small.render(error_msg, True, (255,200,200))
            ui_surf.blit(msg, (const.WINDOW_WIDTH//2 - msg.get_width()//2, const.WINDOW_HEIGHT//2))
            tip = font_small.render("Press R to restart", True, const.GREY_200)
            ui_surf.blit(tip, (const.WINDOW_WIDTH//2 - tip.get_width()//2, const.WINDOW_HEIGHT//2 + 40))

        # Apply camera transform (zoom & pan) and blit to screen.
        final_surf = cam.apply(world_surf)
        screen.blit(final_surf, (0,0))
        screen.blit(ui_surf, (0,0))
        if ai_path_mode and stage == "playing":
            try:
                top_right_pos = cam.x-(const.WINDOW_WIDTH/2)/cam.zoom, cam.y-(const.WINDOW_HEIGHT/2)/cam.zoom
                camera_rect = pygame.Rect(top_right_pos[0],
                                        top_right_pos[1],
                                        const.WINDOW_WIDTH/cam.zoom,
                                        const.WINDOW_HEIGHT/cam.zoom)
                visible_ai_debug_surface = ai_debug_surface.subsurface(camera_rect)
                #pygame.draw.rect(world_surf, TRACK_COLOR, camera_rect)
                screen.blit(visible_ai_debug_surface, (0, 0))
            except Exception:
                pass
        pygame.display.flip()

if __name__ == "__main__":
    main()
    