"""Run with python -m unittest -v test_python.py; no display required."""
import gzip
import json
import math
import os
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from bot import BasicBot
from game import arguments, manual_action, run
from recorder import DrivingRecorder
from scene_labels import label_scene
from simulation import Action, DT, World


class SimulationTests(unittest.TestCase):
    def test_relative_positions_follow_car_translation_and_rotation(self):
        world = World(traffic=False)
        for heading in (0, math.pi/2, math.pi, -math.pi/2, .73):
            world.car.update(x=120, y=-45, a=heading)
            observation = world.observe()
            self.assertEqual(observation['car']['relative_position'], dict(x=0, y=0))
            self.assertEqual(observation['car']['relative_heading'], 0)
            c, s = math.cos(heading), math.sin(heading)
            for obj in observation['world']['objects']:
                position = obj['relative_position']
                self.assertAlmostEqual(120+position['x']*c-position['y']*s, obj['x'])
                self.assertAlmostEqual(-45+position['x']*s+position['y']*c, obj['y'])
                self.assertEqual(position['x'], obj['relative_center']['forward'])
                self.assertEqual(position['y'], obj['relative_center']['right'])
        world.car.update(x=0, y=0, a=0)
        before = world.observe()['world']['objects'][0]
        world.car.update(x=25, y=-10)
        after = world.observe()['world']['objects'][0]
        self.assertEqual((before['x'], before['y']), (after['x'], after['y']))
        self.assertAlmostEqual(after['relative_position']['x'], before['relative_position']['x']-25)
        self.assertAlmostEqual(after['relative_position']['y'], before['relative_position']['y']+10)

    def test_deterministic_actions_and_detached_observations(self):
        a, b = World(), World()
        initial = a.observe()
        for i in range(120):
            action = Action(accelerate=True, steering=.3 if i > 60 else 0)
            a.step(action)
            b.step(action)
        self.assertEqual(a.observe(), b.observe())
        self.assertEqual(initial['car']['y'], 30)
        self.assertEqual(initial['frame'], 0)
        self.assertLess(a.car['y'], 0)

    def test_all_objects_and_relative_transform(self):
        w = World(traffic=False)
        w.car.update(x=0, y=0, a=-math.pi/2, vx=0, vy=-10)
        obs = w.observe()
        objects = obs['world']['objects']
        self.assertEqual(len(objects), len(w.buildings)+len(w.trees)+len(w.props)+25+1)
        self.assertEqual(len({o['id'] for o in objects}), len(objects))
        tree = next(o for o in objects if o['type'] == 'tree')
        self.assertAlmostEqual(tree['relative_center']['forward'], -tree['y'])
        self.assertAlmostEqual(tree['relative_center']['right'], tree['x'])
        self.assertAlmostEqual(tree['relative_velocity']['forward'], -10)
        traffic = [o for o in objects if o['type'] == 'traffic']
        self.assertTrue(all(not o['active'] and o['vx'] == o['vy'] == 0 for o in traffic))
        self.assertTrue(any(o['distance'] > 1000 for o in objects))

    def test_footprint_overlap_and_edge_touch(self):
        p = dict(x=0, y=0, a=0, vx=0, vy=0, length=20)
        obj = dict(id='test', type='building', x=30, y=30, a=0,
                   length=10, width=20, height=10, solid=True)
        scene = label_scene(p, [obj], 140)
        self.assertFalse(scene['labels']['obstacle_center'])
        self.assertTrue(scene['labels']['obstacle_right'])
        obj['y'] = 29
        self.assertTrue(label_scene(p, [obj], 140)['labels']['obstacle_center'])

    def test_collision_and_reset(self):
        w = World()
        b = w.buildings[0]
        self.assertTrue(w.collision(b['x']+10, b['y']+10))
        self.assertTrue(w.collision(1700, 0))
        w.step(Action(accelerate=True))
        w.reset()
        self.assertEqual(w.segment, 1)
        self.assertEqual(w.frame, 1)
        self.assertEqual(w.car['vx'], 0)

    def test_manual_aliases_and_validation(self):
        self.assertEqual(manual_action({'w', 'up', 'left', 'right'}), Action(accelerate=True))
        with self.assertRaises(ValueError):
            Action(steering=float('nan'))
        with self.assertRaises(ValueError):
            World().step(Action(), 2)

    def test_bot_drives_a_complete_loop_without_traffic(self):
        for model in range(3):
            with self.subTest(model=model):
                w, bot = World(model=model, traffic=False), BasicBot()
                visited = set()
                distance = peak_speed = 0
                for _ in range(3600):
                    # Exercise the recorder's observation contract for every car.
                    action = bot.act(w.observe())
                    visited.add(bot.target)
                    old_x, old_y = w.car['x'], w.car['y']
                    w.step(action)
                    distance += math.hypot(w.car['x']-old_x, w.car['y']-old_y)
                    peak_speed = max(peak_speed, math.hypot(w.car['vx'], w.car['vy']))
                self.assertEqual(visited, {0, 1, 2, 3})
                self.assertEqual(w.collisions, 0)
                self.assertGreater(peak_speed, 100)
                self.assertGreater(distance, 4500)
                self.assertLess(abs(w.car['x']), 350)
                self.assertLess(abs(w.car['y']), 350)


class CityGenerationTests(unittest.TestCase):
    def test_seed_reproduction_and_detached_layout(self):
        world = World(1234)
        self.assertEqual(world.observe(), World(1234).observe())
        self.assertNotEqual(world.city, World(5678).city)
        observation = world.observe()
        observation['world']['city']['roads'][0]['start'][0] = -999
        observation['world']['city']['blocks'][0]['x'] = -999
        observation['world']['city']['x_streets'][0] = -999
        self.assertEqual(world.observe(), World(1234).observe())

    def test_connected_streets_clear_buildings_and_fixed_bounds(self):
        from city import on_city_road
        from simulation import LIMIT
        for seed in (0, 1, 42, 8224, 4294967295):
            with self.subTest(seed=seed):
                world = World(seed)
                roads = world.city['roads']
                self.assertLess(len(roads), 220)
                graph = {}
                for r in roads:
                    a, b = tuple(r['start']), tuple(r['end'])
                    graph.setdefault(a, set()).add(b)
                    graph.setdefault(b, set()).add(a)
                visited, pending = set(), [(5, 5)]
                while pending:
                    node = pending.pop()
                    if node not in visited:
                        visited.add(node)
                        pending.extend(graph[node]-visited)
                self.assertEqual(len(visited), 121)
                self.assertTrue(on_city_road(world.city, 0, 30))
                for axis in ('x_streets', 'y_streets'):
                    self.assertEqual(world.city[axis][0], -LIMIT)
                    self.assertEqual(world.city[axis][-1], LIMIT)
                self.assertEqual({b['district'] for b in world.city['blocks']},
                                 {'downtown', 'industrial', 'residential', 'commercial', 'park'})
                for b in world.buildings:
                    self.assertTrue(world.collision(b['x']+b['length']-1,
                                                    b['y']+b['width']-1, radius=1))
                    for r in roads:
                        self.assertFalse(b['x'] < r['x']+r['length'] and b['x']+b['length'] > r['x']
                                         and b['y'] < r['y']+r['width'] and b['y']+b['width'] > r['y'])


class BackgroundTests(unittest.TestCase):
    def test_background_options_and_headless_defaults(self):
        args = arguments(['--background'])
        self.assertTrue(args.bot)
        self.assertTrue(args.headless)
        self.assertEqual(args.steps, 0)
        self.assertEqual(arguments(['--headless']).steps, 3600)
        self.assertEqual(arguments(['--background', '--steps', '3']).steps, 3)
        self.assertEqual(arguments(['--seed', '1234']).seed, 1234)

    def test_new_city_closes_recording_and_updates_rendered_seed(self):
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        import pygame
        with tempfile.TemporaryDirectory() as tmp:
            args = arguments(['--seed', '1234', '--record', '--recordings', tmp,
                              '--width', '320', '--height', '240'])
            events = [[], [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n)],
                      [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F9)],
                      [pygame.event.Event(pygame.QUIT)]]
            with patch('pygame.event.get', side_effect=events), patch('game.secrets.randbits', return_value=5678), redirect_stdout(io.StringIO()):
                run(args)
            sessions = sorted((json.loads(p.read_text()) for p in Path(tmp).glob('*/session.json')),
                              key=lambda meta: meta['initial_state']['settings']['seed'])
            self.assertEqual(len(sessions), 2)
            self.assertEqual(sessions[0]['stop_reason'], 'new_city')
            self.assertEqual(sessions[1]['initial_state']['world']['city']['seed'], 5678)
            self.assertEqual(sessions[1]['initial_state']['segment'], 1)

    def test_focus_loss_keeps_bot_and_recording_running(self):
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        import pygame
        for bot in [False, True]:
            with self.subTest(bot=bot), tempfile.TemporaryDirectory() as tmp:
                args = arguments(['--record', '--recordings', tmp, '--width', '320',
                                  '--height', '240'] + (['--bot'] if bot else []))
                events = [
                    [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_w)],
                    [pygame.event.Event(pygame.WINDOWFOCUSLOST)],
                    [], [pygame.event.Event(pygame.QUIT)],
                ]
                with patch('pygame.event.get', side_effect=events), redirect_stdout(io.StringIO()):
                    run(args)
                path = next(Path(tmp).glob('drive-*'))
                meta = json.loads((path/'session.json').read_text())
                self.assertEqual(meta['stop_reason'], 'quit' if bot else 'focus_lost')
                self.assertEqual(meta['frame_count'], 3 if bot else 1)
                with gzip.open(path/'frames.jsonl.gz', 'rt') as stream:
                    rows = [json.loads(line) for line in stream]
                if bot:
                    self.assertEqual(rows[-1]['keys_held'], [])
                    self.assertGreater(rows[-1]['simulation_time_s'], rows[0]['simulation_time_s'])

    def test_explicit_pause_still_stops_bot(self):
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        import pygame
        with tempfile.TemporaryDirectory() as tmp:
            args = arguments(['--bot', '--record', '--recordings', tmp,
                              '--width', '320', '--height', '240'])
            events = [[], [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE)],
                      [pygame.event.Event(pygame.WINDOWFOCUSLOST)], [],
                      [pygame.event.Event(pygame.QUIT)]]
            with patch('pygame.event.get', side_effect=events), redirect_stdout(io.StringIO()):
                run(args)
            meta = json.loads(next(Path(tmp).glob('*/session.json')).read_text())
            self.assertEqual(meta['stop_reason'], 'pause')
            self.assertEqual(meta['frame_count'], 1)
            self.assertEqual(meta['final_state']['frame'], 1)


class RendererTests(unittest.TestCase):
    def test_obscuring_building_blends_with_car_and_clear_building_stays_opaque(self):
        import pygame
        from renderer import Renderer
        pygame.font.init()
        try:
            world = World(traffic=False)
            world.car.update(x=0, y=0, a=0)
            world.camera.update(x=0, y=0)
            building = dict(id='test_building', type='building', active=True,
                            x=80, y=80, a=0, length=100, width=100, height=150,
                            color='#c6bcad', roof='#e3dac4')
            renderer = Renderer()

            def draw(objects):
                observation = world.observe()
                observation['world']['objects'] = [dict(o) for o in objects]
                return renderer.draw(observation, world.model).copy()

            car_only = draw([])
            faded = draw([building])
            with patch.object(renderer, 'obscures_car', return_value=False):
                opaque = draw([building])
            red_pixels = [(x, y) for x in range(525, 576) for y in range(340, 390)
                          if car_only.get_at((x, y)).r > 150
                          and car_only.get_at((x, y)).g < 80
                          and opaque.get_at((x, y)) != car_only.get_at((x, y))]
            self.assertTrue(red_pixels, 'test building must actually cover red car pixels')
            for point in red_pixels:
                expected = [(a*85+b*170)/255 for a, b in
                            zip(opaque.get_at(point)[:3], car_only.get_at(point)[:3])]
                actual = faded.get_at(point)[:3]
                self.assertTrue(all(abs(a-b) <= 2 for a, b in zip(actual, expected)))
            # A nearby building that does not cover the car remains fully opaque.
            clear = dict(building, x=180, y=-80)
            actual = draw([clear])
            with patch.object(renderer, 'obscures_car', return_value=False):
                expected = draw([clear])
            self.assertEqual(pygame.image.tobytes(actual, 'RGB'), pygame.image.tobytes(expected, 'RGB'))
            self.assertFalse(renderer.obscures_car(dict(building, height=5), world.observe()['car']))
        finally:
            pygame.quit()

    def test_ground_cache_scrolls_and_rebuilds_after_teleport(self):
        import pygame
        from renderer import Renderer
        pygame.font.init()
        try:
            renderer = Renderer((320, 240))
            world = World()
            with patch.object(renderer, '_draw_ground', wraps=renderer._draw_ground) as ground:
                first = world.observe()
                renderer.draw(first, world.model)
                world.camera['x'] += 10
                renderer.draw(world.observe(), world.model)
                self.assertEqual(ground.call_count, 1)
                world.camera.update(x=1400, y=-1400)
                observation = world.observe()
                actual = renderer.draw(observation, world.model).copy()
                self.assertEqual(ground.call_count, 2)
            fresh = Renderer((320, 240)).draw(world.observe(), world.model)
            self.assertEqual(pygame.image.tobytes(actual, 'RGB'), pygame.image.tobytes(fresh, 'RGB'))
            # Culling affects drawing only: off-screen objects remain in the observation.
            self.assertEqual(len(first['world']['objects']), len(observation['world']['objects']))
            self.assertTrue(any(o['bbox_normalized'] is None for o in observation['world']['objects']))
            for obj in observation['world']['objects']:
                box = obj['bbox_normalized']
                if box:
                    self.assertTrue(all(0 <= value <= 1 for value in box.values()))
        finally:
            pygame.quit()


class RecordingTests(unittest.TestCase):
    def test_every_frame_streams_and_actions_reproduce_next_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(traffic=False)
            rec = DrivingRecorder(tmp, w.observe())
            for _ in range(4):
                action = Action(accelerate=True)
                rec.capture(w.observe(), action)
                w.step(action)
            rec.close('test', w.observe())
            with gzip.open(rec.path/'frames.jsonl.gz', 'rt') as f:
                rows = [json.loads(line) for line in f]
            self.assertEqual([r['frame'] for r in rows], list(range(4)))
            self.assertTrue(all(r['image'] is None for r in rows))
            self.assertTrue(all(r['world']['objects'] for r in rows))
            for row in rows:
                self.assertEqual(row['car']['relative_position'], dict(x=0, y=0))
                for obj in row['world']['objects']:
                    self.assertEqual(obj['relative_position'],
                                     dict(x=obj['relative_center']['forward'], y=obj['relative_center']['right']))
            replay = World(traffic=False)
            for row in rows:
                self.assertEqual(replay.car, {k: row['car'][k] for k in replay.car})
                replay.step(Action(**row['actions']))
            self.assertEqual(replay.car, w.car)
            meta = json.loads((rec.path/'session.json').read_text())
            self.assertTrue(meta['completed'])
            self.assertEqual(meta['frame_count'], 4)

    def test_exclude_types_filters_recorded_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(traffic=False)
            rec = DrivingRecorder(tmp, w.observe(), exclude_types={'tree', 'lamp','bench'})
            obs = w.observe()
            rec.capture(obs, Action())
            rec.close('test', obs)
            with gzip.open(rec.path/'frames.jsonl.gz', 'rt') as f:
                row = json.loads(f.readline())
            row_types = {o['type'] for o in row['world']['objects']}
            self.assertNotIn('tree', row_types)
            self.assertNotIn('lamp', row_types)
            self.assertTrue(any(o['type'] == 'building' for o in row['world']['objects']))

    def test_duration_and_idempotent_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World()
            rec = DrivingRecorder(tmp, w.observe(), max_seconds=DT*2)
            for _ in range(3):
                rec.capture(w.observe(), Action())
                w.step(Action())
            self.assertTrue(rec.closed)
            self.assertEqual(rec.count, 2)
            rec.close()
            self.assertEqual(json.loads((rec.path/'session.json').read_text())['stop_reason'], 'duration_limit')

    def test_images_match_saved_world_without_hud(self):
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        import pygame
        from renderer import Renderer
        pygame.font.init()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                w = World()
                renderer = Renderer((1100, 760))
                rec = DrivingRecorder(tmp, w.observe(), image_interval=DT*2)
                for _ in range(3):
                    obs = w.observe()
                    rec.capture(obs, Action(), renderer.draw(obs, w.model))
                    w.step(Action())
                rec.close()
                with gzip.open(rec.path/'frames.jsonl.gz', 'rt') as f:
                    rows = [json.loads(line) for line in f]
                self.assertEqual([bool(r['image']) for r in rows], [True, False, True])
                img = pygame.image.load(str(rec.path/rows[0]['image']))
                self.assertEqual(img.get_size(), (782, 540))
                self.assertEqual(rows[0]['width'], 782)
                self.assertTrue(any(img.get_at((x, 300))[:3] != (182, 199, 159) for x in range(100, 700, 50)))
        finally:
            pygame.quit()


if __name__ == '__main__':
    unittest.main()