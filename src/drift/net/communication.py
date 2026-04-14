import socket, json, math, time
from typing import Dict, Any

import drift.config.const as const

_SQRT2 = math.sqrt(2)  # must match car.py isometric compensation
_SNAP_DIST_SQ = 400.0 ** 2  # teleport if error > 400 px (e.g. respawn)
_CORRECTION_RATE = 8.0       # position error blended at this rate (units/s fraction)
_PING_EWMA_ALPHA = 0.2       # smoothing factor for per-player ping estimate
_MAX_AGE = 0.5               # clamp packet age to 500 ms (guards against clock skew)


def recv_jsons(sock: socket.socket):
    msgs = []
    while True:
        try:
            data = sock.recv(8192)
            if not data: break
            try:
                # Decode and parse the JSON from this datagram
                msgs.append(json.loads(data.decode("utf-8")))
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}, data: {data[:200]}")  # Debug: show what failed to parse
            except UnicodeDecodeError as e:
                print(f"Unicode decode error: {e}, raw data: {data[:200]}")  # Debug: show encoding issue
            except Exception as e:
                print(f"Unexpected error parsing message: {e}")  # Debug: catch other issues
        except BlockingIOError as e:
            # print(f"blocking io error: {e}")  # Debug: socket-level error
            break
        except Exception as e:
            print(f"Socket recv error: {e}")  # Debug: socket-level error
            break
    return msgs


def connect_to_relay() -> socket.socket:
    host, port_str = const.RELAY_PUBLIC_ENDPOINT.rsplit(":", 1)
    port = int(port_str)
    addr_info = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_DGRAM)[0]
    s = socket.socket(*addr_info[:3])
    s.setblocking(False)
    s.connect(addr_info[4])
    return s


def handle_network_messages(sock, remotes: Dict[str, Any], dt: float, my_id: str, is_host: bool, room_code: str | None = None):
    result = {
        "error": None,
        "start_mode": None,
        "start_track": None,
        "host_name": None,
        "host_id": None,
        "race_results": None,
    }
    players = {}
    now = time.time()
    for msg in recv_jsons(sock):
        msg_code = msg.get("code")
        if room_code and isinstance(msg_code, str) and msg_code.upper() != str(room_code).upper():
            # Ignore stale/wrong-room packets so stage transitions stay session-scoped.
            continue

        t = msg.get("t")
        if t == "join_ok":
            host_name = msg.get("host_name")
            if isinstance(host_name, str):
                result["host_name"] = host_name
            host_id = msg.get("host_id")
            if isinstance(host_id, str):
                result["host_id"] = host_id
        elif t == "start_race":
            mode = msg.get("mode")
            if isinstance(mode, str) and mode:
                result["start_mode"] = mode
            track = msg.get("track")
            if isinstance(track, str) and track:
                result["start_track"] = track
            laps = msg.get("laps")
            if isinstance(laps, int) and 1 <= laps <= 10:
                result["start_laps"] = laps
            # Roster: authoritative list of all player/AI IDs from the relay,
            # used to compute deterministic spawn positions on every client.
            roster = msg.get("roster")
            if isinstance(roster, list):
                result["start_roster"] = roster
        elif t == "world": # Placeholder for receiving authoritative world state from server
            host_name = msg.get("host_name")
            if isinstance(host_name, str):
                result["host_name"] = host_name
            host_id = msg.get("host_id")
            if isinstance(host_id, str):
                result["host_id"] = host_id
            world_results = msg.get("results")
            if isinstance(world_results, dict):
                result["race_results"] = world_results
            mode = msg.get("mode")
            track = msg.get("track")
            if msg.get("race_started"):
                if isinstance(mode, str) and mode:
                    result["start_mode"] = mode
                if isinstance(track, str) and track:
                    result["start_track"] = track
            elif isinstance(mode, str) and mode == "lobby":
                # Use world snapshots as a reliable fallback for menu return.
                result["start_mode"] = "lobby"
                if isinstance(track, str) and track:
                    result["start_track"] = track
            players = msg.get("players", {}) or {}
            for pid, d in players.items():
                if pid == my_id:
                    continue
                if is_host and isinstance(pid, str) and pid.startswith("AI-"):
                    # host owns AI locally; skip echoed server AI
                    continue
                tx, ty, ta = float(d["x"]), float(d["y"]), float(d["a"])
                tvx, tvy = float(d.get("vx", 0.0)), float(d.get("vy", 0.0))
                thg = d.get("has_grip", [1.0, 1.0, 1.0, 1.0])
                name = d.get("name", f"Player{pid}")
                car_type = d.get("car_type", "ae86")
                raw_palette = d.get("palette")
                palette = tuple(tuple(c) for c in raw_palette) if raw_palette and len(raw_palette) == 3 else None

                # Estimate one-way transit time from sender's timestamp.
                # Pre-advance the received position so we place the car where it
                # likely is *now*, not where it was when the packet was sent.
                ts = d.get("ts")
                age = min(_MAX_AGE, max(0.0, now - float(ts))) if ts is not None else 0.0
                tx += tvx * age
                ty += tvy * age * _SQRT2

                if pid not in remotes:
                    # First sighting: place exactly at received position
                    remotes[pid] = {
                        "x": tx, "y": ty, "a": ta,
                        "vx": tvx, "vy": tvy,
                        "name": name, "has_grip": thg,
                        "car_type": car_type, "palette": palette,
                        "ping": age * 1000.0,
                    }
                else:
                    cur = remotes[pid]
                    # Update ping EWMA (milliseconds)
                    old_ping = cur.get("ping", age * 1000.0)
                    cur["ping"] = old_ping + _PING_EWMA_ALPHA * (age * 1000.0 - old_ping)
                    # Teleport on large errors (respawn, new race start, etc.)
                    ex, ey = tx - cur["x"], ty - cur["y"]
                    if ex * ex + ey * ey > _SNAP_DIST_SQ:
                        cur["x"], cur["y"] = tx, ty
                    else:
                        # Soft correction: blend predicted position toward received truth.
                        # The advance_remotes() call each frame keeps the car moving;
                        # this nudge corrects accumulated drift without visible snapping.
                        cur["x"] += ex * min(1.0, dt * _CORRECTION_RATE)
                        cur["y"] += ey * min(1.0, dt * _CORRECTION_RATE)
                    # Always update velocity so dead reckoning uses fresh data
                    cur["vx"] = tvx
                    cur["vy"] = tvy
                    cur["has_grip"] = thg
                    da = ((ta - cur["a"] + math.pi) % (2 * math.pi)) - math.pi
                    cur["a"] = (cur["a"] + da * min(1.0, dt * _CORRECTION_RATE)) % (2 * math.pi)
                    cur["name"] = name
                    cur["car_type"] = car_type
                    cur["palette"] = palette
            for pid in list(remotes.keys()):
                if pid not in players:
                    remotes.pop(pid, None)
        elif t == "error":
            result["error"] = msg.get("msg", "error")
            return result
    return result


def send_network_state(sock, code: str, my_id: str, my_car, palette=None):
    pkt = {
        "t": "state",
        "code": code,
        "id": my_id,
        "x": round(my_car.x, 2),
        "y": round(my_car.y, 2),
        "a": round(my_car.angle, 4),
        "vx": round(my_car.vx, 2),
        "vy": round(my_car.vy, 2),
        "has_grip": [round(v, 3) for v in my_car.has_grip],
        "name": my_car.name,
        "car_type": getattr(my_car, "car_type", "ae86"),
        "ts": round(time.time(), 4),
    }
    if palette:
        pkt["palette"] = [list(c) for c in palette]
    try:
        sock.send(json.dumps(pkt).encode("utf-8"))
    except Exception:
        pass


def send_ai_states(sock, code: str, ai_cars):
    # Host broadcasts AI car states including palette so non-host
    # clients can render AI cars with the correct colors.
    for i, ai in enumerate(ai_cars, start=1):
        pkt = {
            "t": "state",
            "code": code,
            "id": f"AI-{i}",
            "x": round(ai.x, 2),
            "y": round(ai.y, 2),
            "a": round(ai.angle, 4),
            "vx": round(ai.vx, 2),
            "vy": round(ai.vy, 2),
            "has_grip": [round(v, 3) for v in ai.has_grip],
            "name": ai.name,
            "car_type": getattr(ai, "car_type", "ae86"),
            "ts": round(time.time(), 4),
        }
        palette = getattr(ai, "palette_colors", None)
        if palette:
            pkt["palette"] = [list(c) for c in palette]
        try:
            sock.send(json.dumps(pkt).encode("utf-8"))
        except Exception:
            pass


def send_ping(sock, code: str):
    try:
        sock.send(json.dumps({"t": "ping", "code": code}).encode("utf-8"))
    except Exception:
        pass


def advance_remotes(remotes: Dict[str, Any], dt: float):
    """Dead-reckoning: advance every remote car's predicted position by its
    last known velocity.  Call this every frame *before* physics/rendering so
    remotes appear to move smoothly between network packets."""
    for cur in remotes.values():
        vx = cur.get("vx", 0.0)
        vy = cur.get("vy", 0.0)
        if vx or vy:
            cur["x"] += vx * dt
            cur["y"] += vy * dt * _SQRT2  # isometric compensation matches car.py
