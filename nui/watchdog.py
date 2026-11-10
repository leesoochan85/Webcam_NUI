"""Release held input if the camera/inference loop stalls."""
import logging
from threading import Event, RLock, Thread
from time import monotonic


class InputGuard:
    ACTIONS = {"move", "left_down", "left_up", "click", "right_click", "scroll",
               "alt_start", "alt_step", "alt_end", "snip"}

    def __init__(self, backend, timeout=1.5, clock=monotonic):
        self.backend, self.timeout, self.clock = backend, timeout, clock
        self.lock, self.stop_event = RLock(), Event()
        self.last_heartbeat = clock()
        self.tripped = False
        self.thread = None

    def __getattr__(self, name):
        target = getattr(self.backend, name)
        if name not in self.ACTIONS:
            return target

        def guarded(*args, **kwargs):
            with self.lock:
                if self.tripped:
                    raise RuntimeError("Input watchdog stopped control after a stalled frame")
                return target(*args, **kwargs)
        return guarded

    def heartbeat(self):
        with self.lock:
            if self.tripped:
                raise RuntimeError("Input watchdog stopped control; restart the program")
            self.last_heartbeat = self.clock()

    def tick(self):
        with self.lock:
            if self.clock()-self.last_heartbeat > self.timeout and not self.tripped:
                self.tripped = True
                logging.error("Frame loop stalled; releasing held input")
                self.backend.release_all()

    def start(self):
        self.last_heartbeat = self.clock()

        def monitor():
            while not self.stop_event.wait(0.05):
                try:
                    self.tick()
                except OSError:
                    logging.exception("Input release failed; retrying")
                    try:
                        self.release_all()
                    except OSError:
                        logging.exception("Input cleanup retry failed")
        self.thread = Thread(target=monitor, daemon=True, name="nui-input-watchdog")
        self.thread.start()

    def release_all(self):
        with self.lock:
            self.backend.release_all()

    def close(self):
        self.stop_event.set()
        if self.thread is not None:
            self.thread.join(timeout=0.3)
        self.release_all()
