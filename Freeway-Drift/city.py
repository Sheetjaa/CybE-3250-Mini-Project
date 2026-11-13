"""Seeded city planning in world units; no rendering dependencies."""
from simulation import CELL, ROAD


def generate_city(world):
    rnd, pick = world.rnd, world.pick
    # Keep the central avenues for the demonstration bot; vary the outer streets.
    axes = [[i*CELL + (int(rnd()*91)-45 if i not in (-5, -1, 0, 1, 5) else 0)
             for i in range(-5, 6)] for _ in range(2)]
    xs, ys = axes
    edges = set()

    def edge(a, b):
        return tuple(sorted((a, b)))

    # A randomized spanning tree guarantees every intersection is reachable.
    visited, stack = {(5, 5)}, [(5, 5)]
    while stack:
        x, y = stack[-1]
        neighbors = [(a, b) for a, b in ((x-1, y), (x+1, y), (x, y-1), (x, y+1))
                     if 0 <= a <= 10 and 0 <= b <= 10 and (a, b) not in visited]
        if not neighbors:
            stack.pop()
            continue
        target = pick(neighbors)
        edges.add(edge(stack[-1], target))
        visited.add(target)
        stack.append(target)
    # Add city loops, continuous central avenues and a perimeter ring road.
    for x in range(11):
        for y in range(11):
            if x < 10 and (y in (0, 4, 5, 6, 10) or rnd() < .20):
                edges.add(edge((x, y), (x+1, y)))
            if y < 10 and (x in (0, 4, 5, 6, 10) or rnd() < .20):
                edges.add(edge((x, y), (x, y+1)))
    roads = []
    for a, b in sorted(edges):
        x0, y0, x1, y1 = xs[a[0]], ys[a[1]], xs[b[0]], ys[b[1]]
        roads.append(dict(x=x0-ROAD/2, y=y0-ROAD/2, length=x1-x0+ROAD,
                          width=y1-y0+ROAD, axis='x' if a[1] == b[1] else 'y',
                          start=list(a), end=list(b)))

    centers = [(-850, -850), (850, -850), (850, 850), (-850, 850)]
    rotation = int(rnd()*4)
    names = ['downtown', 'industrial', 'residential', 'commercial']
    districts = [dict(name=name, x=centers[(i+rotation) % 4][0]+rnd()*240-120,
                      y=centers[(i+rotation) % 4][1]+rnd()*240-120)
                 for i, name in enumerate(names)]
    blocks, buildings, trees, props = [], [], [], []

    def tree(x, y):
        trees.append(dict(id=f'tree_{len(trees)}', type='tree', x=x, y=y, size=11+rnd()*8))

    colors = dict(downtown='#c9c9b1', industrial='#c5bda5',
                  residential='#afc18f', commercial='#d0cbb1', park='#9db585')
    for gx in range(10):
        for gy in range(10):
            x, y = xs[gx]+ROAD/2+12, ys[gy]+ROAD/2+12
            length, width = xs[gx+1]-xs[gx]-ROAD-24, ys[gy+1]-ys[gy]-ROAD-24
            district = min(districts, key=lambda d: (x-d['x'])**2+(y-d['y'])**2)['name']
            if (gx, gy) == (5, 5) or rnd() < .12:
                district = 'park'
            blocks.append(dict(x=x, y=y, length=length, width=width,
                               district=district, color=colors[district]))
            if district == 'park':
                # Leave a clear cross-shaped walkway through each park.
                for ix in (-1, 1):
                    for iy in (-1, 1):
                        for _ in range(2):
                            tree(x+length*(.5+ix*(.13+rnd()*.23)),
                                 y+width*(.5+iy*(.13+rnd()*.23)))
                continue
            nx, ny = (1, 1) if district == 'industrial' else (2, 2)
            lot_x, lot_y = length/nx, width/ny
            for ix in range(nx):
                for iy in range(ny):
                    if district == 'commercial' and rnd() < .18:
                        continue
                    factor = .52 if district == 'residential' else .78
                    bl, bw = lot_x*(factor+rnd()*.12), lot_y*(factor+rnd()*.12)
                    bx = x+ix*lot_x+8+rnd()*max(0, lot_x-bl-16)
                    by = y+iy*lot_y+8+rnd()*max(0, lot_y-bw-16)
                    height = (65+rnd()*75 if district == 'downtown' else
                              16+rnd()*18 if district in ('industrial', 'residential') else 25+rnd()*40)
                    buildings.append(dict(id=f'building_{len(buildings)}', type='building',
                        x=bx, y=by, length=bl, width=bw, height=height, district=district,
                        color=pick(['#d3c5aa', '#d3d5bf', '#c1c9b0', '#d9c9ad', '#c6bcad', '#e0d3b8']),
                        roof=pick(['#e3dac4', '#e3dfca', '#d7d9c4', '#c6cbb9'])))
            for i in range(3 if district == 'residential' else 1):
                tree(x+12+i*(length-24)/3, y-5)
    # Furniture follows real road segments, never a removed street.
    for i, road in enumerate(roads):
        x, y = road['x']+road['length']/2, road['y']+road['width']/2
        props.append(dict(id=f'lamp_{i}', type='lamp',
                          x=x if road['axis'] == 'x' else x+ROAD/2+6,
                          y=y+ROAD/2+6 if road['axis'] == 'x' else y))
    for i, block in enumerate(blocks):
        if block['district'] == 'park':
            props.append(dict(id=f'bench_{i}', type='bench',
                              x=block['x']+block['length']/2+12,
                              y=block['y']+block['width']/2+12))
    city = dict(version=1, seed=world.seed, x_streets=xs, y_streets=ys,
                roads=roads, blocks=blocks, districts=districts)
    return city, buildings, trees, props


def on_city_road(city, x, y):
    """The same rectangles drive terrain grip, the ground renderer and minimap."""
    return any(r['x'] <= x <= r['x']+r['length'] and
               r['y'] <= y <= r['y']+r['width'] for r in city['roads'])


def city_snapshot(city):
    """Detach static map metadata without a recursive copy on every frame."""
    return dict(city, x_streets=list(city['x_streets']), y_streets=list(city['y_streets']),
                roads=[dict(r, start=list(r['start']), end=list(r['end'])) for r in city['roads']],
                blocks=[dict(b) for b in city['blocks']],
                districts=[dict(d) for d in city['districts']])
