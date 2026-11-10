from dataclasses import replace
import unittest

from nui.backend import PreviewBackend
from nui.config import Config
from nui.engine import Engine
from nui.gestures import Observation, Pose
from nui.watchdog import InputGuard


class Harness:
    def __init__(self, **changes):
        self.config = replace(Config(), **changes).validate()
        self.backend = PreviewBackend()
        self.engine = Engine(self.config, self.backend, enabled=True)
        self.now = 0.0

    def drive(self, pose, duration=0.18, x=0.5, y=0.5, palm_x=None, palm_y=None):
        obs = None if pose is None else Observation(pose, x, y,
                   x if palm_x is None else palm_x, y if palm_y is None else palm_y)
        count = max(1, round(duration/0.02))
        for _ in range(count):
            self.engine.update(obs, self.now)
            self.now += 0.02
        return self

    def events(self, name):
        return [e for e in self.backend.events if e[0] == name]


class EngineTests(unittest.TestCase):
    def test_short_pinch_clicks_once(self):
        h = Harness().drive(Pose.POINT).drive(Pose.LEFT_PINCH).drive(Pose.POINT)
        self.assertEqual(len(h.events("click")), 1)
        self.assertFalse(h.events("left_down"))

    def test_long_pinch_drags_then_releases_without_click(self):
        h = Harness().drive(Pose.POINT).drive(Pose.LEFT_PINCH, 0.6).drive(Pose.POINT)
        self.assertEqual(len(h.events("left_down")), 1)
        self.assertEqual(len(h.events("left_up")), 1)
        self.assertFalse(h.events("click"))

    def test_moving_pinch_starts_drag_before_hold(self):
        h = Harness().drive(Pose.POINT).drive(Pose.LEFT_PINCH, 0.12)
        h.drive(Pose.LEFT_PINCH, 0.12, x=0.65)
        self.assertTrue(h.backend.left_held)

    def test_hand_loss_releases_drag_immediately(self):
        h = Harness().drive(Pose.POINT).drive(Pose.LEFT_PINCH, 0.6)
        h.drive(None, 0.02)
        self.assertFalse(h.backend.left_held)
        self.assertFalse(h.events("click"))

    def test_hand_loss_cancels_pending_click(self):
        h = Harness().drive(Pose.POINT).drive(Pose.LEFT_PINCH).drive(None).drive(Pose.POINT)
        self.assertFalse(h.events("click"))

    def test_reacquire_pinched_hand_requires_release(self):
        h = Harness().drive(Pose.POINT).drive(None).drive(Pose.LEFT_PINCH, 0.8)
        self.assertFalse(h.events("left_down"))
        h.drive(Pose.POINT).drive(Pose.LEFT_PINCH, 0.6)
        self.assertTrue(h.backend.left_held)

    def test_right_pinch_one_click_per_hold(self):
        h = Harness().drive(Pose.RIGHT_PINCH, 1)
        self.assertEqual(len(h.events("right_click")), 1)
        h.drive(Pose.POINT).drive(Pose.RIGHT_PINCH)
        self.assertEqual(len(h.events("right_click")), 2)

    def test_v_scroll_has_no_click_or_cursor_movement(self):
        h = Harness().drive(Pose.SCROLL)
        h.drive(Pose.SCROLL, palm_y=0.35)
        self.assertTrue(h.events("scroll"))
        self.assertFalse(h.events("click"))
        self.assertFalse(h.events("move"))

    def test_scroll_up_and_inversion(self):
        for invert, sign in ((False, 1), (True, -1)):
            h = Harness(scroll_invert=invert).drive(Pose.SCROLL)
            h.drive(Pose.SCROLL, palm_y=0.4)
            self.assertEqual(h.events("scroll")[0][1]*sign > 0, True)

    def test_open_hold_enters_alt_once_and_steps_both_directions(self):
        h = Harness().drive(Pose.OPEN, 1.0)
        self.assertEqual(h.engine.mode, "ALT_TAB")
        h.drive(Pose.OPEN, 0.5, palm_x=0.7).drive(Pose.OPEN, 0.5, palm_x=0.3)
        self.assertEqual([v[1] for v in h.events("alt_step")], [1, -1])
        self.assertEqual(len(h.events("alt_start")), 1)

    def test_alt_pinch_select_does_not_click_or_drag(self):
        h = Harness().drive(Pose.OPEN, 1).drive(Pose.LEFT_PINCH, 0.7)
        self.assertFalse(h.backend.alt_held)
        self.assertEqual(h.engine.mode, "NORMAL")
        self.assertFalse(h.events("click"))
        self.assertFalse(h.events("left_down"))

    def test_alt_hand_loss_exits_after_grace(self):
        h = Harness().drive(Pose.OPEN, 1).drive(None, 0.1)
        self.assertTrue(h.backend.alt_held)
        h.drive(None, 0.4)
        self.assertFalse(h.backend.alt_held)

    def test_alt_long_frame_gap_releases_key(self):
        h = Harness().drive(Pose.OPEN, 1)
        h.now += 0.6
        h.drive(Pose.POINT)
        self.assertFalse(h.backend.alt_held)

    def test_capture_pattern_has_priority_over_alt(self):
        h = Harness().drive(Pose.FIST).drive(Pose.OPEN, 0.9)
        self.assertFalse(h.events("alt_start"))
        h.drive(Pose.FIST).drive(Pose.OPEN)
        self.assertEqual(len(h.events("snip")), 1)
        self.assertEqual(h.engine.mode, "SNIPPING")
        self.assertFalse(h.events("alt_start"))

    def test_incomplete_capture_cannot_auto_enter_alt(self):
        h = Harness().drive(Pose.FIST).drive(Pose.OPEN, 3.2)
        self.assertFalse(h.events("snip"))
        self.assertFalse(h.events("alt_start"))
        h.drive(Pose.POINT).drive(Pose.OPEN, 1)
        self.assertEqual(len(h.events("alt_start")), 1)

    def test_capture_loss_resets_sequence(self):
        h = Harness().drive(Pose.FIST).drive(Pose.OPEN).drive(None).drive(Pose.FIST).drive(Pose.OPEN)
        self.assertFalse(h.events("snip"))

    def test_snipping_supports_drag_and_suppresses_alt(self):
        h = Harness().drive(Pose.FIST).drive(Pose.OPEN).drive(Pose.FIST).drive(Pose.OPEN, 1)
        self.assertFalse(h.events("alt_start"))
        h.drive(Pose.POINT).drive(Pose.LEFT_PINCH, 0.6).drive(Pose.POINT)
        self.assertEqual(h.engine.mode, "NORMAL")
        self.assertFalse(h.backend.left_held)

    def test_capture_mode_timeout(self):
        h = Harness(snipping_timeout=0.5).drive(Pose.FIST).drive(Pose.OPEN).drive(Pose.FIST).drive(Pose.OPEN)
        h.drive(Pose.POINT, 0.8)
        self.assertEqual(h.engine.mode, "NORMAL")

    def test_pause_releases_held_input(self):
        h = Harness().drive(Pose.OPEN, 1)
        h.engine.set_enabled(False)
        self.assertFalse(h.backend.alt_held)
        h.drive(Pose.LEFT_PINCH, 1)
        self.assertFalse(h.events("left_down"))

    def test_toggle_hold_only_once_until_released(self):
        h = Harness().drive(Pose.TOGGLE, 2.5)
        self.assertFalse(h.engine.enabled)
        h.drive(Pose.POINT).drive(Pose.TOGGLE, 1.5)
        self.assertTrue(h.engine.enabled)

    def test_close_releases_all(self):
        h = Harness().drive(Pose.POINT).drive(Pose.LEFT_PINCH, 0.6)
        h.engine.close()
        self.assertFalse(h.backend.left_held)

    def test_brief_noise_is_not_a_gesture(self):
        h = Harness().drive(Pose.POINT).drive(Pose.LEFT_PINCH, 0.04).drive(Pose.POINT)
        self.assertFalse(h.events("click"))
        self.assertFalse(h.events("left_down"))

    def test_backward_timestamp_is_rejected(self):
        h = Harness().drive(Pose.POINT)
        with self.assertRaises(ValueError):
            h.engine.update(None, -1)


class WatchdogTests(unittest.TestCase):
    def test_stall_releases_input_and_blocks_later_actions(self):
        clock = [0.0]
        b = PreviewBackend()
        guard = InputGuard(b, timeout=1, clock=lambda: clock[0])
        guard.left_down()
        guard.alt_start()
        clock[0] = 1.1
        guard.tick()
        self.assertFalse(b.left_held)
        self.assertFalse(b.alt_held)
        with self.assertRaises(RuntimeError):
            guard.left_down()
        with self.assertRaises(RuntimeError):
            guard.heartbeat()
        guard.close()

    def test_heartbeat_prevents_trip(self):
        clock = [0.0]
        guard = InputGuard(PreviewBackend(), timeout=1, clock=lambda: clock[0])
        for t in (0.5, 1.0, 1.5):
            clock[0] = t
            guard.heartbeat()
            guard.tick()
        self.assertFalse(guard.tripped)


if __name__ == "__main__":
    unittest.main()
