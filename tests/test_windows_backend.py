"""Validate INPUT layout and event order using a fake user32, on any OS."""
import ctypes
import unittest
from unittest.mock import patch
from nui.backend import WindowsBackend


class Function:
    def __init__(self, result=1):
        self.result, self.calls = result, []

    def __call__(self, *args):
        self.calls.append(args)
        return self.result


def backend():
    b = WindowsBackend.__new__(WindowsBackend)
    class User32:
        SendInput = Function()
        SetCursorPos = Function()
        GetAsyncKeyState = Function(0)
    b.user32 = User32()
    b._define_input()
    b.width, b.height = 1920, 1080
    b.left_held = b.alt_held = False
    b.keys = set()
    b.captured = []
    b._send = b.captured.append
    return b


class WindowsBackendTests(unittest.TestCase):
    def test_input_layout_matches_windows_abi(self):
        b = backend()
        self.assertEqual(ctypes.sizeof(b.Input), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_alt_tab_key_order(self):
        b = backend()
        b.alt_start()
        self.assertEqual([(e.ki.wVk, e.ki.dwFlags) for e in b.captured], [(0x12,0),(9,0),(9,2)])
        b.alt_end()
        self.assertEqual(b.captured[-1].ki.wVk, 0x12)
        self.assertEqual(b.captured[-1].ki.dwFlags, 2)
        self.assertFalse(b.keys)

    def test_previous_window_releases_shift(self):
        b = backend()
        b.alt_start()
        b.alt_step(-1)
        self.assertEqual([(e.ki.wVk,e.ki.dwFlags) for e in b.captured[-4:]],
                         [(0x10,0),(9,0),(9,2),(0x10,2)])
        self.assertEqual(b.keys, {0x12})

    def test_snip_shortcut_releases_all_modifiers(self):
        b = backend()
        b.snip()
        self.assertEqual([(e.ki.wVk,e.ki.dwFlags) for e in b.captured],
                         [(0x5B,0),(0x10,0),(0x53,0),(0x53,2),(0x10,2),(0x5B,2)])
        self.assertFalse(b.keys)

    def test_click_emits_down_up(self):
        b = backend()
        b.click()
        self.assertEqual([e.mi.dwFlags for e in b.captured], [2,4])
        self.assertFalse(b.left_held)

    def test_negative_wheel_uses_unsigned_dword(self):
        b = backend()
        b.scroll(-2)
        self.assertEqual(b.captured[0].mi.mouseData, (-240) & 0xffffffff)

    def test_cleanup_attempts_other_keys_even_if_one_fails(self):
        b = backend()
        b.keys = {0x10, 0x12, 0x5b}
        calls = []
        def key(vk, down):
            calls.append(vk)
            if vk == 0x10:
                raise OSError("fake failure")
            b.keys.discard(vk)
        with patch.object(b, "_key", side_effect=key):
            with self.assertRaises(OSError):
                b.release_all()
        self.assertEqual(set(calls), {0x10,0x12,0x5b})
        self.assertEqual(b.keys, {0x10})

    def test_drag_cleanup_is_idempotent(self):
        b = backend()
        b.left_down()
        b.release_all()
        b.release_all()
        self.assertEqual([e.mi.dwFlags for e in b.captured], [2,4])


if __name__ == "__main__":
    unittest.main()
