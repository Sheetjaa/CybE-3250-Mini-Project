"""Run `python game.py` for manual play or `python game.py --bot` for the bot."""
import argparse
import importlib
import math
import secrets
from pathlib import Path
import sys
import time

from simulation import Action, DT, MODELS, World
from recorder import DrivingRecorder

DRIVE_KEYS = {'w', 'a', 's', 'd', 'up', 'down', 'left', 'right', 'space'}


def manual_action(keys):
    return Action(accelerate=bool(keys & {'w', 'up'}), brake_reverse=bool(keys & {'s', 'down'}),
                  steering=int(bool(keys & {'d', 'right'}))-int(bool(keys & {'a', 'left'})),
                  handbrake='space' in keys)


def load_policy(spec):
    module, sep, name = spec.partition(':')
    if not sep:
        raise ValueError('policy must be module:ClassName')
    return getattr(importlib.import_module(module), name)()


def arguments(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bot', action='store_true', help='start with the policy controlling the car')
    p.add_argument('--policy', default='bot:BasicBot', help='importable module:ClassName with act(observation)')
    p.add_argument('--headless', action='store_true', help='run without a display or real-time throttling')
    p.add_argument('--background', action='store_true',
                   help='run the bot without a window at real-time speed until interrupted')
    p.add_argument('--steps', type=int, default=None,
                   help='headless frame limit; 0 = unlimited (default: 3600, or 0 with --background)')
    p.add_argument('--render', action='store_true', help='render PNGs even in headless mode')
    p.add_argument('--record', action='store_true', help='start recording immediately')
    p.add_argument('--recordings', type=Path, default=Path(__file__).parent/'recordings')
    p.add_argument('--exclude-objects', default='',
                   help='comma-separated object types to omit from recorded world objects, e.g. tree,lamp,bench')
    p.add_argument('--image-interval', type=float, default=.2, help='seconds between PNGs; 0 = every frame')
    p.add_argument('--max-record-seconds', type=float, default=120, help='simulation seconds; 0 = unlimited')
    p.add_argument('--seed', type=int, default=None, help='repeat a city seed; default: a new random city')
    p.add_argument('--car', type=int, choices=range(3), default=0)
    p.add_argument('--no-traffic', action='store_true')
    p.add_argument('--lookahead', type=float, default=140)
    p.add_argument('--width', type=int, default=1100)
    p.add_argument('--height', type=int, default=760)
    args = p.parse_args(argv)
    if args.seed is None:
        args.seed = secrets.randbits(32)
    if args.background:
        args.bot = args.headless = True
    if args.steps is None:
        args.steps = 0 if args.background else 3600
    if args.steps < 0 or args.width < 320 or args.height < 240:
        p.error('steps must be nonnegative; minimum window size is 320 x 240')
    if not all(math.isfinite(v) and v >= 0 for v in [args.image_interval, args.max_record_seconds]):
        p.error('recording intervals must be finite and nonnegative')
    if not math.isfinite(args.lookahead) or not 10 <= args.lookahead <= 500:
        p.error('lookahead must be in [10, 500]')
    args.exclude_objects = {value.strip() for value in args.exclude_objects.split(',') if value.strip()}
    return args


def run(args):
    world = World(args.seed, args.car, not args.no_traffic, args.lookahead)
    print(f'City seed: {world.seed}', flush=True)
    policy = load_policy(args.policy)
    bot = args.bot
    recorder = None
    renderer = screen = None
    pygame = None
    keys = set()
    paused = detections = False
    reason = 'quit'

    def start_recording():
        rec = DrivingRecorder(args.recordings, world.observe(), args.image_interval,
                             args.max_record_seconds, args.exclude_objects)
        print(f'Recording: {rec.path}', flush=True)
        return rec

    try:
        if not args.headless or args.render:
            if args.headless:
                import os
                os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
            import pygame as pg
            pygame = pg
            pygame.display.init()
            pygame.font.init()
            from renderer import Renderer
            renderer = Renderer((args.width, args.height))
            if not args.headless:
                screen = pygame.display.set_mode((args.width, args.height))
                pygame.display.set_caption('Freeway Drift — Python')
            clock = pygame.time.Clock()
        if args.record:
            recorder = start_recording()
        active = True
        while active and (not args.headless or not args.steps or world.frame < args.steps):
            frame_started = time.monotonic()
            if not args.headless:
                clock.tick(60)
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        active = False
                        break
                    if event.type == pygame.WINDOWFOCUSLOST:
                        keys.clear()
                        if recorder and not recorder.closed:
                            recorder.event('release_all', reason='focus_lost')
                        if not bot:
                            paused = True
                            if recorder and not recorder.closed:
                                recorder.close('focus_lost', world.observe())
                    if event.type in (pygame.KEYDOWN, pygame.KEYUP):
                        key = pygame.key.name(event.key)
                        down = event.type == pygame.KEYDOWN
                        if key in DRIVE_KEYS:
                            changed = (key not in keys) if down else (key in keys)
                            if down and not paused:
                                keys.add(key)
                            else:
                                keys.discard(key)
                            if changed and recorder:
                                recorder.event('keydown' if down and not paused else 'keyup', key=key,
                                               source='keyboard', keys_held=sorted(keys))
                        if not down or getattr(event, 'repeat', False):
                            continue
                        if key == 'escape':
                            paused = not paused
                            keys.clear()
                            if paused and recorder and not recorder.closed:
                                recorder.event('release_all', reason='pause')
                                recorder.close('pause', world.observe())
                        elif key == 'r':
                            keys.clear()
                            world.reset()
                            if recorder:
                                recorder.event('reset', segment=world.segment)
                        elif key == 'n':
                            keys.clear()
                            if recorder and not recorder.closed:
                                recorder.event('release_all', reason='new_city')
                                recorder.close('new_city', world.observe())
                            segment = world.segment+1
                            world = World(secrets.randbits(32), world.model_index,
                                          world.traffic_on, world.lookahead)
                            world.segment = segment
                            print(f'City seed: {world.seed}', flush=True)
                        elif key == 'b':
                            bot = not bot
                            keys.clear()
                            if recorder:
                                recorder.event('controller', controller=args.policy if bot else 'manual')
                        elif key == 't':
                            world.traffic_on = not world.traffic_on
                            if recorder:
                                recorder.event('traffic', enabled=world.traffic_on)
                        elif key == 'g':
                            detections = not detections
                        elif key in {'1', '2', '3'}:
                            world.model_index = int(key)-1
                            world.model = MODELS[world.model_index]
                            world.car['vx'] = world.car['vy'] = 0
                            if recorder:
                                recorder.event('model', model=world.model_index)
                        elif key == 'f9' and not paused:
                            if recorder and not recorder.closed:
                                recorder.close('manual', world.observe())
                            else:
                                recorder = start_recording()
            if not active:
                break
            observation = world.observe()
            surface = renderer.draw(observation, world.model) if renderer else None
            if not paused:
                action = policy.act(observation) if bot else manual_action(keys)
                if not isinstance(action, Action):
                    raise TypeError('policy.act must return simulation.Action')
                if recorder:
                    recorder.capture(observation, action, surface, keys, args.policy if bot else 'manual')
            if screen is not None:
                screen.blit(surface, (0, 0))
                renderer.overlay(screen, observation, bot, paused,
                                 recorder is not None and not recorder.closed, detections)
                pygame.display.flip()
            if not paused:
                world.step(action)
            if args.background:
                time.sleep(max(0, DT-(time.monotonic()-frame_started)))
        reason = 'steps_complete' if args.headless else 'quit'
    except KeyboardInterrupt:
        reason = 'interrupted'
        raise
    except BaseException:
        reason = 'error'
        raise
    finally:
        if recorder:
            recorder.close(reason, world.observe())
        if pygame:
            pygame.quit()
    p = world.car
    print(f'Frames: {world.frame}; simulation: {world.time:.2f}s; '
          f'car: ({p["x"]:.1f}, {p["y"]:.1f}); collision contacts: {world.collisions}')


if __name__ == '__main__':
    import signal

    def stop_background(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_background)
    try:
        run(arguments())
    except KeyboardInterrupt:
        sys.exit(130)
