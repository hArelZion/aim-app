"""AIM hand-off: open a new Claude Code session on this computer and start the phone line there.

  python aim_handoff.py [folder]     folder as the Claude app's sidebar names it (default: .aim)

Presses the sidebar's "New session in <folder>" button of the Claude desktop app (Windows UI Automation, like
aim_model.py), types "/phone" into the new session's prompt and sends it. The new session's /phone takes the line
over (aim.py mode on + newconv move the step cards and replies to it); the calling session stops its watcher.
Prints "ok <new title>" or "error <why>".
"""
import ctypes
import sys
import time

import aim_model as m  # noqa: E402  (DPI awareness, UI Automation helpers)

EDIT, DOC = 50004, 50030
KEYEVENTF_UNICODE, KEYEVENTF_KEYUP = 0x0004, 0x0002


class _KI(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]


class _IN(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KI), ("pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_ulong), ("u", _U)]


def _send(vk=0, scan=0, flags=0):
    i = _IN(type=1)
    i.ki = _KI(vk, scan, flags, 0, 0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_IN))


def type_text(s):
    for ch in s:
        _send(scan=ord(ch), flags=KEYEVENTF_UNICODE)
        _send(scan=ord(ch), flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
        time.sleep(0.03)


def key(vk):
    _send(vk=vk)
    _send(vk=vk, flags=KEYEVENTF_KEYUP)


def doc_title(items):
    return next((n for t, n, _ in items if t == DOC and n.endswith(" - Claude Code")), "")


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else ".aim"
    w = m.claude_window()
    if not w:
        print("error window"); return
    items = m.scan(w)
    before = doc_title(items)
    btn = next((e for t, n, e in items if t == m.BUTTON and n == "New session in " + folder), None)
    if not btn:
        print("error no-folder " + folder); return
    m.invoke(btn)
    prompt = None
    for _ in range(20):   # the new session opens with an empty prompt and a new document title
        time.sleep(0.5)
        items = m.scan(w)
        if doc_title(items) != before:
            prompt = next((e for t, n, e in items if t == EDIT and n == "Prompt"), None)
            if prompt:
                break
    if not prompt:
        print("error no-new-session"); return
    try:
        prompt.SetFocus()
    except Exception:
        m.click(prompt)
    time.sleep(0.4)
    type_text("/phone")
    time.sleep(0.6)
    key(0x1B)          # close the command suggestions
    time.sleep(0.3)
    key(0x0D)          # send
    time.sleep(1.5)
    print("ok " + doc_title(m.scan(w)))


if __name__ == "__main__":
    main()
