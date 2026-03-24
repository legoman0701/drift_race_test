import json, drift.config.const as const
from drift.ui.ui_helpers import invalidate_ui_text_cache

def close_settings():
    return "" # stage2

def leave_room(sock, code, my_id, remotes, ai_cars, renderer):
    if sock and code:
        try:
            sock.send(json.dumps({"t": "bye", "code": code, "id": my_id}).encode("utf-8"))
            sock.close()
        except Exception:
            pass
    remotes.clear()
    ai_cars.clear()
    const.AI_PATH_FOLLOW = False
    const.CURSOR_FOLLOW = False
    invalidate_ui_text_cache('room')  # Clear cached room code text
    # Clear tire marks and chunk cache to free memory
    renderer.clear_tire_marks()
    renderer.clear_chunk_cache()
    return "home", "", None, None, remotes # stage1, stage2 sock, code, remotes

def switch_cursor_follow_mode():
    const.CURSOR_FOLLOW = not const.CURSOR_FOLLOW
    if const.CURSOR_FOLLOW: const.AI_PATH_FOLLOW = False
    return "" # stage2

def switch_ai_path_mode():
    const.AI_PATH_FOLLOW = not const.AI_PATH_FOLLOW
    if const.AI_PATH_FOLLOW: const.CURSOR_FOLLOW = False
    return "" # stage2

def handle_controls():
    return "controls" # stage3
