"""Deterministic Freeway Drift simulation. No rendering or ML dependencies."""
from dataclasses import asdict, dataclass
import math

CELL, ROAD, LIMIT = 310, 88, 1550
DT = 1 / 60
MODELS = [
    dict(name='FERRARI', style='ferrari', color='#dc171f', roof='#fa3439', max=205, accel=100,
         grip=7.8, turn=2.3, length=33, width=17),
    dict(name='THE WEEKENDER', color='#c9735e', roof='#e39678', max=270, accel=125,
         grip=5.3, turn=2.55, length=38, width=18),
    dict(name='THE EXPLORER', color='#7c9d96', roof='#aac1b1', max=175, accel=75,
         grip=8.5, turn=1.85, length=40, width=20),
]


def clamp(value, low, high):
    return max(low, min(high, value))


@dataclass(frozen=True)
class Action:
    accelerate: bool = False
    brake_reverse: bool = False
    steering: float = 0.0  # -1 left, +1 right (clockwise in the world)
    handbrake: bool = False

    def __post_init__(self):
        if not math.isfinite(self.steering) or not -1 <= self.steering <= 1:
            raise ValueError('steering must be finite and in [-1, 1]')

    def to_dict(self):
        return asdict(self)


class World:
    def __init__(self, seed=8224, model=0, traffic=True, lookahead=140):
        if not 0 <= model < len(MODELS):
            raise ValueError('model must be 0, 1 or 2')
        if not math.isfinite(lookahead) or not 10 <= lookahead <= 500:
            raise ValueError('lookahead must be in [10, 500]')
        self.seed = seed
        self.rng_state = seed & 0xffffffff
        self.model_index = model
        self.model = MODELS[model]
        self.traffic_on = traffic
        self.lookahead = lookahead
        self.frame = 0
        self.segment = -1
        self.time = 0.0
        self.buildings, self.trees, self.props, self.traffic = [], [], [], []
        self.particles, self.skids = [], []
        self.effect_id = 0
        self.collisions = 0
        self.generate()
        self.reset()

    def rnd(self):
        self.rng_state = (self.rng_state * 1664525 + 1013904223) & 0xffffffff
        return self.rng_state / 4294967296

    def pick(self, values):
        return values[int(self.rnd() * len(values))]

    def generate(self):
        from city import generate_city
        self.city, self.buildings, self.trees, self.props = generate_city(self)
        for i in range(25):
            self.traffic.append(dict(id=f'traffic_{i}', type='traffic', axis=i % 2,
                dir=1 if i % 4 < 2 else -1, lane=self.pick([-CELL, 0, CELL]),
                pos=(self.rnd()*2-1)*LIMIT, speed=48+self.rnd()*35,
                color=self.pick(['#d9bb79', '#8eaaa4', '#b9c1a9', '#bf8e7b', '#e5d8bf']), blocked=False))

    def reset(self):
        """Reset the player; traffic and the session clock continue, as in the browser."""
        self.car = dict(x=0.0, y=30.0, a=-math.pi/2, vx=0.0, vy=0.0, steer=0.0)
        self.camera = dict(x=0.0, y=30.0)
        self.segment += 1

    @staticmethod
    def traffic_pose(t):
        if t['axis'] == 0:
            return dict(x=t['pos'], y=t['lane']+t['dir']*20, a=0 if t['dir'] == 1 else math.pi)
        return dict(x=t['lane']-t['dir']*20, y=t['pos'], a=math.pi/2 if t['dir'] == 1 else -math.pi/2)

    def collision(self, x, y, radius=12):
        if abs(x) > LIMIT+34 or abs(y) > LIMIT+34:
            return True
        # Reject distant footprints, including the larger warehouse buildings.
        for b in self.buildings:
            if (x+radius < b['x'] or x-radius > b['x']+b['length'] or
                    y+radius < b['y'] or y-radius > b['y']+b['width']):
                continue
            nx, ny = clamp(x, b['x'], b['x']+b['length']), clamp(y, b['y'], b['y']+b['width'])
            if (x-nx)**2 + (y-ny)**2 < radius**2:
                return True
        return False

    def effect(self, kind, **values):
        self.effect_id += 1
        return dict(id=f'{kind}_{self.effect_id}', type=kind, **values)

    def puff(self, x, y, count, color):
        for _ in range(count):
            self.particles.append(self.effect('particle', x=x, y=y, z=4+self.rnd()*5,
                vx=(self.rnd()-.5)*40, vy=(self.rnd()-.5)*40, life=.3+self.rnd()*.5,
                max_life=.8, color=color, size=2+self.rnd()*4))

    def step(self, action, dt=DT):
        if not isinstance(action, Action):
            raise TypeError('step expects an Action')
        if not math.isfinite(dt) or not 0 < dt <= .05:
            raise ValueError('dt must be in (0, .05]')
        count = math.ceil(dt / .012)
        for _ in range(count):
            self._substep(action, dt/count)
        self.time += dt
        self.frame += 1

    def _substep(self, action, dt):
        p, m = self.car, self.model
        c, s = math.cos(p['a']), math.sin(p['a'])
        forward, speed = p['vx']*c+p['vy']*s, math.hypot(p['vx'], p['vy'])
        p['steer'] += (action.steering-p['steer'])*min(1, dt*9)
        if action.brake_reverse:
            if forward > 5:
                p['vx'] *= max(0, 1-dt*3.4)
                p['vy'] *= max(0, 1-dt*3.4)
            else:
                p['vx'] -= c*m['accel']*.55*dt
                p['vy'] -= s*m['accel']*.55*dt
        elif action.accelerate:
            p['vx'] += c*m['accel']*dt
            p['vy'] += s*m['accel']*dt
        p['a'] += p['steer']*m['turn']*clamp(abs(forward)/52, 0, 1)*(-1 if forward < -.5 else 1)*(1.25 if action.handbrake else 1)*dt
        c, s = math.cos(p['a']), math.sin(p['a'])
        f, side = p['vx']*c+p['vy']*s, -p['vx']*s+p['vy']*c
        from city import on_city_road
        grass = not on_city_road(self.city, p['x'], p['y'])
        side *= math.exp(-(1 if action.handbrake else m['grip'])*dt)
        f *= math.exp(-(1.1 if action.handbrake else 1 if grass else .28)*dt)
        f = clamp(f, -65, m['max']*(.65 if grass else 1))
        p['vx'], p['vy'] = f*c-side*s, f*s+side*c
        old_x, old_y = p['x'], p['y']
        nx, ny = old_x+p['vx']*dt, old_y+p['vy']*dt
        hit = False
        if not self.collision(nx, p['y']):
            p['x'] = nx
        else:
            p['vx'] *= -.26
            hit = True
        if not self.collision(p['x'], ny):
            p['y'] = ny
        else:
            p['vy'] *= -.26
            hit = True
        if hit:
            self.collisions += 1
            if speed > 30:
                self.puff(p['x'], p['y'], 4, '#dfd4b2')
        if speed > 45 and (abs(side) > 20 or action.handbrake):
            for sign in [-1, 1]:
                ox, oy = sign*7*s-11*c, -sign*7*c-11*s
                self.skids.append(self.effect('skid', x=old_x+ox, y=old_y+oy,
                    x2=p['x']+ox, y2=p['y']+oy, life=8.0))
        self.update_traffic(dt)
        for particle in self.particles:
            particle['life'] -= dt
            particle['x'] += particle['vx']*dt
            particle['y'] += particle['vy']*dt
            particle['z'] += 9*dt
        self.particles = [p for p in self.particles if p['life'] > 0][-160:]
        for skid in self.skids:
            skid['life'] -= dt
        self.skids = [s for s in self.skids if s['life'] > 0][-700:]
        for axis in ['x', 'y']:
            self.camera[axis] += (p[axis]+p['v'+axis]*.42-self.camera[axis])*min(1, dt*4)

    def update_traffic(self, dt):
        if not self.traffic_on:
            return
        # Simultaneous decisions avoid dependence on list/update order.
        poses = [self.traffic_pose(t) for t in self.traffic]
        for t, v in zip(self.traffic, poses):
            c, s = math.cos(v['a']), math.sin(v['a'])
            dx, dy = self.car['x']-v['x'], self.car['y']-v['y']
            blocked = 0 < dx*c+dy*s < 85 and abs(-dx*s+dy*c) < 24
            for other, ov in zip(self.traffic, poses):
                if other is t:
                    continue
                ox, oy = ov['x']-v['x'], ov['y']-v['y']
                if 0 < ox*c+oy*s < 48 and abs(-ox*s+oy*c) < 20:
                    blocked = True
                    break
            t['blocked'] = blocked
            t['pos'] += t['dir']*t['speed']*(not blocked)*dt
            if abs(t['pos']) > LIMIT+30:
                t['pos'] = -math.copysign(LIMIT+30, t['pos'])
            dist = math.hypot(dx, dy)
            if .01 < dist < 25:
                nx, ny = self.car['x']+dx/dist*(25-dist), self.car['y']+dy/dist*(25-dist)
                if not self.collision(nx, ny):
                    self.car['x'], self.car['y'] = nx, ny
                self.car['vx'] *= .94
                self.car['vy'] *= .94
                self.collisions += 1

    def objects(self):
        """All objects, including disabled traffic; coordinates are object centers."""
        objects = []
        for b in self.buildings:
            objects.append(dict(b, x=b['x']+b['length']/2, y=b['y']+b['width']/2,
                                height=b['height']+9, a=0, solid=True))
        for t in self.trees:
            objects.append(dict(t, a=0, length=t['size'], width=t['size'],
                                height=10+t['size']*1.28, solid=False))
        for p in self.props:
            lamp = p['type'] == 'lamp'
            objects.append(dict(p, x=p['x']+(1 if lamp else 3.5), y=p['y']+(1 if lamp else 10.5),
                                a=0, length=4 if lamp else 7, width=7 if lamp else 21,
                                height=37 if lamp else 12, solid=False))
        for t in self.traffic:
            pose = self.traffic_pose(t)
            moving = self.traffic_on and not t['blocked']
            objects.append(dict(t, **pose, length=32, width=16, height=18,
                vx=math.cos(pose['a'])*t['speed']*moving,
                vy=math.sin(pose['a'])*t['speed']*moving, active=self.traffic_on, solid=self.traffic_on))
        objects.append(dict(id='fountain', type='fountain', x=155, y=155, a=0,
                            length=32, width=32, height=3, solid=False))
        objects.extend(dict(p, a=0, length=p['size'], width=p['size'], height=0, solid=False) for p in self.particles)
        objects.extend(dict(s, a=0, length=0, width=0, height=0, solid=False) for s in self.skids)
        return objects

    def observe(self):
        from city import city_snapshot
        from scene_labels import label_scene
        p = dict(self.car, model=self.model['name'], length=self.model['length'], width=self.model['width'])
        p.update(relative_position=dict(x=0.0, y=0.0),
                 relative_center=dict(forward=0.0, right=0.0), relative_heading=0.0)
        scene = label_scene(p, self.objects(), self.lookahead)
        objects = scene.pop('objects')
        return dict(frame=self.frame, simulation_time_s=self.time, segment=self.segment,
            car=p, camera=dict(self.camera), collisions=self.collisions, rng_state=self.rng_state, scene=scene,
            settings=dict(traffic=self.traffic_on, model=self.model_index, seed=self.seed),
            world=dict(bounds=dict(x_min=-LIMIT-34, y_min=-LIMIT-34, x_max=LIMIT+34, y_max=LIMIT+34),
                       roads=dict(cell_size=CELL, width=ROAD, layout='generated', segments_field='city.roads'),
                       city=city_snapshot(self.city),
                       park=dict(self.city['blocks'][55], path_width=12),
                       objects=objects))
