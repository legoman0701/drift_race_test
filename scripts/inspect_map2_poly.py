import sys, os, importlib.util
runner_path = os.path.dirname(os.path.dirname(__file__))
mod_path = os.path.join(runner_path, 'tools', 'nn_trainer.py')
spec = importlib.util.spec_from_file_location('nn_trainer_module', mod_path)
t = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t)
poly, meta = t._load_path_polyline(2)
print('polylen', len(poly))
px, py = 2135, 1995
cx, cy, seg, tv, d2 = t._nearest_on_polyline(px, py, poly)
print('nearest', cx, cy, 'seg', seg, 't', tv, 'd2', d2)
print('seg point', poly[seg])
print('next point', poly[(seg+1)%len(poly)])
for i in range(seg-5, seg+6):
    p = poly[i%len(poly)]
    print(i%len(poly), p)
