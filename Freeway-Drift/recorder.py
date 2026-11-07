"""Stream complete observations to disk instead of buffering whole sessions."""
import gzip
import json
from pathlib import Path
import time
import uuid


def dump(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False)


class DrivingRecorder:
    def __init__(self, root, initial, image_interval=.2, max_seconds=120):
        if image_interval < 0 or max_seconds < 0:
            raise ValueError('recording intervals must be nonnegative')
        self.path = Path(root) / f'drive-{time.time_ns()}-{uuid.uuid4().hex[:6]}'
        (self.path / 'frames').mkdir(parents=True)
        self.frames = gzip.open(self.path / 'frames.jsonl.gz', 'wt', encoding='utf-8', compresslevel=1)
        self.events = (self.path / 'inputs.jsonl').open('w', encoding='utf-8')
        self.origin = time.monotonic()
        self.epoch = time.time()*1000
        self.start_simulation = initial['simulation_time_s']
        self.interval = image_interval
        self.next_image = self.start_simulation
        self.max_seconds = max_seconds
        self.count = self.images = 0
        self.closed = False
        self.metadata = dict(schema_version=3, implementation='python', started_epoch_ms=self.epoch,
            state_cadence='every simulation frame, including frames without images',
            action_alignment='actions are chosen from this observation and applied to the next simulation step',
            coordinates='world units; radians; +forward along car heading; +right clockwise',
            velocity='relative_velocity = object world velocity minus player world velocity, rotated into player axes',
            objects='all objects including off-screen, decorative, effects and disabled traffic; center coordinates',
            image_interval_s=image_interval, max_duration_s=max_seconds,
            clock='epoch_ms = started_epoch_ms + monotonic elapsed_ms; simulation_time_s is separate',
            initial_state=initial, completed=False)
        self._metadata()
        self.event('start')

    def stamp(self):
        elapsed = (time.monotonic()-self.origin)*1000
        return dict(epoch_ms=self.epoch+elapsed, elapsed_ms=elapsed)

    def _metadata(self):
        temporary = self.path / 'session.json.tmp'
        temporary.write_text(json.dumps(self.metadata, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(self.path / 'session.json')

    def event(self, kind, **details):
        if not self.closed:
            self.events.write(dump(dict(**self.stamp(), type=kind, **details))+'\n')
            self.events.flush()

    def capture(self, observation, action, surface=None, keys=(), controller='manual'):
        if self.closed:
            return False
        elapsed = observation['simulation_time_s']-self.start_simulation
        if self.max_seconds and elapsed >= self.max_seconds-1e-9:
            self.close('duration_limit', observation)
            return False
        row = dict(observation, **self.stamp(), record_frame=self.count, actions=action.to_dict(),
                   keys_held=sorted(keys), controller=controller, image=None)
        if surface is not None and observation['simulation_time_s']+1e-9 >= self.next_image:
            import pygame
            width, height = surface.get_size()
            scale = min(1, 960/width, 540/height)
            size = (max(1, round(width*scale)), max(1, round(height*scale)))
            image = pygame.transform.smoothscale(surface, size) if scale < 1 else surface
            row['image'] = f'frames/{self.count:08d}.png'
            row.update(width=size[0], height=size[1], source_width=width, source_height=height)
            # Only image dimensions change; the observation remains detached from the world.
            for obj in row['world']['objects']:
                box = obj.get('bbox_normalized')
                obj['bbox_pixels'] = ({key: value*(size[0] if key.startswith('x') else size[1])
                                       for key, value in box.items()} if box else None)
            pygame.image.save(image, str(self.path / row['image']))
            self.images += 1
            self.next_image = observation['simulation_time_s']+self.interval
        self.frames.write(dump(row)+'\n')
        self.count += 1
        if self.count % 60 == 0:
            self.frames.flush()
        return True

    def close(self, reason='manual', final=None):
        if self.closed:
            return
        self.event('stop', reason=reason, state=final)
        self.closed = True
        self.frames.close()
        self.events.close()
        self.metadata.update(completed=True, frame_count=self.count, image_count=self.images,
                             stop_reason=reason, final_state=final)
        self._metadata()
