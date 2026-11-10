from dataclasses import replace
import unittest
from nui.config import Config
from nui.gestures import Classifier, Point, Pose
from nui.pointer import Pointer


def hand(up=(True, False, False, False), thumb_open=True):
    p = [Point(0.5, 0.9) for _ in range(21)]
    p[1:5] = [Point(0.34, 0.76), Point(0.28, 0.65), Point(0.21, 0.52), Point(0.13, 0.39)]
    for base, x, raised in zip((5, 9, 13, 17), (0.4, 0.48, 0.56, 0.64), up):
        p[base] = Point(x, 0.63)
        if raised:
            p[base+1:base+4] = [Point(x, 0.47), Point(x, 0.32), Point(x, 0.20)]
        else:
            p[base+1:base+4] = [Point(x, 0.53), Point(x, 0.65), Point(x, 0.73)]
    if not thumb_open:
        p[4] = Point(0.42, 0.72)
    return p


class GeometryTests(unittest.TestCase):
    def setUp(self):
        self.classifier = Classifier(Config())

    def classify(self, p):
        return self.classifier.classify(p, 960, 540).pose

    def test_point(self):
        self.assertEqual(self.classify(hand()), Pose.POINT)

    def test_open(self):
        self.assertEqual(self.classify(hand((True,)*4)), Pose.OPEN)

    def test_fist_not_pinch(self):
        self.assertEqual(self.classify(hand((False,)*4, False)), Pose.FIST)

    def test_scroll(self):
        self.assertEqual(self.classify(hand((True, True, False, False))), Pose.SCROLL)

    def test_pinky_toggle(self):
        self.assertEqual(self.classify(hand((False, False, False, True))), Pose.TOGGLE)

    def test_left_pinch_hysteresis(self):
        p = hand()
        p[4] = Point(p[8].x+0.04, p[8].y)
        self.assertEqual(self.classify(p), Pose.LEFT_PINCH)
        p[4] = Point(p[8].x+0.09, p[8].y)
        self.assertEqual(self.classify(p), Pose.LEFT_PINCH)
        self.classifier.reset()
        self.assertEqual(self.classify(p), Pose.POINT)
        p[4] = Point(p[8].x+0.15, p[8].y)
        self.assertEqual(self.classify(p), Pose.POINT)

    def test_right_pinch(self):
        p = hand((True, True, False, False))
        p[4] = Point(p[12].x+0.02, p[12].y)
        self.assertEqual(self.classify(p), Pose.RIGHT_PINCH)

    def test_mirrored_geometry_preserves_pose(self):
        p = hand((True,)*4)
        self.assertEqual(self.classify([Point(1-v.x, v.y) for v in p]), Pose.OPEN)

    def test_scaled_image_preserves_pose(self):
        p = hand((True,)*4)
        a = self.classifier.classify(p, 960, 540)
        b = self.classifier.classify(p, 1920, 1080)
        self.assertEqual(a.pose, b.pose)

    def test_landmark_count(self):
        with self.assertRaises(ValueError):
            self.classify([])


class PointerTests(unittest.TestCase):
    def test_mapping_bounds(self):
        p = Pointer(Config())
        self.assertEqual(p.mapped(-1, 2), (0.0, 1.0))
        self.assertEqual(p.mapped(0.5, 0.5), (0.5, 0.5))

    def test_same_edge_required_then_continuous_resume(self):
        p = Pointer(Config())
        previous = p.update(0.02, 0.5, 0)
        p.mark_lost(0.1)
        self.assertIsNone(p.update(0.7, 0.5, 0.2))
        self.assertTrue(p.waiting)
        resumed = p.update(0.03, 0.5, 0.3)
        self.assertEqual(previous, resumed)
        self.assertFalse(p.waiting)

    def test_edge_wait_times_out(self):
        p = Pointer(Config())
        p.update(0.02, 0.5, 0)
        p.mark_lost(0.1)
        self.assertIsNotNone(p.update(0.5, 0.5, 3.5))

    def test_occlusion_in_center_does_not_require_edge(self):
        p = Pointer(Config())
        value = p.update(0.5, 0.5, 0)
        p.mark_lost(0.1)
        self.assertEqual(value, p.update(0.7, 0.5, 0.2))

    def test_smoothing_is_time_based(self):
        def simulate(dt):
            p = Pointer(Config())
            p.update(0.5, 0.5, 0)
            for i in range(1, round(0.2/dt)+1):
                p.update(0.8, 0.5, i*dt)
            return p.value[0]
        self.assertAlmostEqual(simulate(0.02), simulate(0.04), places=5)


class ConfigTests(unittest.TestCase):
    def test_defaults_valid(self):
        Config().validate()

    def test_bad_pinch_order(self):
        with self.assertRaises(ValueError):
            replace(Config(), pinch_close=0.6, pinch_open=0.4).validate()

    def test_nan_rejected(self):
        with self.assertRaises(ValueError):
            replace(Config(), alt_hold=float("nan")).validate()

    def test_zero_scroll_rejected(self):
        with self.assertRaises(ValueError):
            replace(Config(), scroll_step=0).validate()

    def test_bool_camera_index_rejected(self):
        with self.assertRaises(ValueError):
            replace(Config(), camera_index=True).validate()


if __name__ == "__main__":
    unittest.main()
