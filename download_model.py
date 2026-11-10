"""Fetch Google's versioned Hand Landmarker bundle; standard library only."""
import argparse
import hashlib
from pathlib import Path
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
             "hand_landmarker/float16/1/hand_landmarker.task")
DEFAULT_MODEL = ROOT / "models" / "hand_landmarker.task"
REQUIRED = {"hand_detector.tflite", "hand_landmarks_detector.tflite"}


def valid_model(path):
    try:
        with zipfile.ZipFile(path) as archive:
            return REQUIRED.issubset(archive.namelist()) and archive.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def download(path=DEFAULT_MODEL, force=False):
    path = Path(path)
    if not force and valid_model(path):
        print(f"Model ready: {path}")
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".download")
    try:
        print("Downloading official Hand Landmarker (float16/version 1)...")
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "WebcamNUI/0.1"})
        with urllib.request.urlopen(request, timeout=45) as response, temporary.open("wb") as output:
            total = 0
            while chunk := response.read(1024*1024):
                total += len(chunk)
                if total > 30*1024*1024:
                    raise ValueError("Unexpected model size")
                output.write(chunk)
        if not valid_model(temporary):
            raise ValueError("Downloaded file is not a valid Hand Landmarker bundle")
        temporary.replace(path)
        print(f"Model ready: {path}")
        print("SHA256:", hashlib.sha256(path.read_bytes()).hexdigest())
        return path
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        download(force=args.force)
    except (OSError, ValueError) as exc:
        print(f"Model download failed: {exc}\nManual URL: {MODEL_URL}\nSave as: {DEFAULT_MODEL}", file=sys.stderr)
        raise SystemExit(1)
