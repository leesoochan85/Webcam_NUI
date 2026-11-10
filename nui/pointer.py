"""Smoothed absolute mapping with same-edge hand re-entry."""
from math import exp
from .config import Config


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


class Pointer:
    def __init__(self, config: Config):
        self.c = config
        self.value = None
        self.at = None
        self.raw = None
        self.exit_edges = set()
        self.lost_at = None
        self.offset = (0.0, 0.0)
        self.waiting = False

    def reset(self):
        self.__init__(self.c)

    def mapped(self, x, y):
        m = self.c.edge_margin
        return clamp((x-m)/(1-2*m)), clamp((y-m)/(1-2*m))

    def mark_lost(self, now):
        if self.lost_at is not None or self.value is None or self.raw is None:
            return
        self.lost_at = now
        x, y = self.raw
        m = self.c.edge_margin + self.c.edge_reentry_band
        if x <= m:
            self.exit_edges.add("left")
        if x >= 1-m:
            self.exit_edges.add("right")
        if y <= m:
            self.exit_edges.add("top")
        if y >= 1-m:
            self.exit_edges.add("bottom")
        # When the fingertip left the active rectangle, pin the real cursor
        # exactly to that edge rather than leaving a smoothing gap.
        px, py = self.value
        if x <= self.c.edge_margin:
            px = 0.0
        elif x >= 1-self.c.edge_margin:
            px = 1.0
        if y <= self.c.edge_margin:
            py = 0.0
        elif y >= 1-self.c.edge_margin:
            py = 1.0
        self.value = px, py
        return self.value

    def update(self, x, y, now):
        mx, my = self.mapped(x, y)
        if self.lost_at is not None:
            band = self.c.edge_margin + self.c.edge_reentry_band
            valid = {"left": x <= band, "right": x >= 1-band,
                     "top": y <= band, "bottom": y >= 1-band}
            timed_out = now-self.lost_at >= self.c.edge_reentry_timeout
            if self.exit_edges and not timed_out and not all(valid[e] for e in self.exit_edges):
                self.waiting = True
                return None
            # Anchor to the last cursor location; decays while moving in-frame.
            self.offset = (self.value[0]-mx, self.value[1]-my)
            self.lost_at = None
            self.exit_edges.clear()
            self.at = now
            self.waiting = False
        dt = min(max(now-(self.at if self.at is not None else now), 0), 0.1)
        decay = exp(-dt/0.3)
        ox, oy = self.offset
        self.offset = (ox*decay, oy*decay)
        target = (clamp(mx+self.offset[0]), clamp(my+self.offset[1]))
        alpha = 1-exp(-dt/self.c.smoothing_tau)
        if self.value is None:
            self.value = target
        else:
            self.value = tuple(a+alpha*(b-a) for a, b in zip(self.value, target))
        self.at, self.raw = now, (x, y)
        return self.value
