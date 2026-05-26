import sys, os, importlib.util
# load trainer module
runner_path = os.path.dirname(os.path.dirname(__file__))
mod_path = os.path.join(runner_path, 'tools', 'nn_trainer.py')
spec = importlib.util.spec_from_file_location('nn_trainer_module', mod_path)
trainer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trainer)
# import app and Car
sys.path.insert(0, os.path.join(runner_path, 'src'))
import drift.app as app
from drift.core.car import Car
# load poly
poly, meta = trainer._load_path_polyline(2)
# create car at checkpoint 2 location
px, py = 2135, 1995
c = Car(px, py, 'T_test', is_ai=True)
c.angle = 0.0
c.vx = c.vy = 0.0
inp = app._compute_nn_input_for_car(trainer, poly, c)
print('car._nn_nearest_hint =', getattr(c, '_nn_nearest_hint', None))
# also print nearest using that hint
cx, cy, seg, t, d2 = trainer._nearest_on_polyline(px, py, poly, hint_seg=getattr(c, '_nn_nearest_hint', 0))
print('nearest after compute', cx, cy, 'seg', seg, 'd2', d2)
