"""Replace BasicBot with a model implementing Policy.act(observation) -> Action.

Policies receive the same full observation written to the recorder, before the
selected action is applied. No pygame import is needed for state-based training.
"""
import math
from typing import Protocol
from simulation import Action, CELL, LIMIT, clamp


class Policy(Protocol):
    def act(self, observation: dict) -> Action: ...


class BasicBot:
    """Follow a clockwise square on the road grid; brake for nearby traffic.

    Uses right-side lanes and pure pursuit. This is a demonstration policy, not
    a route planner: starting far off the route may require a manual reset.
    """
    CRUISE_SPEED = 120  # World units/s; the HUD displays this as about 58 km/h.
    TURN_SPEED = 45

    def __init__(self):
        self.route = [(20, -CELL+20), (CELL-20, -CELL+20),
                      (CELL-20, CELL-20), (20, CELL-20)]
        self.target = 0
        self.segment = None

    def act(self, observation):
        if observation['segment'] != self.segment:
            self.target = 0
            self.segment = observation['segment']
        p = observation['car']
        tx, ty = self.route[self.target]
        if math.hypot(tx-p['x'], ty-p['y']) < 45:
            self.target = (self.target+1) % len(self.route)
            tx, ty = self.route[self.target]
        dx, dy = tx-p['x'], ty-p['y']
        error = math.atan2(math.sin(math.atan2(dy, dx)-p['a']), math.cos(math.atan2(dy, dx)-p['a']))
        speed = math.hypot(p['vx'], p['vy'])
        target_speed = self.CRUISE_SPEED if abs(error) < .3 else self.TURN_SPEED
        clearance = max(40, speed*.9)
        for o in observation['world']['objects']:
            q = o['relative_center']
            if o['solid'] and o['active'] and 0 < q['forward'] < clearance and abs(q['right']) < 22:
                target_speed = min(target_speed, max(0, (q['forward']-30)*.8))
        if abs(p['x']) > LIMIT-70 or abs(p['y']) > LIMIT-70:
            target_speed = 0
        return Action(accelerate=speed < target_speed-3,
                      brake_reverse=speed > target_speed+4 and speed > 5,
                      steering=clamp(error*1.8, -1, 1))
