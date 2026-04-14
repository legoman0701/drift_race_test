import socket, json, math, time
from collections import deque
from typing import Dict, Any

import drift.config.const as const

_SQRT2 = math.sqrt(2)  # must match car.py isometric compensation
_SNAP_DIST_SQ = 400.0 ** 2  # teleport if error > 400 px (e.g. respawn)
_CORRECTION_RATE = 8.0       # position error blended at this rate (units/s fraction)
_PING_EWMA_ALPHA = 0.15      # smoothing factor for ping estimate
_MAX_AGE = 0.5               # clamp packet age to 500 ms (guards against clock skew)
_PL_WINDOW = 5.0             # seconds over which packet-loss % is computed

# Module-level per-player recv stats (cleared on disconnect)
_recv_stats: Dict[str, Dict] = {}
# Track when we last sent a state packet so we can compute RTT from world echo
_last_send_time: float = 0.0
_my_ping_ewma: float | None = None
# Monotonically-incrementing send sequence number for packet-loss detection
_send_seq: int = 0


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
        "my_ping": None,   # RTT/2 in ms measured via world echo of own state
    }
    players = {}
    now = time.time()
    for msg in recv_jsons(sock):
        msg_code = msg.get("code")
        t = msg.get("t")
        if t not in ("world",):  # skip spammy world packets in debug log
            print(f"[net] recv t={t!r} code={msg_code!r}")
        if room_code and isinstance(msg_code, str) and msg_code.upper() != str(room_code).upper():
            # Ignore stale/wrong-room packets so stage transitions stay session-scoped.
            continue

        if t == "pong":
            ts_sent = msg.get("ts")
            print(f"[net] pong received, ts={ts_sent}, rtt={(time.time()-float(ts_sent))*1000:.1f}ms" if ts_sent else "[net] pong received but no ts")
            if ts_sent is not None:
                rtt_ms = (now - float(ts_sent)) * 1000.0
                if 0.0 < rtt_ms < 2000.0:
                    prev = result["my_ping"]
                    if prev is None:
                        result["my_ping"] = rtt_ms / 2.0
                    else:
                        result["my_ping"] = prev + _PING_EWMA_ALPHA * (rtt_ms / 2.0 - prev)
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
                    # Own echo in world → measure RTT from local send time
                    global _my_ping_ewma
                    if _last_send_time > 0.0:
                        rtt_ms = (now - _last_send_time) * 1000.0
                        if 0.0 < rtt_ms < 2000.0:
                            if _my_ping_ewma is None:
                                _my_ping_ewma = rtt_ms / 2.0
                            else:
                                _my_ping_ewma = _my_ping_ewma + _PING_EWMA_ALPHA * (rtt_ms / 2.0 - _my_ping_ewma)
                            result["my_ping"] = _my_ping_ewma
                            print(f"[net] RTT={rtt_ms:.1f}ms  ping={_my_ping_ewma:.1f}ms")
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

                # ── Per-player recv stats (ping + packet loss) ──────────────
                if pid not in _recv_stats:
                    _recv_stats[pid] = {"last_recv": now, "ping": 0.0, "last_sq": None, "pl_events": deque()}
                st = _recv_stats[pid]
                interval = now - st["last_recv"]
                st["last_recv"] = now
                # Running EWMA of inter-arrival interval → smoothed one-way delay proxy
                prev_ping = st["ping"]
                raw_interval_ms = interval * 1000.0
                st["ping"] = prev_ping + _PING_EWMA_ALPHA * (raw_interval_ms - prev_ping)
                # Sequence-number based packet loss: count gaps between received sq values
                new_sq = int(d["sq"]) if d.get("sq") is not None else None
                if new_sq is not None:
                    if st["last_sq"] is not None:
                        gap = max(1, new_sq - st["last_sq"])
                        st["pl_events"].append((now, gap, 1))  # (time, expected, received)
                    else:
                        st["pl_events"].append((now, 1, 1))  # first packet, no gap yet
                    st["last_sq"] = new_sq
                # Large ping spike → treat as implicit packet loss even without sq gap
                # A sudden ×1.5 jump in interval suggests a dropped packet caused queuing
                if prev_ping > 0.0 and raw_interval_ms > prev_ping * 1.5:
                    st["pl_events"].append((now, 2, 1))  # 2 expected, 1 received (1 implied drop)
                # Trim events outside the window
                while st["pl_events"] and now - st["pl_events"][0][0] > _PL_WINDOW:
                    st["pl_events"].popleft()
                # PL%: (expected - received) / expected
                # Shows None only if sq never seen AND no spike events yet
                if st["pl_events"]:
                    total_exp = sum(e[1] for e in st["pl_events"])
                    total_recv = sum(e[2] for e in st["pl_events"])
                    pl_pct = max(0.0, 100.0 * (1.0 - total_recv / total_exp)) if total_exp > 0 else 0.0
                else:
                    pl_pct = None
                # ────────────────────────────────────────────────────────────

                # Pre-advance position by ts age (same-clock only, i.e. same host)
                ts = d.get("ts")
                age = min(_MAX_AGE, max(0.0, now - float(ts))) if ts is not None else 0.0
                tx += tvx * age
                ty += tvy * age * _SQRT2

                ping_to_server = float(d["ps"]) if d.get("ps") is not None else None

                if pid not in remotes:
                    # First sighting: place exactly at received position
                    remotes[pid] = {
                        "x": tx, "y": ty, "a": ta,
                        "vx": tvx, "vy": tvy,
                        "name": name, "has_grip": thg,
                        "car_type": car_type, "palette": palette,
                        "ping": ping_to_server,
                        "pl": pl_pct,
                    }
                else:
                    cur = remotes[pid]
                    if ping_to_server is not None:
                        cur["ping"] = ping_to_server
                    cur["pl"] = pl_pct
                    # Teleport on large errors (respawn, new race start, etc.)
                    ex, ey = tx - cur["x"], ty - cur["y"]
                    if ex * ex + ey * ey > _SNAP_DIST_SQ:
                        cur["x"], cur["y"] = tx, ty
                    else:
                        # Soft correction toward received truth
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
            # Clean up disconnected players from recv stats
            for pid in list(_recv_stats.keys()):
                if pid not in players:
                    _recv_stats.pop(pid, None)
            for pid in list(remotes.keys()):
                if pid not in players:
                    remotes.pop(pid, None)
        elif t == "error":
            result["error"] = msg.get("msg", "error")
            return result
    return result


def send_network_state(sock, code: str, my_id: str, my_car, palette=None, my_ping=None):
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
        "car_type": getattr(my_car, "car_type", "ae86"),
        "ts": round(time.time(), 4),
        "ps": round(my_ping, 1) if my_ping is not None else None,
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
