#!/usr/bin/env python3
"""
NN Tester

Loads a saved network produced by `tools/nn_trainer.py` and runs evaluation
episodes in the headless `TrainingEnv`. Prints per-episode and aggregate
metrics.
"""
import sys
import os
import time
import pickle
import importlib.util
import pygame


# Make project importable when running from tools/
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
os.chdir(_ROOT)


def _load_trainer_module():
    path = os.path.join(os.path.dirname(__file__), "nn_trainer.py")
    spec = importlib.util.spec_from_file_location("nn_trainer_module", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_network_from_pickle(path, trainer_mod):
    with open(path, "rb") as f:
        d = pickle.load(f)
    arch = d.get("arch") or d.get("architecture") or {}
    in_s = arch.get("in") or arch.get("input_size") or trainer_mod.INPUT_SIZE
    hid = arch.get("hidden") or arch.get("hidden_sizes") or list(trainer_mod.HIDDEN_SIZES)
    out_s = arch.get("out") or arch.get("output_size") or trainer_mod.OUTPUT_SIZE
    net = trainer_mod.NeuralNetwork(in_s, list(hid), out_s)
    net.set_weights(d["weights"])
    return net


def evaluate(net, trainer_mod, map_num=None, episodes=5):
    if map_num is None:
        map_num = trainer_mod.const.MAP_NUM

    polyline, meta = trainer_mod._load_path_polyline(map_num)
    env = trainer_mod.TrainingEnv(polyline, meta, num_cars=1)
    # Rendering setup (reuse trainer visuals)
    map_w = int(meta.get("width", 2944))
    map_h = int(meta.get("height", 2496))
    scale = 0.4
    win_w, win_h = int(map_w * scale), int(map_h * scale)
    screen = None
    debug_win = None
    debug_surf = None
    try:
        pygame.init()
        screen = pygame.display.set_mode((win_w, win_h))
        pygame.display.set_caption("NN Tester - Evaluation")
        from pygame._sdl2.video import Window as SDLWindow
        debug_win = SDLWindow("Physics Debug", size=(trainer_mod.DEBUG_WIN_SIZE, trainer_mod.DEBUG_WIN_SIZE))
        debug_surf = pygame.Surface((trainer_mod.DEBUG_WIN_SIZE, trainer_mod.DEBUG_WIN_SIZE))
    except Exception:
        # If rendering can't be initialized, continue headless
        screen = None
        debug_win = None
        debug_surf = None
    results = []
    for ep in range(episodes):
        obs = env.reset(keep_car_type=True)
        total_reward = 0.0
        steps = 0
        start = time.time()
        clock = pygame.time.Clock()
        left_edge, right_edge = trainer_mod._build_edge_segments(polyline, half_width=70)
        edge_segs = trainer_mod._segments_from_polyline(left_edge) + trainer_mod._segments_from_polyline(right_edge)
        while True:
            action = net.forward(obs[0])
            actions = [action]
            obs, rewards, done = env.step(actions)
            total_reward += float(rewards[0])
            steps += 1
            # Render every other step (like trainer)
            if screen is not None and steps % 2 == 0:
                for ev in pygame.event.get():
                    if ev.type == pygame.QUIT:
                        done = True
                    elif ev.type == pygame.WINDOWCLOSE:
                        ew = getattr(ev, "window", None)
                        ew_id = ew.id if ew is not None and hasattr(ew, "id") else 0
                        if debug_win is not None and ew_id == debug_win.id:
                            # hide debug window if user closes it
                            debug_win.hide()
                        else:
                            done = True

                screen.fill((25, 30, 35))
                trainer_mod.draw_track_outline(screen, left_edge, right_edge, scale)
                trainer_mod.draw_poly_checkpoints(screen, env.polyline, env.poly_checkpoint_segments, scale)
                # draw the single car
                trainer_mod.draw_cars_simple(screen, env.cars, env.car_alive, scale)

                # draw raycasts for car 0 if alive
                if env.car_alive[0]:
                    c = env.cars[0]
                    for ra in env.ray_angles_rad:
                        hx, hy, rd, hit = trainer_mod.raycast_grid(env.edge_grid, c.x, c.y, c.angle + ra, trainer_mod.MAX_RAY_DIST)
                        color = (0, 200, 0) if hit else (80, 80, 80)
                        pygame.draw.line(screen, color, (int(c.x * scale), int(c.y * scale)), (int(hx * scale), int(hy * scale)), 1)
                        if hit:
                            pygame.draw.circle(screen, (0, 255, 0), (int(hx * scale), int(hy * scale)), 2)

                # HUD
                font = pygame.font.Font(None, 22)
                hud_lines = [f"Episode {ep+1}/{episodes}  Step {env.step_count}", f"Reward {total_reward:.1f}"]
                for i, txt in enumerate(hud_lines):
                    surf = font.render(txt, True, (220, 220, 220))
                    screen.blit(surf, (8, 6 + i * 20))

                pygame.display.flip()

                # debug window
                if debug_win is not None:
                    if env.car_alive[0]:
                        bc = env.cars[0]
                        seg_h = env.car_prev_seg[0]
                        trainer_mod.draw_debug_view(debug_surf, bc, env.edge_segments, env.ray_angles_rad, env.edge_grid, polyline, seg_h, left_edge, right_edge, checkpoint_segments=env.poly_checkpoint_segments, next_checkpoint_idx=env.car_next_checkpoint[0], checkpoint_hits=env.car_checkpoint_hits[0], checkpoint_flash=env.car_checkpoint_flash[0], last_checkpoint_gain=env.car_last_checkpoint_gain[0])
                    else:
                        debug_surf.fill((20, 22, 28))
                        msg = pygame.font.Font(None, 18)
                        ts = msg.render("No alive car", True, (120, 120, 120))
                        debug_surf.blit(ts, (trainer_mod.DEBUG_WIN_SIZE // 2 - ts.get_width() // 2, trainer_mod.DEBUG_WIN_SIZE // 2))
                    debug_win.get_surface().blit(debug_surf, (0, 0))
                    debug_win.flip()

                clock.tick(60)
            if done:
                break
        elapsed = time.time() - start
        cp_hits = env.car_checkpoint_hits[0] if env.car_checkpoint_hits else 0
        results.append({"reward": total_reward, "steps": steps, "time": elapsed, "checkpoints": cp_hits})
        print(f"Episode {ep+1}/{episodes}: reward={total_reward:.1f} steps={steps} checkpoints={cp_hits} time={elapsed:.2f}s")

    avg = sum(r["reward"] for r in results) / len(results)
    avg_steps = sum(r["steps"] for r in results) / len(results)
    avg_cp = sum(r["checkpoints"] for r in results) / len(results)
    print(f"Average reward {avg:.1f}  avg_steps {avg_steps:.1f}  avg_checkpoints {avg_cp:.2f}")
    return results


def main():
    # Hardcoded configuration (no CLI args)
    MODEL_PATH = os.path.join("ai_models", "best_network.pkl")
    EPISODES = 5
    MAP_NUM = 1

    trainer_mod = _load_trainer_module()

    if not os.path.exists(MODEL_PATH):
        print(f"Model not found: {MODEL_PATH}")
        return

    print(f"Loading model: {MODEL_PATH}")
    net = _load_network_from_pickle(MODEL_PATH, trainer_mod)
    print("Starting evaluation...")
    evaluate(net, trainer_mod, map_num=MAP_NUM, episodes=EPISODES)


if __name__ == "__main__":
    main()
