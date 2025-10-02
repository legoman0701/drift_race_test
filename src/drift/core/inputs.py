import math,  pygame # global
from typing import Optional, Dict, Any

import drift.config.const as const # local


def get_text_input(surface: pygame.Surface, title_text: str, tip_text: str,
                   font_big: pygame.font.Font, font_small: pygame.font.Font,
                   allowed_set: Optional[str] = None) -> Optional[str]:
    pygame.key.set_repeat(const.KEY_REPEAT_DELAY, const.KEY_REPEAT_INTERVAL)
    text = ""
    while True:
        surface.fill((20, 20, 25))
        # caller draws UI frame around if needed
        from drift.ui.ui import draw_track_ui  # local import to avoid cycle
        draw_track_ui(surface)
        title = font_big.render("Joining", True, const.WHITE_240)
        surface.blit(title, (const.WINDOW_WIDTH // 2 - title.get_width() // 2, const.TITLE_Y))
        title = font_big.render(title_text, True, (230, 230, 240))
        surface.blit(title, (const.WINDOW_WIDTH // 2 - title.get_width() // 2, const.WINDOW_HEIGHT // 2 - 70))
        disp_text = text if text else "(empty)"
        inp = font_big.render(disp_text, True, (180, 255, 180))
        surface.blit(inp, (const.WINDOW_WIDTH // 2 - inp.get_width() // 2, const.WINDOW_HEIGHT // 2 - 10))
        tip = font_small.render(tip_text, True, (180, 180, 180))
        surface.blit(tip, (const.WINDOW_WIDTH // 2 - tip.get_width() // 2, const.WINDOW_HEIGHT // 2 + 40))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); raise SystemExit(0)
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN:
                    return text or None
                if ev.key == const.ESCAPE_KEY:
                    return None
                if ev.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                else:
                    ch = ev.unicode.upper() if allowed_set is not None else ev.unicode
                    if allowed_set is None or (ch in allowed_set):
                        if len(text) < const.MAX_CODE_LENGTH:
                            text += ch


def get_code_input(surface, font_big, font_small):
    return get_text_input(surface,
                          "Enter ROOM CODE (A-Z/0-9)",
                          "Enter : validate  -  Esc : cancel",
                          font_big, font_small, allowed_set=const.ROOM_ALPHABET)


def get_name_input(surface, font_big, font_small, tag):
    pygame.key.set_repeat(const.KEY_REPEAT_DELAY, const.KEY_REPEAT_INTERVAL)
    text = ""
    error_msg = ""
    from drift.ui.ui import draw_track_ui  # local import to avoid cycle
    while True:
        surface.fill((20, 20, 25))
        draw_track_ui(surface)
        title = font_big.render("Hosting" if tag == "host" else "Joining", True, const.WHITE_240)
        surface.blit(title, (const.WINDOW_WIDTH // 2 - title.get_width() // 2, const.TITLE_Y))
        title = font_big.render("Enter your name", True, (230, 230, 240))
        surface.blit(title, (const.WINDOW_WIDTH // 2 - title.get_width() // 2, const.WINDOW_HEIGHT // 2 - 70))
        disp_text = text if text else "(empty)"
        inp = font_big.render(disp_text, True, (180, 255, 180))
        surface.blit(inp, (const.WINDOW_WIDTH // 2 - inp.get_width() // 2, const.WINDOW_HEIGHT // 2 - 10))
        tip = font_small.render("Enter : OK  -  Esc : cancel", True, (180, 180, 180))
        surface.blit(tip, (const.WINDOW_WIDTH // 2 - tip.get_width() // 2, const.WINDOW_HEIGHT // 2 + 40))
        if error_msg:
            error_surf = font_big.render(error_msg, True, (230, 80, 80))
            surface.blit(error_surf, (const.WINDOW_WIDTH // 2 - error_surf.get_width() // 2, const.WINDOW_HEIGHT // 2 - 120))
        pygame.display.flip()
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                pygame.quit(); raise SystemExit(0)
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_RETURN:
                    if text.upper() in const.PROFANITY_SET:
                        error_msg = "Inappropriate name. Choose another."
                        continue
                    if len(text) < const.MIN_NAME_LENGTH:
                        error_msg = "Name must be at least 3 characters long."
                        continue
                    return text
                if ev.key == const.ESCAPE_KEY:
                    return None
                if ev.key == pygame.K_BACKSPACE:
                    text = text[:-1]
                    error_msg = ""
                else:
                    ch = ev.unicode
                    if ch.isprintable() and len(text) < const.MAX_NAME_LENGTH:
                        text += ch
                        error_msg = ""


def read_inputs(joysticks, car, cam, mouse_follow_mode: bool, ai_path_mode: bool) -> Dict[str, float]:
    keys = pygame.key.get_pressed()
    th = (1 if any(keys[key] for key in const.UP_KEY) else 0) - (1 if any(keys[key] for key in const.DOWN_KEY) else 0)
    st = (1 if any(keys[key] for key in const.RIGHT_KEY) else 0) - (1 if any(keys[key] for key in const.LEFT_KEY) else 0)
    br = 1.0 if keys[const.BRAKE_KEY] else 0.0
    if th != 0:
        th = 1.0 if th > 0 else -1.0
    if st != 0:
        st = 1.0 if st > 0 else -1.0

    if mouse_follow_mode:
        mouse_pos = pygame.mouse.get_pos()
        mous_vec = (mouse_pos[0] - car.x + cam.x - const.WINDOW_WIDTH / 2,
                    mouse_pos[1] - car.y + cam.y - const.WINDOW_HEIGHT / 2)
        mag = math.sqrt(mous_vec[0] ** 2 + mous_vec[1] ** 2) or 1.0
        mous_vec = (mous_vec[0] / mag, mous_vec[1] / mag)

        error = (math.atan2(mous_vec[0], mous_vec[1]) - math.pi / 2 + car.angle + math.pi) % (2 * math.pi) - math.pi
        st = -error * 2

    if joysticks and joysticks[0] != []:
        js = joysticks[0]
        steering = js.get_axis(0)
        throttle = (js.get_axis(5) + 1) / 2
        breaks = (js.get_axis(4) + 1) / 2
        if not ai_path_mode:
            st = steering if steering != 0 else st
            th = throttle if throttle != 0 else th
            br = breaks if breaks != 0 else br
    return {"th": float(th), "st": float(st), "br": float(br)}
