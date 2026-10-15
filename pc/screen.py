"""AIM screen sharing: show this computer's screen on the phone and take taps and typing back.

  python screen.py on|off      start / stop the background agent (started with the other lines by aim_gpt.py on/off)
  python screen.py start       open a session now (for Claude, when a physical approval is needed): posts a note to
                               the phone, which then shows the screen button; session ends by itself
  python screen.py stop        end the session now
  python screen.py setpin      set a PIN (read from stdin) the phone must enter to start a session; "none" removes it

Safety:
  * Only runs while the AIM line is on; /phone-off stops the agent and any session.
  * A session needs a request from the signed-in phone (row-level security: only the owner's account can write) and
    the optional PIN; it ends after 10 minutes (extend from the phone), or when stopped on either side.
  * A banner with a Stop button stays on top on this screen the whole time.
  * Frames are a single private image that is overwritten and deleted when the session ends. Only the primary
    screen is shared. Windows' secure desktop (UAC prompts, lock screen) cannot be captured or controlled.
  * Only mouse clicks/scroll, typing, and a short list of keys are accepted from the phone.
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import aim

HOME = aim.HOME
PIDFILE = os.path.join(HOME, "screen.pid")
LOG = os.path.join(HOME, "screen.log")
PINFILE = os.path.join(HOME, "screen.pin")
FRAME = "screen/frame.jpg"
SESSION_SECONDS = 600
MAX_W = 1100
KEYS = {"enter": 0x0D, "esc": 0x1B, "tab": 0x09, "backspace": 0x08, "delete": 0x2E, "space": 0x20,
        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "home": 0x24, "end": 0x23,
        "pageup": 0x21, "pagedown": 0x22}


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pin_hash(pin):
    return hashlib.sha256(("aim-screen:" + pin).encode("utf-8")).hexdigest()


def pin_required():
    return os.path.exists(PINFILE)


def pin_ok(pin):
    if not pin_required():
        return True
    with open(PINFILE, encoding="utf-8") as f:
        return pin_hash(str(pin or "")) == f.read().strip()


# ---------------------------------------------------------------- input injection (ctypes, no dependencies)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass
user32 = ctypes.windll.user32
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def _send(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def _mouse(flags, data=0):
    i = INPUT(); i.type = 0; i.u.mi = MOUSEINPUT(0, 0, data, flags, 0, 0)
    return i


def _key(vk=0, scan=0, flags=0):
    i = INPUT(); i.type = 1; i.u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return i


def click(x, y, button="left", double=False):
    user32.SetCursorPos(int(x), int(y))
    down, up = (0x0002, 0x0004) if button == "left" else (0x0008, 0x0010)
    for _ in range(2 if double else 1):
        _send(_mouse(down), _mouse(up))
        time.sleep(0.05)


def scroll(x, y, dy):
    user32.SetCursorPos(int(x), int(y))
    _send(_mouse(0x0800, int(-dy) & 0xFFFFFFFF))   # MOUSEEVENTF_WHEEL, positive = up


def type_text(s):
    for ch in s[:200]:
        code = ord(ch)
        _send(_key(0, code, 0x0004), _key(0, code, 0x0004 | 0x0002))   # KEYEVENTF_UNICODE down/up


def press(name):
    vk = KEYS.get(name)
    if vk:
        _send(_key(vk), _key(vk, 0, 0x0002))


def apply_event(ev, W, H):
    t = ev.get("t")
    x, y = float(ev.get("x", 0)) * W, float(ev.get("y", 0)) * H
    if t == "click":
        click(x, y, "right" if ev.get("b") == "right" else "left", bool(ev.get("dbl")))
    elif t == "scroll":
        scroll(x, y, max(-1200, min(1200, int(ev.get("dy", 0)))))
    elif t == "text":
        type_text(str(ev.get("s", "")))
    elif t == "key":
        press(str(ev.get("k", "")))


# ---------------------------------------------------------------- banner (always visible while sharing)
class Banner(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.q = queue.Queue(); self.stop_clicked = False; self.expires = 0

    def run(self):
        import tkinter as tk
        root = tk.Tk(); root.overrideredirect(True); root.attributes("-topmost", True)
        root.configure(bg="#b3261e")
        lab = tk.Label(root, fg="white", bg="#b3261e", font=("Segoe UI", 11, "bold"), padx=12, pady=4)
        lab.pack(side="left")
        tk.Button(root, text="Stop", command=lambda: setattr(self, "stop_clicked", True), bg="white", fg="#b3261e",
                  relief="flat", padx=10).pack(side="left", padx=(0, 8), pady=3)
        sw = root.winfo_screenwidth(); root.geometry("+%d+0" % max(0, sw // 2 - 170))

        def tick():
            try:
                if self.q.get_nowait() == "close":
                    root.destroy(); return
            except queue.Empty:
                pass
            left = max(0, int(self.expires - time.time()))
            lab.config(text="Screen shared with phone  %d:%02d" % (left // 60, left % 60))
            root.after(400, tick)
        tick(); root.mainloop()


# ---------------------------------------------------------------- session
def capture():
    from PIL import Image, ImageGrab
    img = ImageGrab.grab()
    W, H = img.size
    small = img.convert("RGB")
    small.thumbnail((MAX_W, MAX_W))
    return W, H, small


def upload(img):
    buf = io.BytesIO(); img.save(buf, "JPEG", quality=55, optimize=True)
    aim.call("POST", "/storage/v1/object/%s/%s" % (aim.BUCKET, urllib.parse.quote(FRAME)), buf.getvalue(),
             {"Content-Type": "image/jpeg", "x-upsert": "true"})


def rows(*ids):
    r = aim.call("GET", "/rest/v1/control?id=in.(%s)&select=id,data" % ",".join(ids)) or []
    return {x["id"]: x["data"] for x in r}


def session():
    expires = time.time() + SESSION_SECONDS
    banner = Banner(); banner.expires = expires; banner.start()
    last_seq, n, last_sig, last_sent = None, 0, None, 0.0
    W = H = 0
    end_reason = "expired"
    try:
        while True:
            now = time.time()
            if now >= expires:
                break
            if banner.stop_clicked:
                end_reason = "stopped on the computer"; break
            r = rows("screen-req", "screen-in", "settings")
            if (r.get("settings") or {}).get("mode") == "off":
                end_reason = "line paused"; break
            req = r.get("screen-req") or {}
            if req.get("state") == "stop":
                end_reason = "stopped on the phone"; break
            if req.get("state") == "extend" and req.get("at") != getattr(session, "_ext", None):
                session._ext = req.get("at"); expires = time.time() + SESSION_SECONDS; banner.expires = expires
            inp = r.get("screen-in") or {}
            seq = inp.get("seq")
            if seq is not None and seq != last_seq:
                if last_seq is not None and W:
                    for ev in (inp.get("events") or [])[:20]:
                        try:
                            apply_event(ev, W, H)
                        except Exception:
                            pass
                    last_sig = None   # show the result quickly
                last_seq = seq
            W, H, img = capture()
            sig = hash(img.resize((48, 27)).tobytes())
            if sig != last_sig or now - last_sent > 4:
                upload(img); n += 1; last_sig, last_sent = sig, now
                aim.put_row("screen", {"state": "on", "seq": n, "w": W, "h": H, "expires": iso(expires),
                                       "pin_required": pin_required(), "at": aim.now_iso()})
            time.sleep(0.25)
    finally:
        banner.q.put("close")
        try:
            aim.call("DELETE", "/storage/v1/object/%s/%s" % (aim.BUCKET, urllib.parse.quote(FRAME)))
        except SystemExit:
            pass
        aim.put_row("screen", {"state": "off", "reason": end_reason, "pin_required": pin_required(), "at": aim.now_iso()})
        aim.put_row("screen-in", {"seq": None, "events": []})
        aim.put_row("screen-req", {"state": "idle", "at": aim.now_iso()})


def agent():
    old = rows("screen-req").get("screen-req") or {}
    handled = old.get("at")   # a request left over from before this agent started is ignored
    aim.put_row("screen", {"state": "off", "pin_required": pin_required(), "at": aim.now_iso()})
    while True:
        try:
            r = rows("screen-req", "settings")
            req = r.get("screen-req") or {}
            if (r.get("settings") or {}).get("mode") != "off" and req.get("state") == "request" and req.get("at") != handled:
                handled = req.get("at")
                if req.get("local") or pin_ok(req.get("pin")):
                    session()
                else:
                    aim.put_row("screen", {"state": "denied", "reason": "pin", "pin_required": True, "at": aim.now_iso()})
                    aim.put_row("screen-req", {"state": "idle", "at": aim.now_iso()})
        except SystemExit:
            pass
        except Exception as e:
            print("agent error:", e, flush=True)
        time.sleep(2)


# ---------------------------------------------------------------- commands
def read_pid():
    try:
        with open(PIDFILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def alive(pid):
    if not pid:
        return False
    r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"], capture_output=True, text=True)
    return str(pid) in r.stdout


def cmd_on():
    if alive(read_pid()):
        print("screen agent already running"); return
    log = open(LOG, "ab")
    flags = 0x00000008 | 0x00000200 | 0x08000000
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "agent"], stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    with open(PIDFILE, "w") as f:
        f.write(str(p.pid))
    print("screen agent on (pid %d)" % p.pid)


def cmd_off():
    pid = read_pid()
    if pid and alive(pid):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    try:
        aim.call("DELETE", "/storage/v1/object/%s/%s" % (aim.BUCKET, urllib.parse.quote(FRAME)))
    except SystemExit:
        pass
    aim.put_row("screen", {"state": "off", "pin_required": pin_required(), "at": aim.now_iso()})
    print("screen agent off")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    c = sys.argv[1] if len(sys.argv) > 1 else ""
    if c == "agent":
        agent()
    elif c == "on":
        cmd_on()
    elif c == "off":
        cmd_off()
    elif c == "start":
        if not alive(read_pid()):
            cmd_on()
        aim.put_row("screen-req", {"state": "request", "local": True, "at": aim.now_iso()})
        ts = int(time.time() * 1000)
        aim.call("POST", "/rest/v1/messages", {"id": "m%d-c" % ts, "sender": "claude", "kind": "system", "ts": ts,
                                               "text": "המסך של המחשב זמין. לחץ על כפתור המסך בראש הדף כדי לראות ולאשר.",
                                               **({"conv": aim.current_conv()} if aim.current_conv() else {})},
                 {"Prefer": "return=minimal"})
        print("screen session requested; the phone shows the screen button")
    elif c == "stop":
        aim.put_row("screen-req", {"state": "stop", "at": aim.now_iso()})
        print("stop requested")
    elif c == "setpin":
        pin = sys.stdin.read().strip()
        if pin.lower() in ("", "none"):
            if os.path.exists(PINFILE):
                os.remove(PINFILE)
            print("PIN removed")
        else:
            with open(PINFILE, "w", encoding="utf-8") as f:
                f.write(pin_hash(pin))
            print("PIN set")
    else:
        sys.exit(__doc__)
