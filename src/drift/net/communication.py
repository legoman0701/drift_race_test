import socket, json, math
from typing import Dict, Any

import drift.config.const as const


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


def handle_network_messages(sock, remotes: Dict[str, Any], dt: float, my_id: str, is_host: bool):
    result = {"error": None, "start_mode": None, "start_track": None, "host_name": None, "host_id": None}
    players = {}
    for msg in recv_jsons(sock):
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
        elif t == "world": # Placeholder for receiving authoritative world state from server
            host_name = msg.get("host_name")
            if isinstance(host_name, str):
                result["host_name"] = host_name
            host_id = msg.get("host_id")
            if isinstance(host_id, str):
                result["host_id"] = host_id
            if msg.get("race_started"):
                mode = msg.get("mode")
                if isinstance(mode, str) and mode:
                    result["start_mode"] = mode
            players = msg.get("players", {}) or {}
            POS_SMOOTHING_MULTIPLIER = 300.0
            ANGLE_SMOOTHING_MULTIPLIER = 300.0
            alpha_pos = min(1.0, dt * POS_SMOOTHING_MULTIPLIER)
            alpha_angle = min(1.0, dt * ANGLE_SMOOTHING_MULTIPLIER)
            for pid, d in players.items():
                if pid == my_id:
                    continue
                if is_host and isinstance(pid, str) and pid.startswith("AI-"):
                    # host owns AI locally; skip echoed server AI
                    continue
                tx, ty, ta = float(d["x"]), float(d["y"]), float(d["a"])
                thg = d.get("has_grip", [1.0, 1.0, 1.0, 1.0])
                name = d.get("name", f"Player{pid}")
                car_type = d.get("car_type", "ae86")
                if pid not in remotes:
                    remotes[pid] = {"x": tx, "y": ty, "a": ta, "name": name, "has_grip": thg, "car_type": car_type}
                else:
                    cur = remotes[pid]
                    cur["x"] += (tx - cur["x"]) * alpha_pos
                    cur["y"] += (ty - cur["y"]) * alpha_pos
                    cur["has_grip"] = thg
                    da = ((ta - cur["a"] + math.pi) % (2 * math.pi)) - math.pi
                    cur["a"] = (cur["a"] + da * alpha_angle) % (2 * math.pi)
                    cur["name"] = name
                    cur["car_type"] = car_type
            for pid in list(remotes.keys()):
                if pid not in players:
                    remotes.pop(pid, None)
        elif t == "error":
            result["error"] = msg.get("msg", "error")
            return result
    return result


def send_network_state(sock, code: str, my_id: str, my_car):
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
    }
    try:
        sock.send(json.dumps(pkt).encode("utf-8"))
    except Exception:
        pass


def send_ai_states(sock, code: str, ai_cars):
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
        }
        try:
            sock.send(json.dumps(pkt).encode("utf-8"))
        except Exception:
            pass


def send_ping(sock, code: str):
    try:
        sock.send(json.dumps({"t": "ping", "code": code}).encode("utf-8"))
    except Exception:
        pass
