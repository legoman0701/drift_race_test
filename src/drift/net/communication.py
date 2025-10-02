import socket, json, math
from typing import Dict, Any

import drift.config.const as const


def recv_jsons(sock: socket.socket):
    msgs = []
    while True:
        try:
            data = sock.recv(8192)
            if not data:
                break
            try:
                msgs.append(json.loads(data.decode("utf-8")))
            except Exception:
                pass
        except BlockingIOError:
            break
        except Exception:
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
    players = {}
    for msg in recv_jsons(sock):
        t = msg.get("t")
        if t == "join_ok":
            pass
        elif t == "world":
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
                tx, ty, ta, tdr = float(d["x"]), float(d["y"]), float(d["a"]), float(d["drift_ratio"])
                name = d.get("name", f"Player{pid}")
                if pid not in remotes:
                    remotes[pid] = {"x": tx, "y": ty, "a": ta, "name": name, "drift_ratio": tdr}
                else:
                    cur = remotes[pid]
                    cur["x"] += (tx - cur["x"]) * alpha_pos
                    cur["y"] += (ty - cur["y"]) * alpha_pos
                    cur["drift_ratio"] += (tdr - cur["drift_ratio"]) * alpha_pos
                    da = ((ta - cur["a"] + math.pi) % (2 * math.pi)) - math.pi
                    cur["a"] = (cur["a"] + da * alpha_angle) % (2 * math.pi)
                    cur["name"] = name
            for pid in list(remotes.keys()):
                if pid not in players:
                    remotes.pop(pid, None)
        elif t == "error":
            return msg.get("msg", "error")
    return None


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
        "drift_ratio": round(my_car.drift_ratio, 2),
        "name": my_car.name,
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
            "drift_ratio": round(ai.drift_ratio, 2),
            "name": ai.name,
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
