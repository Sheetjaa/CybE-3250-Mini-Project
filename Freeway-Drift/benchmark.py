"""Measure uncapped observation, rendering and simulation time without a window."""
import argparse
import os
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', type=int, default=600)
    parser.add_argument('--width', type=int, default=1100)
    parser.add_argument('--height', type=int, default=760)
    args = parser.parse_args()
    if args.frames < 1 or args.width < 320 or args.height < 240:
        parser.error('frames must be positive; minimum size is 320 x 240')
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    import pygame
    from bot import BasicBot
    from renderer import Renderer
    from simulation import World

    pygame.font.init()
    try:
        world, policy = World(traffic=False), BasicBot()
        renderer = Renderer((args.width, args.height))
        times = dict(observation=0., rendering=0., policy_and_physics=0.)
        for _ in range(args.frames):
            started = time.perf_counter()
            observation = world.observe()
            observed = time.perf_counter()
            renderer.draw(observation, world.model)
            rendered = time.perf_counter()
            world.step(policy.act(observation))
            stepped = time.perf_counter()
            times['observation'] += observed-started
            times['rendering'] += rendered-observed
            times['policy_and_physics'] += stepped-rendered
        total = sum(times.values())
        print(f'{args.frames} frames at {args.width} x {args.height}: '
              f'{args.frames/total:.1f} frames/s, {total/args.frames*1000:.2f} ms/frame')
        for name, seconds in times.items():
            print(f'  {name}: {seconds/args.frames*1000:.2f} ms/frame')
        print('Includes cold renderer caches; excludes display, HUD, recording and frame cap.')
    finally:
        pygame.quit()


if __name__ == '__main__':
    main()
