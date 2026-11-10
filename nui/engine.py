"""One state machine owns gesture priority and every held input."""
import logging
from math import hypot
from .config import Config
from .gestures import Observation, Pose
from .pointer import Pointer


class Engine:
    def __init__(self, config: Config, backend, enabled=False):
        self.c, self.backend = config, backend
        self.pointer = Pointer(config)
        self.enabled = enabled
        self.mode = "NORMAL" if enabled else "PAUSED"
        self.status = "Point your index finger" if enabled else "F8 or pinky hold to enable"
        self.candidate = self.stable = None
        self.candidate_since = 0.0
        self.previous = None
        self.missing_since = None
        self.last_update = None
        self.capture_stage = 0
        self.capture_deadline = 0.0
        self.capture_ready = 0.0
        self.snipping_until = 0.0
        self.alt_origin = 0.0
        self.alt_step_at = 0.0
        self.alt_ready = True
        self.toggle_fired = False
        self.pinch_start = None
        self.pinch_anchor = None
        self.dragging = False
        self.require_release = False
        self.right_fired = False
        self.click_ready = 0.0
        self.scroll_y = None

    def _note(self, message):
        self.status = message
        logging.info(message)

    def _cancel_pinch(self):
        self.backend.left_up()
        self.pinch_start = self.pinch_anchor = None
        self.dragging = False

    def set_enabled(self, enabled):
        self.backend.release_all()
        self.enabled = enabled
        self.mode = "NORMAL" if enabled else "PAUSED"
        self.capture_stage = 0
        self.pinch_start = self.pinch_anchor = None
        self.dragging = False
        self.require_release = True
        self.alt_ready = False
        self.scroll_y = None
        self.pointer.reset()
        self._note("NUI ON - show index finger" if enabled else "NUI PAUSED")

    def close(self):
        self.backend.release_all()

    def update(self, obs: Observation | None, now: float):
        if self.last_update is not None and now < self.last_update:
            raise ValueError("timestamps must not go backwards")
        if self.last_update is not None and now-self.last_update > self.c.lost_timeout:
            self._missing(self.last_update)
            self._missing(now)
        self.last_update = now
        if obs is None:
            self._missing(now)
            return
        self.missing_since = None
        pose = obs.pose
        if pose != self.candidate:
            self.candidate, self.candidate_since = pose, now
            self.toggle_fired = False
        if now-self.candidate_since < self.c.pose_debounce:
            # Freeze output during transitions; never continue a stale action.
            return
        self.stable = pose
        changed = pose != self.previous
        self.previous = pose

        if pose == Pose.TOGGLE:
            self._cancel_pinch()
            if not self.toggle_fired and now-self.candidate_since >= self.c.toggle_hold:
                self.set_enabled(not self.enabled)
                self.toggle_fired = True
            return
        if not self.enabled:
            return

        if self.require_release:
            if pose in (Pose.LEFT_PINCH, Pose.RIGHT_PINCH):
                return
            self.require_release = False

        if self.mode == "ALT_TAB":
            if pose == Pose.LEFT_PINCH:
                self.backend.alt_end()
                self.mode = "NORMAL"
                self.alt_ready = False
                self.require_release = True
                self._note("Window selected")
            elif pose == Pose.OPEN:
                delta = obs.palm_x-self.alt_origin
                if abs(delta) >= self.c.alt_step_distance and now-self.alt_step_at >= self.c.alt_step_cooldown:
                    self.backend.alt_step(1 if delta > 0 else -1)
                    self.alt_origin, self.alt_step_at = obs.palm_x, now
                    self._note("Next window" if delta > 0 else "Previous window")
            return

        if self.mode == "SNIPPING":
            if now >= self.snipping_until:
                self._cancel_pinch()
                self.mode = "NORMAL"
                self.alt_ready = False
                self.require_release = True
                self._note("Capture gesture mode ended")
                return
            else:
                self._pointer_actions(obs, now, capture=True)
                return

        if self.capture_stage and now > self.capture_deadline:
            self.capture_stage = 0
            self.alt_ready = False
            self._note("Capture pattern expired")
        if self.capture_stage:
            if changed:
                expected = {1: Pose.OPEN, 2: Pose.FIST, 3: Pose.OPEN}[self.capture_stage]
                if pose == expected:
                    self.capture_stage += 1
                    if self.capture_stage == 4:
                        self.capture_stage = 0
                        self.capture_ready = now+self.c.capture_cooldown
                        self._cancel_pinch()
                        self.backend.snip()
                        self.mode = "SNIPPING"
                        self.snipping_until = now+self.c.snipping_timeout
                        self.alt_ready = False
                        self._note("Snipping Tool: point, pinch and drag a rectangle")
                    else:
                        self._note(f"Capture pattern {self.capture_stage}/4")
                elif pose not in (Pose.OPEN, Pose.FIST, Pose.OTHER):
                    self.capture_stage = 0
            if self.capture_stage or self.mode == "SNIPPING":
                return
        if changed and pose == Pose.FIST and now >= self.capture_ready:
            self._cancel_pinch()
            self.scroll_y = None
            self.capture_stage = 1
            self.alt_ready = False
            self.capture_deadline = now+self.c.capture_timeout
            self._note("Capture pattern 1/4: open, fist, open")
            return

        if pose != Pose.OPEN:
            self.alt_ready = True
        elif self.alt_ready and now-self.candidate_since >= self.c.alt_hold:
            self._cancel_pinch()
            self.scroll_y = None
            self.backend.alt_start()
            self.mode = "ALT_TAB"
            self.alt_origin, self.alt_step_at = obs.palm_x, now
            self._note("Alt+Tab: move palm sideways; pinch to select")
            return
        self._pointer_actions(obs, now)

    def _pointer_actions(self, obs, now, capture=False):
        pose = obs.pose
        if pose != Pose.LEFT_PINCH and self.pinch_start is not None:
            if self.dragging:
                self.backend.left_up()
                self._note("Drag released")
                if capture:
                    self.mode = "NORMAL"
                    self.alt_ready = False
            elif pose == Pose.POINT and now >= self.click_ready:
                self.backend.click()
                self._note("Left click")
            self.pinch_start = self.pinch_anchor = None
            self.dragging = False
            self.click_ready = now+self.c.click_cooldown

        if pose in (Pose.POINT, Pose.LEFT_PINCH):
            pos = self.pointer.update(obs.x, obs.y, now)
            if pos is None:
                self._cancel_pinch()
                self.require_release = True
                self.status = "Return hand from the same screen edge"
                return
            if pose == Pose.POINT:
                self.backend.move(*pos)
            else:
                if self.pinch_start is None:
                    self.pinch_start = now
                    self.pinch_anchor = pos
                dx = (pos[0]-self.pinch_anchor[0])*self.backend.width
                dy = (pos[1]-self.pinch_anchor[1])*self.backend.height
                if not self.dragging and (now-self.pinch_start >= self.c.drag_hold or hypot(dx, dy) >= self.c.drag_distance_px):
                    self.backend.left_down()
                    self.dragging = True
                    self._note("Dragging")
                if self.dragging:
                    self.backend.move(*pos)

        if pose != Pose.RIGHT_PINCH:
            self.right_fired = False
        elif not capture and not self.right_fired and now >= self.click_ready:
            self.backend.right_click()
            self.right_fired = True
            self.click_ready = now+self.c.click_cooldown
            self._note("Right click")

        if pose != Pose.SCROLL or capture:
            self.scroll_y = None
        elif self.scroll_y is None:
            self.scroll_y = obs.palm_y
        else:
            delta = self.scroll_y-obs.palm_y
            steps = int(delta/self.c.scroll_step)
            if steps:
                # Bound individual bursts; consume measured distance to avoid backlog.
                self.backend.scroll(max(-5, min(5, -steps if self.c.scroll_invert else steps)))
                self.scroll_y -= steps*self.c.scroll_step
                self._note("Scrolling")

    def _missing(self, now):
        frozen = self.pointer.mark_lost(now)
        if frozen is not None and self.enabled and self.mode in ("NORMAL", "SNIPPING"):
            self.backend.move(*frozen)
        self._cancel_pinch()  # Never turn a tracking loss into a click.
        self.capture_stage = 0
        self.scroll_y = None
        self.require_release = True
        self.right_fired = False
        self.candidate = self.stable = self.previous = None
        self.toggle_fired = False
        if self.missing_since is None:
            self.missing_since = now
        if self.mode == "ALT_TAB" and now-self.missing_since >= self.c.lost_timeout:
            self.backend.alt_end()
            self.mode = "NORMAL"
            self.alt_ready = False
            self._note("Hand lost: Alt released, highlighted window selected")
