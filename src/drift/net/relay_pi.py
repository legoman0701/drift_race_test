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
        "host_name": room.get("host_name", ""),
        "host_id": room.get("host_id", ""),
        "race_started": bool(room.get("race_started", False)),
        "mode": room.get("mode", "mode1"),
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
                    # if the timed out client was host, purge AI states
                    if caddr == room.get("host_addr") or pid == room.get("host_id"):
                        for sid in list(room["states"].keys()):
                            if isinstance(sid, str) and sid.startswith("AI-"):
                                room["states"].pop(sid, None)
                        assign_random_host(room)
                    room["dirty"] = True
            # remove room if empty
            if not room["clients"]:
                rooms.pop(code, None)

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
            room = {"clients": {}, "states": {}, "host_addr": addr, "host_id": pid, "host_name": name, "mode": mode, "track": track, "race_started": False, "last_broadcast": 0.0, "dirty": True}
            rooms[code] = room
            room["clients"][addr] = {"id": pid, "name": name, "car_type": car_type, "last": now}
            room["states"].setdefault(pid, {"x": 500, "y": 350, "a": 0.0, "vx": 0.0, "vy": 0.0, "name": name, "has_grip": [1.0, 1.0, 1.0, 1.0], "car_type": car_type})
            room["dirty"] = True
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
            room["clients"][addr] = {"id": pid, "name": name, "last": now, "car_type": car_type}
            room["states"].setdefault(pid, {"x": 500, "y": 350, "a": 0.0, "vx": 0.0, "vy": 0.0, "name": name, "has_grip": [1.0, 1.0, 1.0, 1.0], "car_type": car_type})
            room["dirty"] = True
            # Send host_name and track from room data
            host_name = room.get("host_name", "no_host")
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
            }
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
            if pid: room["states"].pop(pid, None) # remove player
            # If the host leaves, purge AI states and clear host markers
            if addr == room.get("host_addr") or pid == room.get("host_id"):
                for sid in list(room["states"].keys()):
                    if isinstance(sid, str) and sid.startswith("AI-"):
                        room["states"].pop(sid, None)
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
            room["race_started"] = True
            room["dirty"] = True
            start_msg = {"t": "start_race", "code": code, "mode": room.get("mode", "mode1"), "track": room.get("track", "track1")}
            for caddr in list(room["clients"].keys()):
                sendto_json(sock, caddr, start_msg)

        else:
            sendto_json(sock, addr, {"t":"error","msg":"unknown_type"})

def main():
    loop()

if __name__ == "__main__":
    main()
