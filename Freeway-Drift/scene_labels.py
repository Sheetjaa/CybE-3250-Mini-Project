"""World observations and exact footprint occupancy in the player's coordinate frame."""
import math


def corners(obj):
    c, s = math.cos(obj['a']), math.sin(obj['a'])
    return [(obj['x']+f*c-r*s, obj['y']+f*s+r*c)
            for f, r in [(-obj['length']/2, -obj['width']/2),
                         (obj['length']/2, -obj['width']/2),
                         (obj['length']/2, obj['width']/2),
                         (-obj['length']/2, obj['width']/2)]]


def overlap(points, zone):
    for axis, bound, sign in [(0, zone['forward_min'], 1), (0, zone['forward_max'], -1),
                              (1, zone['right_min'], 1), (1, zone['right_max'], -1)]:
        output = []
        for i, a in enumerate(points):
            b = points[(i+1) % len(points)]
            da, db = (a[axis]-bound)*sign, (b[axis]-bound)*sign
            if da >= 0:
                output.append(a)
            if (da >= 0) != (db >= 0):
                t = da/(da-db)
                output.append((a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1])))
        points = output
    return abs(sum(a[0]*points[(i+1) % len(points)][1]-points[(i+1) % len(points)][0]*a[1]
                   for i, a in enumerate(points))) > 1e-7


def label_scene(player, objects, distance):
    c, s = math.cos(player['a']), math.sin(player['a'])
    zones = [dict(name=name, forward_min=player['length']/2,
                  forward_max=player['length']/2+distance, right_min=(lane-.5)*40,
                  right_max=(lane+.5)*40) for name, lane in [('left', -1), ('center', 0), ('right', 1)]]
    labels = {f'obstacle_{name}': False for name in ['left', 'center', 'right']}
    for o in objects:
        dx, dy = o['x']-player['x'], o['y']-player['y']
        vx, vy = o.get('vx', 0), o.get('vy', 0)
        dvx, dvy = vx-player['vx'], vy-player['vy']
        forward, right = dx*c+dy*s, -dx*s+dy*c
        o.update(vx=vx, vy=vy, active=o.get('active', True),
                 relative_position=dict(x=forward, y=right),
                 relative_center=dict(forward=forward, right=right),
                 relative_velocity=dict(forward=dvx*c+dvy*s, right=-dvx*s+dvy*c),
                 relative_heading=math.atan2(math.sin(o['a']-player['a']), math.cos(o['a']-player['a'])),
                 distance=math.hypot(dx, dy))
        if o['type'] == 'skid':
            ex, ey = o['x2']-player['x'], o['y2']-player['y']
            o['relative_end'] = dict(forward=ex*c+ey*s, right=-ex*s+ey*c)
        # Full footprints can be reconstructed from center, heading and dimensions.
        # Compute corner transforms only for solid occupancy checks, not decorations.
        o['lanes'] = []
        if o['solid'] and o['active']:
            pts = [((x-player['x'])*c+(y-player['y'])*s,
                    -(x-player['x'])*s+(y-player['y'])*c) for x, y in corners(o)]
            f0, f1 = min(q[0] for q in pts), max(q[0] for q in pts)
            r0, r1 = min(q[1] for q in pts), max(q[1] for q in pts)
            o['lanes'] = [z['name'] for z in zones
                          if f1 > z['forward_min'] and f0 < z['forward_max']
                          and r1 > z['right_min'] and r0 < z['right_max'] and overlap(pts, z)]
            for lane in o['lanes']:
                labels['obstacle_'+lane] = True
    return dict(objects=objects, labels=labels, zones=zones,
                config=dict(distance=distance, lane_width=40, distance_origin='front_bumper',
                            reference='car_heading'))
