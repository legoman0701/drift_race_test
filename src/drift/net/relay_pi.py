#!/usr/bin/env python3
# relay_pi_trust.py — UDP room relay that TRUSTS client states (no server-side physics)
# Expose via Playit.gg: william-allow.gl.at.ply.gg:4800 => 127.0.0.1:40123 (UDP)

import socket, json, time, random

RELAY_HOST = "0.0.0.0"
RELAY_PORT = 40123
MAX_PACKET = 1400
CLIENT_TIMEOUT = 15.0   # seconds since last packet before drop
WORLD_HZ = 60.0         # broadcast world snapshots at most this often
TICK = 0.01             # main loop tick

# Rooms:
#   code -> {
#       "clients": { addr: {"id","name", "car_type","last"} },
#       "states":  { id: {"x","y","a","vx","vy","name", "has_grip", "car_type"} },
#       "results": { id: {"time","name","car_type"} },
#       "host_addr": tuple|None,   # address of the creator
#       "host_id": str,            # id of the creator
#       "mode": str,               # selected game mode for room starts
#       "race_started": bool,
#       "last_broadcast": float,
#       "dirty": bool
#   }
rooms = {}


def assign_random_host(room):
    if not room.get("clients"):
        room["host_addr"] = None
        room["host_id"] = ""
        room["host_name"] = ""
        return
    new_addr, new_info = random.choice(list(room["clients"].items()))
    room["host_addr"] = new_addr
    room["host_id"] = new_info.get("id", "")
    room["host_name"] = new_info.get("name", "")


def remove_client_from_room(room, addr=None, pid=None):
    """Remove a client by address and/or player id from one room.

    Returns True if any client entry was removed.
    """
    removed = False
    removed_host = False
    removed_pids = set()

    for caddr, info in list(room["clients"].items()):
        info_pid = info.get("id")
        by_addr = (addr is not None and caddr == addr)
        by_pid = (pid is not None and info_pid == pid)
        if not (by_addr or by_pid):
            continue

        if caddr == room.get("host_addr") or info_pid == room.get("host_id"):
            removed_host = True
        if info_pid:
            removed_pids.add(info_pid)
        room["clients"].pop(caddr, None)
        removed = True

    for rid in removed_pids:
        room["states"].pop(rid, None)
        room.get("results", {}).pop(rid, None)

    if removed_host:
        for sid in list(room["states"].keys()):
            if isinstance(sid, str) and sid.startswith("AI-"):
                room["states"].pop(sid, None)
        room["race_started"] = False
        assign_random_host(room)

    if removed:
        room["dirty"] = True
    return removed


def evict_from_other_rooms(except_code, addr, pid):
    """Ensure a client is active in only one room at a time."""
    for code, room in list(rooms.items()):
        if code == except_code:
            continue
        remove_client_from_room(room, addr=addr, pid=pid)
        if not room.get("clients"):
            rooms.pop(code, None)

def sendto_json(sock, addr, obj):
    try:
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        if len(data) > MAX_PACKET:
            data = b'{"t":"error","msg":"packet_too_big"}'
        sock.sendto(data, addr)
    except Exception:
        pass

def broadcast_world(sock, code, room): # update world screen
    now = time.time()
    room["last_broadcast"] = now
    world = {
        "t": "world",
        "code": code,
        "players": room["states"],
        "results": room.get("results", {}),
        "host_name": room.get("host_name", ""),
        "host_id": room.get("host_id", ""),
        "race_started": bool(room.get("race_started", False)),
        "mode": room.get("mode", "mode1"),
        "track": room.get("track", "track1"),
    }
    for caddr in list(room["clients"].keys()):
        sendto_json(sock, caddr, world)
    room["dirty"] = False

def loop():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((RELAY_HOST, RELAY_PORT))
    sock.settimeout(TICK)
    print(f"[relay] UDP listening on {RELAY_HOST}:{RELAY_PORT}")
    while True:
        now = time.time()

        # Prune idle clients & empty rooms; prune stale states
        for code, room in list(rooms.items()):
            for caddr, info in list(room["clients"].items()):
                if now - info["last"] > CLIENT_TIMEOUT:
                    # drop client and its state
                    pid = info["id"]
                    room["clients"].pop(caddr, None)
                    room["states"].pop(pid, None)
                    room.get("results", {}).pop(pid, None)
                    # if the timed out client was host, purge AI states
                    if caddr == room.get("host_addr") or pid == room.get("host_id"):
                        for sid in list(room["states"].keys()):
                            if isinstance(sid, str) and sid.startswith("AI-"):
                                room["states"].pop(sid, None)
                        room["race_started"] = False
                        assign_random_host(room)
                    room["dirty"] = True
            # remove room if empty
            if not room["clients"]:
                rooms.pop(code, None)
            else:
                # Prune stale AI states that haven't been updated recently
                try:
                    for sid, sinfo in list(room.get("states", {}).items()):
                        if isinstance(sid, str) and sid.startswith("AI-"):
                            last = float(sinfo.get("last", 0.0))
                            if now - last > CLIENT_TIMEOUT:
                                room["states"].pop(sid, None)
                                room.get("results", {}).pop(sid, None)
                                room["dirty"] = True
                except Exception:
                    pass

        # Broadcast worlds for rooms marked dirty (throttled)
        for code, room in list(rooms.items()):
            # dirty -> flag : broadcasting needed
            if room["dirty"] and (now - room["last_broadcast"] >= (1.0 / WORLD_HZ)):
                broadcast_world(sock, code, room)

        # Receive packet
        try:
            data, addr = sock.recvfrom(8192)
        except socket.timeout:
            continue
        except Exception as e:
            print(f"Error receiving packet: {e}")
            continue

        # Parse JSON
        try:
            msg = json.loads(data.decode("utf-8"))
        except Exception:
            sendto_json(sock, addr, {"t":"error","msg":"invalid_json"})
            continue

        mtype = msg.get("t")

        if mtype == "create": # player wants to create a new room
            code = (msg.get("code") or "").upper().strip()
            pid  = (msg.get("id") or "")[:16]
            name = (msg.get("name") or f"Player{pid}")[:24]
            car_type = (msg.get("car_type") or "ae86")[:16]
            mode = (msg.get("mode") or "mode1").strip()
            track = (msg.get("track") or "track1").strip()
            if not code or not pid:
                sendto_json(sock, addr, {"t":"error","msg":"missing_code_or_id"}); continue
            if code in rooms:
                sendto_json(sock, addr, {"t":"error","msg":"room_already_exists"}); continue
            evict_from_other_rooms(code, addr, pid)
            max_players = max(1, min(int(msg.get("max_players", 6)), 16))
            room = {"clients": {}, "states": {}, "results": {}, "host_addr": addr, "host_id": pid, "host_name": name, "mode": mode, "track": track, "max_players": max_players, "race_started": False, "last_broadcast": 0.0, "dirty": True}
            rooms[code] = room
            room["clients"][addr] = {"id": pid, "name": name, "car_type": car_type, "last": now}
            room["states"].setdefault(pid, {"x": 500, "y": 350, "a": 0.0, "vx": 0.0, "vy": 0.0, "name": name, "has_grip": [1.0, 1.0, 1.0, 1.0], "car_type": car_type})
            room["dirty"] = True
            print(f"[relay] Room {code!r} created by {name!r} (id={pid}) | mode={mode} track={track}")
            sendto_json(sock, addr, {"t":"join_ok", "code": code, "host_name": name, "track": track})
            broadcast_world(sock, code, room)

        elif mtype == "join": # player wants to join an existing room
            code = (msg.get("code") or "").upper().strip()
            pid  = (msg.get("id") or "")[:16]
            name = (msg.get("name") or f"Player{pid}")[:24]
            car_type = (msg.get("car_type") or "ae86")[:16]
            if not code or not pid:
                sendto_json(sock, addr, {"t":"error","msg":"missing_code_or_id"}); continue
            room = rooms.get(code)
            if not room:
                sendto_json(sock, addr, {"t":"error","msg":"room_not_found"}); continue
            if room.get("race_started"):
                sendto_json(sock, addr, {"t":"error","msg":"race_in_progress"}); continue
            if len(room["states"]) >= room.get("max_players", 6):
                sendto_json(sock, addr, {"t":"error","msg":"room_full"}); continue
            evict_from_other_rooms(code, addr, pid)
            room["clients"][addr] = {"id": pid, "name": name, "last": now, "car_type": car_type}
            room["states"].setdefault(pid, {"x": 500, "y": 350, "a": 0.0, "vx": 0.0, "vy": 0.0, "name": name, "has_grip": [1.0, 1.0, 1.0, 1.0], "car_type": car_type})
            room["dirty"] = True
            # Send host_name and track from room data
            host_name = room.get("host_name", "no_host")
            player_count = len(room["states"])
            print(f"[relay] {name!r} (id={pid}) joined room {code!r} | players in room: {player_count}")
            sendto_json(sock, addr, {"t":"join_ok", "code": code, "host_name": host_name, "track": room.get("track", "track1")})
            broadcast_world(sock, code, room)

        elif mtype == "state": # get player's physic car status (trigger broadcoast)
            # TRUST client: accept their state into room store
            code = (msg.get("code") or "").upper().strip()
            pid  = (msg.get("id") or "")[:16]
            room = rooms.get(code)
            if not room or addr not in room["clients"]:
                sendto_json(sock, addr, {"t":"error","msg":"room_not_found_or_not_joined"}); continue
            room["clients"][addr]["last"] = now
            # Only the host can publish AI states (ids starting with 'AI-')
            is_ai = isinstance(pid, str) and pid.startswith("AI-")
            if is_ai and room.get("host_addr") != addr:
                # ignore non-host AI updates
                continue
            # Update registered car_type when player changes car mid-session
            if not is_ai:
                new_car_type = msg.get("car_type")
                if isinstance(new_car_type, str) and new_car_type:
                    room["clients"][addr]["car_type"] = new_car_type[:16]
            # Validate and store palette (3 RGB triplets) for car coloring.
            # Both player and AI states can carry a palette; non-host clients
            # use it to render remote/AI cars with the correct colors.
            raw_palette = msg.get("palette")
            if (isinstance(raw_palette, list) and len(raw_palette) == 3 and
                    all(isinstance(c, list) and len(c) == 3 and
                        all(isinstance(v, (int, float)) for v in c) for c in raw_palette)):
                palette = raw_palette
            else:
                palette = None
            st = {
                "x": float(msg.get("x", 0.0)),
                "y": float(msg.get("y", 0.0)),
                "a": float(msg.get("a", 0.0)),
                "vx": float(msg.get("vx", 0.0)),
                "vy": float(msg.get("vy", 0.0)),
                # for AI, trust provided name; for players, use registered name
                "name": (str(msg.get("name")) if is_ai else room["clients"][addr]["name"]),
                "has_grip": list(msg.get("has_grip", [1.0, 1.0, 1.0, 1.0])),
                "car_type": (str(msg.get("car_type")) if is_ai else room["clients"][addr]["car_type"]),
                "palette": palette,
            }
            # timestamp for pruning stale AI states later
            try:
                st["last"] = now
            except Exception:
                pass
            room["states"][pid] = st
            room["dirty"] = True

        elif mtype == "ping": # get user connection information (no broadcast)
            code = (msg.get("code") or "").upper().strip()
            room = rooms.get(code)
            if room and addr in room["clients"]:
                room["clients"][addr]["last"] = now

        elif mtype == "bye": # player leaves
            code = (msg.get("code") or "").upper().strip()
            pid  = (msg.get("id") or "")[:16]
            room = rooms.get(code)
            if not room: 
                continue
            room["clients"].pop(addr, None)
            if pid:
                room["states"].pop(pid, None) # remove player
                room.get("results", {}).pop(pid, None)
            # If the host leaves, purge AI states and clear host markers
            if addr == room.get("host_addr") or pid == room.get("host_id"):
                for sid in list(room["states"].keys()):
                    if isinstance(sid, str) and sid.startswith("AI-"):
                        room["states"].pop(sid, None)
                room["race_started"] = False
                assign_random_host(room)
            room["dirty"] = True # trigger broadcast
            if not room["clients"]: # delete room if empty
                rooms.pop(code, None)

        elif mtype == "start_race":
            code = (msg.get("code") or "").upper().strip()
            pid  = (msg.get("id") or "")[:16]
            room = rooms.get(code)
            if not room or addr not in room["clients"]:
                sendto_json(sock, addr, {"t":"error","msg":"room_not_found_or_not_joined"}); continue
            if addr != room.get("host_addr") or pid != room.get("host_id"):
                sendto_json(sock, addr, {"t":"error","msg":"only_host_can_start"}); continue
            requested_mode = (msg.get("mode") or room.get("mode", "mode1")).strip()
            requested_track = (msg.get("track") or room.get("track", "track1")).strip()

            if requested_track:
                room["track"] = requested_track

            if requested_mode == "lobby":
                room["race_started"] = False
                room["mode"] = "lobby"
                room["results"] = {}
            else:
                room["race_started"] = True
                room["mode"] = requested_mode
                room["results"] = {}

            room["dirty"] = True
            player_count = len(room["states"])
            print(f"[relay] Race started in room {code!r} | mode={requested_mode} track={room.get('track','track1')} players={player_count}")
            # Include the full roster (all state keys) so every client can
            # compute identical spawn-slot assignments, even if some AI states
            # haven't been received yet via world snapshots.
            roster = sorted(room["states"].keys())
            start_msg = {"t": "start_race", "code": code, "mode": requested_mode, "track": room.get("track", "track1"), "roster": roster}
            laps = msg.get("laps")
            if isinstance(laps, int) and 1 <= laps <= 10:
                start_msg["laps"] = laps
            for caddr in list(room["clients"].keys()):
                sendto_json(sock, caddr, start_msg)

        elif mtype == "race_result":
            code = (msg.get("code") or "").upper().strip()
            pid  = (msg.get("id") or "")[:16]
            room = rooms.get(code)
            if not room or addr not in room["clients"]:
                sendto_json(sock, addr, {"t":"error","msg":"room_not_found_or_not_joined"}); continue
            is_ai_result = isinstance(pid, str) and pid.startswith("AI-")
            if is_ai_result:
                # Only the host may submit AI results
                if addr != room.get("host_addr"):
                    sendto_json(sock, addr, {"t":"error","msg":"only_host_can_submit_ai_results"}); continue
            else:
                if not pid or pid != room["clients"][addr].get("id"):
                    sendto_json(sock, addr, {"t":"error","msg":"invalid_player_id"}); continue
            try:
                finish_time = float(msg.get("time", 0.0))
            except Exception:
                sendto_json(sock, addr, {"t":"error","msg":"invalid_finish_time"}); continue
            if finish_time < 0.0:
                sendto_json(sock, addr, {"t":"error","msg":"invalid_finish_time"}); continue

            # For AI results, use the name/car_type from the AI state if available;
            # fall back to host's client info.
            if is_ai_result:
                ai_state = room.get("states", {}).get(pid, {})
                result_name = ai_state.get("name", pid)
                result_car_type = ai_state.get("car_type", "ae86")
            else:
                result_name = room["clients"][addr].get("name", pid)
                result_car_type = room["clients"][addr].get("car_type", "ae86")

            room.setdefault("results", {})[pid] = {
                "time": round(finish_time, 4),
                "name": result_name,
                "car_type": result_car_type,
            }
            # include optional best lap if provided by client
            try:
                best = msg.get("best_lap")
                if best is not None:
                    bval = float(best)
                    if bval >= 0.0:
                        room["results"][pid]["best_lap"] = round(bval, 4)
            except Exception:
                pass
            room["dirty"] = True

        else:
            sendto_json(sock, addr, {"t":"error","msg":"unknown_type"})

def main():
    loop()

if __name__ == "__main__":
    main()
