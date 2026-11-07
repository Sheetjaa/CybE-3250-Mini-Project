"""Pygame isometric renderer; recording receives only the world surface."""
import math
import pygame
from scene_labels import corners
from simulation import CELL, ROAD, LIMIT, clamp


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

    def project(self, x, y, z=0):
        dx, dy = x-self.camera['x'], y-self.camera['y']
        return ((dx-dy)*.866*self.zoom+self.size[0]*.5,
                (dx+dy)*.5*self.zoom-z*self.zoom+self.size[1]*.49)

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

    def car(self, obj, color, roof):
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

    def draw(self, observation, model):
        self.camera = observation['camera']
        observation['camera']['zoom'] = self.zoom
        observation['viewport'] = dict(width=self.size[0], height=self.size[1], projection='isometric')
        self.surface.fill('#b6c79f')
        self.rect(-LIMIT-95, -LIMIT-95, LIMIT*2+190, LIMIT*2+190, '#a9bc96')
        for i in range(-5, 6):
            self.rect(i*CELL-ROAD/2-10, -LIMIT-55, ROAD+20, LIMIT*2+110, '#d8d8be')
            self.rect(-LIMIT-55, i*CELL-ROAD/2-10, LIMIT*2+110, ROAD+20, '#d8d8be')
        for i in range(-5, 6):
            self.rect(i*CELL-ROAD/2, -LIMIT-44, ROAD, LIMIT*2+88, '#87958a')
            self.rect(-LIMIT-44, i*CELL-ROAD/2, LIMIT*2+88, ROAD, '#87958a')
        for i in range(-5, 6):
            for j in range(-5, 5):
                for n in range(75, 260, 39):
                    self.rect(i*CELL-1, j*CELL+n, 2, 16, '#d7dac1')
                    self.rect(j*CELL+n, i*CELL-1, 16, 2, '#d7dac1')
                for k in range(-27, 30, 12):
                    self.rect(i*CELL+k, j*CELL+48, 7, 10, '#d9ddc3')
                    self.rect(j*CELL+48, i*CELL+k, 10, 7, '#d9ddc3')
        self.rect(66, 68, 177, 177, '#9db585')
        self.rect(66, 149, 177, 12, '#d3d2b5')
        self.rect(149, 68, 12, 177, '#d3d2b5')
        objects = observation['world']['objects']
        for obj in objects:
            projected = [self.project(x, y, z) for x, y in corners(obj)
                         for z in [0, obj['height']]]
            xs, ys = [p[0] for p in projected], [p[1] for p in projected]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            width, height = self.size
            visible = obj['active'] and x1 > 0 and y1 > 0 and x0 < width and y0 < height
            obj['bbox_normalized'] = (dict(x_min=max(0, x0)/width, y_min=max(0, y0)/height,
                                          x_max=min(width, x1)/width, y_max=min(height, y1)/height)
                                      if visible else None)

        for o in objects:
            if o['type'] == 'skid':
                pygame.draw.line(self.surface, '#66765f', self.project(o['x'], o['y']), self.project(o['x2'], o['y2']), 2)
        player = dict(observation['car'], id='player', type='player', active=True)
        for o in sorted([*objects, player], key=lambda o: o['x']+o['y']):
            if not o['active'] or o['type'] == 'skid':
                continue
            x, y = self.project(o['x'], o['y'])
            if x < -160 or x > self.size[0]+160 or y < -160 or y > self.size[1]+200:
                continue
            kind = o['type']
            if kind == 'building':
                self.box(o, o['color'], o['roof'])
                self.box(dict(o, length=o['length']-10, width=o['width']-10, height=2),
                         o['roof'], o['roof'], z=o['height'])
                # Windows on both camera-facing walls.
                for z in range(10, int(o['height'])-10, 16):
                    for dx in range(12, int(o['length'])-8, 19):
                        self.rect(o['x']-o['length']/2+dx, o['y']+o['width']/2+.1, 7, .8, '#7e9690', z)
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
                         model['roof'] if kind == 'player' else shade(o['color'], 1.07))
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
                 'B: bot   F9: record   T: traffic   G: detection zones   1/2/3: car',
                 f'{"BOT" if bot else "MANUAL"}   {"PAUSED" if paused else "DRIVING"}   {"RECORDING" if recording else ""}']
        for i, line in enumerate(lines):
            screen.blit(self.font.render(line, True, '#f5f3e9', '#273e36'), (16, 16+i*25))
        # Minimap is drawn only on the display, never into recorded images.
        rect = pygame.Rect(self.size[0]-176, 16, 160, 160)
        pygame.draw.rect(screen, '#b3c59f', rect)
        scale = 160/(2*LIMIT+170)
        for i in range(-5, 6):
            pygame.draw.line(screen, '#e2e4cd', (rect.centerx+i*CELL*scale, rect.top),
                             (rect.centerx+i*CELL*scale, rect.bottom), max(1, round(ROAD*scale)))
            pygame.draw.line(screen, '#e2e4cd', (rect.left, rect.centery+i*CELL*scale),
                             (rect.right, rect.centery+i*CELL*scale), max(1, round(ROAD*scale)))
        p = observation['car']
        pygame.draw.circle(screen, '#273e36', (rect.centerx+p['x']*scale, rect.centery+p['y']*scale), 3)
