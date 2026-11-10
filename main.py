"""Windows webcam NUI. Default: camera preview, no OS input."""
import argparse
from collections import deque
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
from time import monotonic

from download_model import DEFAULT_MODEL, valid_model
from nui.backend import PreviewBackend, WindowsBackend
from nui.config import Config
from nui.engine import Engine
from nui.gestures import Classifier
from nui.watchdog import InputGuard

ROOT = Path(__file__).resolve().parent
WINDOW = "Webcam NUI"
CONNECTIONS = ((0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),
               (5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),
               (15,16),(13,17),(0,17),(17,18),(18,19),(19,20))


def setup_logging():
    (ROOT / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), RotatingFileHandler(
                            ROOT/"logs"/"nui.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")])


def draw(cv, frame, landmarks, obs, engine, fps, live, config):
    h, w = frame.shape[:2]
    m = config.edge_margin
    cv.rectangle(frame, (int(w*m), int(h*m)), (int(w*(1-m)), int(h*(1-m))), (195, 200, 210), 1)
    if landmarks:
        xy = [(int(p.x*w), int(p.y*h)) for p in landmarks]
        for a, b in CONNECTIONS:
            cv.line(frame, xy[a], xy[b], (80, 210, 140), 2)
        for p in xy:
            cv.circle(frame, p, 4, (80, 225, 245), -1)
        cv.circle(frame, xy[8], 10, (0, 220, 255), 2)
    # Mini desktop shows the mapped cursor even in preview mode.
    rx, ry, rw, rh = w-190, h-125, 170, 95
    cv.rectangle(frame, (rx, ry), (rx+rw, ry+rh), (225, 225, 225), 1)
    if engine.pointer.value:
        x, y = engine.pointer.value
        cv.circle(frame, (rx+int(x*rw), ry+int(y*rh)), 5, (0, 220, 255), -1)
    cv.rectangle(frame, (0, 0), (w, 133), (28, 31, 38), -1)
    color = (90, 225, 140) if engine.enabled else (100, 170, 255)
    lines = [f"{'LIVE' if live else 'PREVIEW - no OS input'} | {engine.mode} | {fps:.0f} FPS",
             f"Pose: {obs.pose.value if obs else 'NO HAND'}",
             engine.status,
             "F8: ON/OFF | F10: quit | P / Q / Esc: preview window keys"]
    if engine.pointer.waiting:
        lines[2] = "Return from same edge (3 s limit); pointer is frozen"
    for i, line in enumerate(lines):
        cv.putText(frame, line, (14, 27+i*29), cv.FONT_HERSHEY_SIMPLEX, 0.56,
                   color if i == 0 else (230, 233, 240), 1, cv.LINE_AA)


def run(args):
    config = Config.load(args.config)
    if args.camera is not None:
        from dataclasses import replace
        config = replace(config, camera_index=args.camera).validate()
    if not valid_model(args.model):
        raise RuntimeError("Model missing/corrupt. Run setup_windows.bat or python download_model.py")
    try:
        import cv2 as cv
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError("Dependencies missing. Run setup_windows.bat first.") from exc

    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    backend = WindowsBackend() if args.live else PreviewBackend()
    guard = InputGuard(backend)
    engine = Engine(config, guard, enabled=not args.live)
    classifier = Classifier(config)
    # Preview mode still supports global hotkeys on Windows without injecting input.
    hotkeys = backend if args.live else (WindowsBackend() if sys.platform == "win32" else None)
    camera = landmarker = None
    try:
        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(args.model.resolve())),
            running_mode=vision.RunningMode.VIDEO, num_hands=1,
            min_hand_detection_confidence=config.detection_confidence,
            min_hand_presence_confidence=config.detection_confidence,
            min_tracking_confidence=config.tracking_confidence)
        landmarker = vision.HandLandmarker.create_from_options(options)
        camera = cv.VideoCapture(config.camera_index, cv.CAP_DSHOW if sys.platform == "win32" else cv.CAP_ANY)
        if not camera.isOpened() and sys.platform == "win32":
            camera.release()
            camera = cv.VideoCapture(config.camera_index, cv.CAP_MSMF)
        if not camera.isOpened():
            raise RuntimeError(f"Cannot open camera {config.camera_index}; check Windows camera permission / other apps")
        camera.set(cv.CAP_PROP_FRAME_WIDTH, config.camera_width)
        camera.set(cv.CAP_PROP_FRAME_HEIGHT, config.camera_height)
        camera.set(cv.CAP_PROP_BUFFERSIZE, 1)
        cv.namedWindow(WINDOW, cv.WINDOW_NORMAL)
        cv.resizeWindow(WINDOW, config.camera_width, config.camera_height)
        guard.start()
        pressed = {}
        last_stamp = -1
        frames = deque(maxlen=30)
        logging.info("Started %s; camera=%s", "LIVE (paused)" if args.live else "PREVIEW", config.camera_index)
        while True:
            guard.heartbeat()
            if hotkeys:
                for vk in (0x77, 0x79):  # F8, F10; rising edges only
                    current = hotkeys.key_pressed(vk)
                    if current and not pressed.get(vk, False):
                        if vk == 0x79:
                            return
                        engine.set_enabled(not engine.enabled)
                        classifier.reset()
                    pressed[vk] = current
            ok, frame = camera.read()
            if not ok or frame is None:
                raise RuntimeError("Camera stopped delivering frames; held input released")
            now = monotonic()
            if config.mirror:
                frame = cv.flip(frame, 1)
            rgb = cv.cvtColor(frame, cv.COLOR_BGR2RGB)
            stamp = max(last_stamp+1, int(now*1000))
            last_stamp = stamp
            result = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), stamp)
            points = result.hand_landmarks[0] if result.hand_landmarks else None
            if points:
                obs = classifier.classify(points, frame.shape[1], frame.shape[0])
            else:
                obs = None
                classifier.reset()
            engine.update(obs, monotonic())
            guard.heartbeat()
            frames.append(now)
            fps = (len(frames)-1)/(frames[-1]-frames[0]) if len(frames)>1 and frames[-1]>frames[0] else 0
            draw(cv, frame, points, obs, engine, fps, args.live, config)
            cv.imshow(WINDOW, frame)
            key = cv.waitKey(1) & 0xff
            if key in (27, ord("q")) or cv.getWindowProperty(WINDOW, cv.WND_PROP_VISIBLE) < 1:
                return
            if key == ord("p"):
                engine.set_enabled(not engine.enabled)
                classifier.reset()
    finally:
        # Release input before potentially slow camera/model cleanup.
        try:
            guard.close()
        finally:
            if camera is not None:
                camera.release()
            if landmarker is not None:
                landmarker.close()
            cv.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Windows mouse/keyboard control; starts PAUSED")
    parser.add_argument("--camera", type=int, help="override camera index (0, 1, ...)")
    parser.add_argument("--config", type=Path, default=ROOT/"config.json")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    args = parser.parse_args()
    setup_logging()
    try:
        run(args)
    except KeyboardInterrupt:
        logging.info("Stopped by keyboard")
    except Exception:
        logging.exception("NUI stopped")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
