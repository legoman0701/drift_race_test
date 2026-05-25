import socket, json, math, time
from collections import deque
from typing import Dict, Any

import drift.config.const as const

_SQRT2 = math.sqrt(2)  # must match car.py isometric compensation
_SNAP_DIST_SQ = 400.0 ** 2  # teleport if error > 400 px (e.g. respawn)
_CORRECTION_RATE = 8.0       # position error blended at this rate (units/s fraction)
_MAX_AGE = 0.5               # clamp packet age to 500 ms (guards against clock skew)

# ── Self-ping / packet-loss state (one set per client) ──────────────────
_PING_ALPHA = 0.15           # EWMA smoothing for ping
_PL_WINDOW = 5.0             # sliding window (seconds) for PL%
_send_seq: int = 0           # monotonic sequence number attached to every sent packet
_last_send_time: float = 0.0 # time.time() when we last sent a state packet
_ping_ewma: float | None = None
_pl_last_sq: int | None = None
_pl_events: deque = deque()  # (time, expected, received) tuples


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


def handle_network_messages(sock, remotes: Dict[str, Any], dt: float, my_id: str, is_host: bool, room_code: str | None = None, my_car=None):
    result = {
        "error": None,
        "start_mode": None,
        "start_track": None,
        "host_name": None,
        "host_id": None,
        "race_results": None,
        "stop_race": False,
    }
    players = {}
    now = time.time()
    for msg in recv_jsons(sock):
        msg_code = msg.get("code")
        t = msg.get("t")
        if room_code and isinstance(msg_code, str) and msg_code.upper() != str(room_code).upper():
            continue

        if t == "pong":
            # Relay echoes our ping packet — measure RTT
            ts_sent = msg.get("ts")
            if ts_sent is not None:
                _update_own_ping((now - float(ts_sent)) * 1000.0, my_car)
            continue
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
            choice = msg.get("choice")
            if isinstance(choice, int) and 0 <= choice < len(const.MODES_CHOICES[const.MODE_INDEX]):
                result["start_choice"] = choice
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
                    # Own echo → measure ping (RTT/2) and PL from sq gaps
                    if _last_send_time > 0.0:
                        _update_own_ping((now - _last_send_time) * 1000.0, my_car)
                    _update_own_pl(d, now, my_car)
                    continue
                if is_host and isinstance(pid, str) and pid.startswith("AI-"):
                    continue
                tx, ty, ta = float(d["x"]), float(d["y"]), float(d["a"])
                tvx, tvy = float(d.get("vx", 0.0)), float(d.get("vy", 0.0))
                thg = d.get("has_grip", [1.0, 1.0, 1.0, 1.0])
                name = d.get("name", f"Player{pid}")
                car_type = d.get("car_type", const.CAR_ID)
                raw_palette = d.get("palette")
                palette = tuple(tuple(c) for c in raw_palette) if raw_palette and len(raw_palette) == 3 else None

                # Pre-advance position by ts age
                ts = d.get("ts")
                age = min(_MAX_AGE, max(0.0, now - float(ts))) if ts is not None else 0.0
                tx += tvx * age
                ty += tvy * age * _SQRT2

                # Read the remote player's self-reported ping & PL
                remote_ping = float(d["ps"]) if d.get("ps") is not None else None
                remote_pl = float(d["pl"]) if d.get("pl") is not None else None

                if pid not in remotes:
                    remotes[pid] = {
                        "x": tx, "y": ty, "a": ta,
                        "vx": tvx, "vy": tvy,
                        "name": name, "has_grip": thg,
                        "car_type": car_type, "palette": palette,
                        "ping": remote_ping,
                        "pl": remote_pl,
                    }
                else:
                    cur = remotes[pid]
                    if remote_ping is not None:
                        cur["ping"] = remote_ping
                    if remote_pl is not None:
                        cur["pl"] = remote_pl
                    ex, ey = tx - cur["x"], ty - cur["y"]
                    if ex * ex + ey * ey > _SNAP_DIST_SQ:
                        cur["x"], cur["y"] = tx, ty
                    else:
                        cur["x"] += ex * min(1.0, dt * _CORRECTION_RATE)
                        cur["y"] += ey * min(1.0, dt * _CORRECTION_RATE)
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
        elif t == "stop_race":
            result["stop_race"] = True
        elif t == "error":
            error_msg = msg.get("msg", "error")
            if error_msg == "unknown_type": # avoid fallback offline
                print("WARNING: Server sent 'unknown_type'. Is the relay.py updated?")
                continue 
            result["error"] = error_msg
            return result
    return result


# ── Ping & PL helpers ───────────────────────────────────────────────────

def send_stop_race(sock, code: str, my_id: str):
    # print("hi from send_stop_race located in communication.py")
    try:
        sock.send(json.dumps({
            "t": "stop_race", 
            "code": code,
            "id": my_id
        }).encode("utf-8"))
        return True
    except Exception:
        # print("Failed from send_stop_race located in communication.py")
        return False

def _update_own_ping(rtt_ms: float, my_car):
    """Update own ping (RTT/2) using EWMA. Stores result on my_car.ping_ms."""
    global _ping_ewma
    if not (0.0 < rtt_ms < 2000.0):
        return
    if _ping_ewma is None:
        _ping_ewma = rtt_ms / 2.0
    else:
        _ping_ewma += _PING_ALPHA * (rtt_ms / 2.0 - _ping_ewma)
    if my_car is not None:
        my_car.ping_ms = _ping_ewma

def _update_own_pl(d: dict, now: float, my_car):
    """Update own packet-loss % from echoed sq gaps + spike detection.
    Stores result on my_car.pl_pct."""
    global _pl_last_sq
    echo_sq = int(d["sq"]) if d.get("sq") is not None else None
    # Only record a new event when sq actually advances (skip duplicate relay echoes)
    if echo_sq is not None and echo_sq != _pl_last_sq:
        if _pl_last_sq is not None:
            gap = max(1, echo_sq - _pl_last_sq)
            _pl_events.append((now, gap, 1))
        else:
            _pl_events.append((now, 1, 1))
        _pl_last_sq = echo_sq
        # Spike detection: if ping_ewma exists and current RTT is >1.5× the smoothed RTT
        if _ping_ewma is not None and _last_send_time > 0.0:
            rtt_ms = (now - _last_send_time) * 1000.0
            if rtt_ms > _ping_ewma * 2 * 1.5:
                _pl_events.append((now, 2, 1))
    # Trim outside window
    while _pl_events and now - _pl_events[0][0] > _PL_WINDOW:
        _pl_events.popleft()
    # Compute PL%
    if _pl_events and my_car is not None:
        total_exp = sum(e[1] for e in _pl_events)
        total_recv = sum(e[2] for e in _pl_events)
        my_car.pl_pct = max(0.0, 100.0 * (1.0 - total_recv / total_exp)) if total_exp > 0 else 0.0

def send_network_state(sock, code: str, my_id: str, my_car, palette=None):
    global _last_send_time, _send_seq
    _last_send_time = time.time()
    _send_seq += 1
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
        "car_type": getattr(my_car, "car_type", const.CAR_ID),
        "ts": round(time.time(), 4),
        "ps": round(my_car.ping_ms, 1) if my_car.ping_ms is not None else None,
        "pl": round(my_car.pl_pct, 1) if my_car.pl_pct is not None else None,
        "sq": _send_seq,
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
            "car_type": getattr(ai, "car_type", const.CAR_ID),
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
        sock.send(json.dumps({"t": "ping", "code": code, "ts": round(time.time(), 4)}).encode("utf-8"))
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
