"""Preview backend and Windows SendInput adapter (no external automation lib)."""
from collections import deque
import ctypes
import logging
import sys


class PreviewBackend:
    def __init__(self, width=1920, height=1080):
        self.width, self.height = width, height
        self.events = deque(maxlen=2000)
        self.position = (width//2, height//2)
        self.left_held = False
        self.alt_held = False

    def emit(self, name, *args):
        self.events.append((name, *args))
        if name != "move":
            logging.info("PREVIEW %s %s", name, args or "")

    def move(self, x, y):
        self.position = (round(x*(self.width-1)), round(y*(self.height-1)))
        self.emit("move", *self.position)

    def left_down(self):
        self.left_held = True
        self.emit("left_down")

    def left_up(self):
        if self.left_held:
            self.emit("left_up")
        self.left_held = False

    def click(self):
        self.emit("click")

    def right_click(self):
        self.emit("right_click")

    def scroll(self, steps):
        self.emit("scroll", steps)

    def alt_start(self):
        self.alt_held = True
        self.emit("alt_start")

    def alt_step(self, direction):
        self.emit("alt_step", direction)

    def alt_end(self):
        if self.alt_held:
            self.emit("alt_end")
        self.alt_held = False

    def snip(self):
        self.emit("snip")

    def release_all(self):
        self.left_up()
        self.alt_end()


class WindowsBackend:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("Real input requires Windows. Use preview mode on this OS.")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        try:
            self.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except AttributeError:
            self.user32.SetProcessDPIAware()
        self.width = self.user32.GetSystemMetrics(0)
        self.height = self.user32.GetSystemMetrics(1)
        self.left_held = self.alt_held = False
        self.keys = set()
        self._define_input()

    def _define_input(self):
        class Mouse(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32),
                        ("mouseData", ctypes.c_uint32), ("dwFlags", ctypes.c_uint32),
                        ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]

        class Keyboard(ctypes.Structure):
            _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16),
                        ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class Hardware(ctypes.Structure):
            _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_uint16),
                        ("wParamH", ctypes.c_uint16)]

        class Union(ctypes.Union):
            _fields_ = [("mi", Mouse), ("ki", Keyboard), ("hi", Hardware)]

        class Input(ctypes.Structure):
            _anonymous_ = ("payload",)
            _fields_ = [("type", ctypes.c_uint32), ("payload", Union)]

        self.Input, self.Mouse, self.Keyboard = Input, Mouse, Keyboard
        self.user32.SendInput.argtypes = (ctypes.c_uint32, ctypes.POINTER(Input), ctypes.c_int)
        self.user32.SendInput.restype = ctypes.c_uint32
        self.user32.SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)
        self.user32.SetCursorPos.restype = ctypes.c_int
        self.user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self.user32.GetAsyncKeyState.restype = ctypes.c_short

    def _send(self, event):
        if self.user32.SendInput(1, ctypes.byref(event), ctypes.sizeof(self.Input)) != 1:
            raise OSError(ctypes.get_last_error(), "SendInput failed; check foreground-app permissions")

    def _mouse(self, flags, data=0):
        self._send(self.Input(type=0, mi=self.Mouse(mouseData=data & 0xffffffff, dwFlags=flags)))

    def _key(self, vk, down):
        # Track before injection so cleanup can release after a partial failure.
        if down:
            self.keys.add(vk)
        self._send(self.Input(type=1, ki=self.Keyboard(wVk=vk, dwFlags=0 if down else 2)))
        if not down:
            self.keys.discard(vk)

    def _tap(self, vk):
        try:
            self._key(vk, True)
        finally:
            self._key(vk, False)

    def move(self, x, y):
        if not self.user32.SetCursorPos(round(x*(self.width-1)), round(y*(self.height-1))):
            raise OSError(ctypes.get_last_error(), "SetCursorPos failed")

    def left_down(self):
        self.left_held = True
        self._mouse(0x0002)

    def left_up(self):
        if self.left_held:
            self._mouse(0x0004)
            self.left_held = False

    def click(self):
        try:
            self.left_down()
        finally:
            self.left_up()

    def right_click(self):
        try:
            self._mouse(0x0008)
        finally:
            self._mouse(0x0010)

    def scroll(self, steps):
        self._mouse(0x0800, steps*120)

    def alt_start(self):
        self.alt_held = True
        self._key(0x12, True)
        self._tap(0x09)

    def alt_step(self, direction):
        if direction < 0:
            try:
                self._key(0x10, True)
                self._tap(0x09)
            finally:
                self._key(0x10, False)
        else:
            self._tap(0x09)

    def alt_end(self):
        if self.alt_held:
            self._key(0x12, False)
            self.alt_held = False

    def snip(self):
        try:
            self._key(0x5B, True)
            self._key(0x10, True)
            self._tap(0x53)
        finally:
            # release_all will retry each outstanding key if either call fails.
            try:
                self._key(0x10, False)
            finally:
                self._key(0x5B, False)

    def key_pressed(self, vk):
        return bool(self.user32.GetAsyncKeyState(vk) & 0x8000)

    def release_all(self):
        errors = []
        try:
            self.left_up()
        except OSError as exc:
            errors.append(exc)
        for vk in list(self.keys):
            try:
                self._key(vk, False)
            except OSError as exc:
                errors.append(exc)
        self.alt_held = 0x12 in self.keys
        if errors:
            raise errors[0]
