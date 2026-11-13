"""Pygame isometric renderer; recording receives only the world surface."""
import math
from functools import lru_cache
import pygame
from scene_labels import corners
from simulation import CELL, ROAD, LIMIT, clamp


@lru_cache(maxsize=256)
def shade(color, factor):
    rgb = pygame.Color(color)
    return tuple(clamp(round(v*factor), 0, 255) for v in (rgb.r, rgb.g, rgb.b))


class Renderer:
    def __init__(self, size=(1100, 760)):
        self.size = size
        self.surface = pygame.Surface(size)
        self.zoom = clamp(min(size[0]/1100, size[1]/760), .72, 1.6)
        self.camera = dict(x=0, y=0)
        self.font = pygame.font.Font(None, 24)
        self._ground = None
        self._ground_camera = None
        self._offset = (0, 0)
        self._hud = {}
        self._city = None
        self._city_key = None
        self._minimap = None
        self._building_layer = None

    def project(self, x, y, z=0):
        dx, dy = x-self.camera['x'], y-self.camera['y']
        return ((dx-dy)*.866*self.zoom+self.size[0]*.5+self._offset[0],
                (dx+dy)*.5*self.zoom-z*self.zoom+self.size[1]*.49+self._offset[1])

    def polygon(self, points, color):
        pygame.draw.polygon(self.surface, color, points)

    def rect(self, x, y, length, width, color, z=0):
        self.polygon([self.project(x, y, z), self.project(x+length, y, z),
                      self.project(x+length, y+width, z), self.project(x, y+width, z)], color)

    def box(self, obj, color, roof=None, z=0):
        pts = corners(obj)
        low = [self.project(x, y, z) for x, y in pts]
        high = [self.project(x, y, z+obj['height']) for x, y in pts]
        # Draw only the two sides facing the isometric camera.
        for i in range(4):
            j = (i+1) % 4
            if (pts[j][1]-pts[i][1])-(pts[j][0]-pts[i][0]) > 0:
                self.polygon([low[i], low[j], high[j], high[i]], shade(color, .84 if i % 2 else 1))
        self.polygon(high, roof or shade(color, 1.07))

    def ferrari(self, obj, color, roof):
        """Low red sports body, dark cockpit, alloy wheels and yellow nose badge."""
        c, s = math.cos(obj['a']), math.sin(obj['a'])
        length, width = obj['length'], obj['width']

        def part(forward, right, part_length, part_width, height, z, paint, top=None):
            self.box(dict(obj, x=obj['x']+forward*c-right*s,
                          y=obj['y']+forward*s+right*c,
                          length=part_length, width=part_width, height=height),
                     paint, top, z=z)

        for f in (-length*.31, length*.30):
            for r in (-width*.48, width*.48):
                part(f, r, 8, 3.5, 5, 1, '#202326', '#69747c')
        # A wide rear deck and a tapered nose distinguish it from city traffic.
        part(-length*.12, 0, length*.76, width, 5, 3, color, roof)
        part(length*.35, 0, length*.30, width*.85, 4, 3, color, roof)
        part(-length*.08, 0, length*.40, width*.72, 4, 8, '#182c36', '#34525e')
        part(-length*.13, 0, length*.18, width*.73, 1, 12, color, roof)
        # Engine vents, side intakes, slim headlights and paired tail lights.
        for f in (-length*.35, -length*.40):
            part(f, 0, 1.1, width*.62, .4, 8, '#303034', '#303034')
        for r in (-width*.41, width*.41):
            part(-length*.14, r, length*.18, 1.4, 2, 5, '#29272a')
            part(length*.40, r*.75, 3.7, 2.5, .5, 7, '#fff2c5', '#fff2c5')
            part(-length*.48, r*.74, 1.2, 3, 1.8, 5, '#ff6353', '#ff6353')
        part(length*.31, 0, 2, 1.8, .4, 7.5, '#ffd143', '#ffd143')

    def car(self, obj, color, roof, sports=False):
        if sports:
            self.ferrari(obj, color, roof)
            return
        for f in [-obj['length']*.3, obj['length']*.29]:
            for r in [-obj['width']*.5, obj['width']*.5]:
                c, s = math.cos(obj['a']), math.sin(obj['a'])
                wheel = dict(obj, x=obj['x']+f*c-r*s, y=obj['y']+f*s+r*c,
                             length=8, width=4, height=5)
                self.box(wheel, '#36453f', z=2)
        self.box(dict(obj, height=7), color, roof, z=4)
        self.box(dict(obj, length=obj['length']*.48, width=obj['width']*.81, height=6),
                 '#456862', '#b8cbc0', z=11)
        self.box(dict(obj, length=obj['length']*.29, width=obj['width']*.86, height=1), roof, roof, z=17)

    @staticmethod
    def obscures_car(building, player):
        # A ray toward this isometric camera moves equally in +x, +y and +z.
        # Test the car's footprint and center, including its body and roof.
        x0 = building['x']-building['length']/2
        x1 = building['x']+building['length']/2
        y0 = building['y']-building['width']/2
        y1 = building['y']+building['width']/2
        for x, y in [*corners(player), (player['x'], player['y'])]:
            for z in (4, 12):
                entry = max(0, x0-x, y0-y)
                exit = min(x1-x, y1-y, building['height']+2-z)
                if exit > entry:
                    return True
        return False

    def building(self, obj, translucent=False):
        target = self.surface
        if translucent:
            if self._building_layer is None:
                self._building_layer = pygame.Surface(self.size, pygame.SRCALPHA)
                self._building_layer.set_alpha(85)
            box = obj['bbox_normalized']
            # Include the roof cap and rasterized boundary pixels.
            area = pygame.Rect(math.floor(box['x_min']*self.size[0]),
                               math.floor(box['y_min']*self.size[1]),
                               math.ceil((box['x_max']-box['x_min'])*self.size[0]),
                               math.ceil((box['y_max']-box['y_min'])*self.size[1]))
            area = area.inflate(8, 8).clip(target.get_rect())
            self._building_layer.fill((0, 0, 0, 0), area)
            self.surface = self._building_layer
        try:
            # Composite the entire building once so walls, roof and windows
            # share one opacity, even where their polygons overlap.
            self.box(obj, obj['color'], obj['roof'])
            self.box(dict(obj, length=obj['length']-10, width=obj['width']-10, height=2),
                     obj['roof'], obj['roof'], z=obj['height'])
            for z in range(10, int(obj['height'])-10, 16):
                for dx in range(12, int(obj['length'])-8, 19):
                    self.rect(obj['x']-obj['length']/2+dx, obj['y']+obj['width']/2+.1,
                              7, .8, '#7e9690', z)
        finally:
            self.surface = target
        if translucent:
            target.blit(self._building_layer, area, area)

    def _draw_ground(self):
        self.surface.fill('#b6c79f')
        self.rect(-LIMIT-95, -LIMIT-95, LIMIT*2+190, LIMIT*2+190, '#a9bc96')
        for block in self._city['blocks']:
            x, y, length, width = (block[k] for k in ('x', 'y', 'length', 'width'))
            self.rect(x, y, length, width, block['color'])
            if block['district'] == 'park':
                self.rect(x, y+width/2-6, length, 12, '#d3d2b5')
                self.rect(x+length/2-6, y, 12, width, '#d3d2b5')
            elif block['district'] in ('industrial', 'commercial'):
                # Parking aprons make warehouse and shop blocks feel different.
                self.rect(x, y, length, 24, '#a2a99a')
                for dx in range(10, int(length)-10, 18):
                    self.rect(x+dx, y+3, 1.5, 16, '#dedcc3')
        for r in self._city['roads']:
            self.rect(r['x']-10, r['y']-10, r['length']+20, r['width']+20, '#d8d8be')
        for r in self._city['roads']:
            self.rect(r['x'], r['y'], r['length'], r['width'], '#87958a')
        for r in self._city['roads']:
            horizontal = r['axis'] == 'x'
            span = r['length'] if horizontal else r['width']
            for n in range(ROAD+12, int(span)-ROAD, 39):
                x = r['x']+n if horizontal else r['x']+ROAD/2-1
                y = r['y']+ROAD/2-1 if horizontal else r['y']+n
                self.rect(x, y, 16 if horizontal else 2, 2 if horizontal else 16, '#d7dac1')
            for end in (ROAD+3, span-ROAD-13):
                for k in range(12, ROAD-10, 12):
                    self.rect(r['x']+(end if horizontal else k),
                              r['y']+(k if horizontal else end),
                              10 if horizontal else 7, 7 if horizontal else 10, '#d9ddc3')

    def _blit_ground(self):
        # Keep a viewport-sized cache with a gutter, rather than a full-city bitmap.
        # Camera movement only changes the blit position until the gutter runs out.
        margin = 128
        dx = dy = 0
        if self._ground_camera is not None:
            cx = self._ground_camera['x']-self.camera['x']
            cy = self._ground_camera['y']-self.camera['y']
            dx = round((cx-cy)*.866*self.zoom)
            dy = round((cx+cy)*.5*self.zoom)
        if self._ground is None or abs(dx) > margin or abs(dy) > margin:
            if self._ground is None:
                self._ground = pygame.Surface((self.size[0]+2*margin, self.size[1]+2*margin))
            target = self.surface
            self.surface = self._ground
            self._offset = (margin, margin)
            try:
                self._draw_ground()
            finally:
                self.surface = target
                self._offset = (0, 0)
            self._ground_camera = dict(self.camera)
            dx = dy = 0
        self.surface.blit(self._ground, (dx-margin, dy-margin))

    def draw(self, observation, model):
        self.camera = observation['camera']
        observation['camera']['zoom'] = self.zoom
        observation['viewport'] = dict(width=self.size[0], height=self.size[1], projection='isometric')
        self._city = observation['world']['city']
        city_key = (self._city['seed'], self._city['version'])
        if city_key != self._city_key:
            self._ground = self._ground_camera = self._minimap = None
            self._city_key = city_key
        self._blit_ground()
        objects = observation['world']['objects']
        visible_objects = []
        for obj in objects:
            projected = [self.project(x, y) for x, y in corners(obj)]
            xs, ys = [p[0] for p in projected], [p[1] for p in projected]
            x0, y0, x1, y1 = min(xs), min(ys)-obj['height']*self.zoom, max(xs), max(ys)
            width, height = self.size
            visible = obj['active'] and x1 > 0 and y1 > 0 and x0 < width and y0 < height
            obj['bbox_normalized'] = (dict(x_min=max(0, x0)/width, y_min=max(0, y0)/height,
                                          x_max=min(width, x1)/width, y_max=min(height, y1)/height)
                                      if visible else None)
            if visible:
                visible_objects.append(obj)

        for o in objects:
            if o['type'] == 'skid':
                pygame.draw.line(self.surface, '#66765f', self.project(o['x'], o['y']), self.project(o['x2'], o['y2']), 2)
        player = dict(observation['car'], id='player', type='player', active=True)
        player_drawn = False
        for o in sorted([*visible_objects, player], key=lambda o: o['x']+o['y']):
            if not o['active'] or o['type'] == 'skid':
                continue
            kind = o['type']
            if kind == 'building':
                self.building(o, translucent=player_drawn and self.obscures_car(o, player))
            elif kind == 'tree':
                self.box(dict(o, length=4, width=4, height=12), '#8d8161')
                self.box(dict(o, height=o['size']*.8), '#7e9c67', '#99b27b', z=10)
                self.box(dict(o, length=o['size']*.66, width=o['size']*.66, height=o['size']*.48),
                         '#8da96f', '#a9bf88', z=10+o['size']*.8)
            elif kind == 'lamp':
                self.box(dict(o, length=2, width=2, height=34), '#98a390')
                self.box(dict(o, height=3), '#bcc5af', '#eee9cc', z=34)
            elif kind == 'bench':
                self.box(dict(o, height=5), '#a18c6b', '#bea986')
            elif kind in ['traffic', 'player']:
                self.car(o, model['color'] if kind == 'player' else o['color'],
                         model['roof'] if kind == 'player' else shade(o['color'], 1.07),
                         sports=kind == 'player' and model.get('style') == 'ferrari')
                if kind == 'player':
                    player_drawn = True
            elif kind == 'particle':
                pygame.draw.circle(self.surface, o['color'], self.project(o['x'], o['y'], o['z']), max(1, round(o['size']*self.zoom)))
            elif kind == 'fountain':
                self.box(o, '#b8c5ad', '#9dbfba')
        return self.surface

    def overlay(self, screen, observation, bot, paused, recording, detections=False):
        if detections:
            p = observation['car']
            c, s = math.cos(p['a']), math.sin(p['a'])
            for z in observation['scene']['zones']:
                points = [self.project(p['x']+f*c-r*s, p['y']+f*s+r*c, 1)
                          for f, r in [(z['forward_min'], z['right_min']), (z['forward_max'], z['right_min']),
                                       (z['forward_max'], z['right_max']), (z['forward_min'], z['right_max'])]]
                color = '#ff755c' if observation['scene']['labels']['obstacle_'+z['name']] else '#60e9b0'
                pygame.draw.polygon(screen, color, points, 2)
        speed = math.hypot(observation['car']['vx'], observation['car']['vy'])
        lines = [f'FREEWAY DRIFT   {speed*.48:.0f} km/h   {observation["car"]["model"]}',
                 'WASD / arrows: drive   Space: handbrake   R: reset   Esc: pause',
                 'B: bot   F9: record   T: traffic   G: zones   1/2/3: car   N: new city',
                 f'{"BOT" if bot else "MANUAL"}   {"PAUSED" if paused else "DRIVING"}   {"RECORDING" if recording else ""}   City {self._city["seed"]}']
        for i, line in enumerate(lines):
            previous = self._hud.get(i)
            if previous is None or previous[0] != line:
                self._hud[i] = (line, self.font.render(line, True, '#f5f3e9', '#273e36'))
            screen.blit(self._hud[i][1], (16, 16+i*25))
        # Minimap is drawn only on the display, never into recorded images.
        rect = pygame.Rect(self.size[0]-176, 16, 160, 160)
        scale = 160/(2*LIMIT+170)
        if self._minimap is None:
            self._minimap = pygame.Surface((160, 160))
            self._minimap.fill('#b3c59f')
            for block in self._city['blocks']:
                pygame.draw.rect(self._minimap, block['color'],
                                 (80+block['x']*scale, 80+block['y']*scale,
                                  max(1, block['length']*scale), max(1, block['width']*scale)))
            for road in self._city['roads']:
                pygame.draw.rect(self._minimap, '#e2e4cd',
                                 (80+road['x']*scale, 80+road['y']*scale,
                                  max(1, road['length']*scale), max(1, road['width']*scale)))
        screen.blit(self._minimap, rect)
        p = observation['car']
        pygame.draw.circle(screen, '#273e36', (rect.centerx+p['x']*scale, rect.centery+p['y']*scale), 3)
