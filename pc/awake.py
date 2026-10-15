"""Keep this computer awake and on while the AIM line is on.

  python awake.py on       start the keep-awake process AND switch the power plan so the computer never goes to
                           sleep or hibernation on its own, on mains or battery (and closing a laptop lid does nothing)
  python awake.py off      stop it and put the power plan back exactly as it was before
  python awake.py status   show what is applied

What it does:
  * a hidden process asks Windows to stay awake (SetThreadExecutionState); it dies with the line
  * the original sleep / hibernate / lid settings of the active power plan are saved in awake-state.json and
    restored by "off" (also by the next "on" if a crash left them changed: run "python awake.py off")
What it cannot do: stop you from shutting down or sleeping the computer by hand (Start menu, power button), force
quit by Windows Update or a power cut. The screen may still turn off.
"""
import base64
import json
import os
import re
import subprocess
import sys

HOME = os.path.join(os.path.expanduser("~"), ".aim")
PIDFILE = os.path.join(HOME, "awake.pid")
STATE = os.path.join(HOME, "awake-state.json")
SETTINGS = [("SUB_SLEEP", "STANDBYIDLE"), ("SUB_SLEEP", "HIBERNATEIDLE"), ("SUB_BUTTONS", "LIDACTION")]
LOOP = (
    "Add-Type -Namespace W -Name P -MemberDefinition "
    "'[System.Runtime.InteropServices.DllImport(\"kernel32.dll\")] public static extern uint SetThreadExecutionState(uint f);';"
    "while($true){[void][W.P]::SetThreadExecutionState([uint32]2147483649);Start-Sleep -Seconds 30}"
)


def powercfg(*args):
    return subprocess.run(["powercfg"] + list(args), capture_output=True, text=True)


def active_scheme():
    m = re.search(r"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})", powercfg("/getactivescheme").stdout)
    return m.group(1) if m else None


def read_setting(scheme, sub, setting):
    out = powercfg("/query", scheme, sub, setting).stdout
    ac = re.search(r"Current AC Power Setting Index:\s*0x([0-9a-fA-F]+)", out)
    dc = re.search(r"Current DC Power Setting Index:\s*0x([0-9a-fA-F]+)", out)
    if not ac or not dc:
        return None
    return [int(ac.group(1), 16), int(dc.group(1), 16)]


def write_setting(scheme, sub, setting, ac, dc):
    powercfg("/setacvalueindex", scheme, sub, setting, str(ac))
    powercfg("/setdcvalueindex", scheme, sub, setting, str(dc))


def apply_power():
    if os.path.exists(STATE):   # already applied (or a crash left it applied): keep the ORIGINAL values
        return
    scheme = active_scheme()
    if not scheme:
        return
    saved = {}
    for sub, setting in SETTINGS:
        v = read_setting(scheme, sub, setting)
        if v is not None:
            saved["%s/%s" % (sub, setting)] = v
    if not saved:
        return
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump({"scheme": scheme, "values": saved}, f)
    for key in saved:
        sub, setting = key.split("/")
        write_setting(scheme, sub, setting, 0, 0)   # 0 = never (sleep, hibernate) / do nothing (lid)
    powercfg("/setactive", scheme)


def restore_power():
    try:
        with open(STATE, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return False
    for key, (ac, dc) in st["values"].items():
        sub, setting = key.split("/")
        write_setting(st["scheme"], sub, setting, ac, dc)
    powercfg("/setactive", st["scheme"])
    os.remove(STATE)
    return True


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


def on():
    apply_power()
    if alive(read_pid()):
        print("awake: already on")
        return
    flags = 0x00000200 | 0x08000000  # NEW_PROCESS_GROUP | NO_WINDOW (DETACHED_PROCESS makes powershell exit at once)
    enc = base64.b64encode(LOOP.encode("utf-16-le")).decode()   # -EncodedCommand: the embedded quotes survive Windows argument parsing
    p = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=flags, close_fds=True)
    with open(PIDFILE, "w") as f:
        f.write(str(p.pid))
    print("awake: on (pid %d), sleep/hibernate/lid switched off" % p.pid)


def off():
    pid = read_pid()
    if pid and alive(pid):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    restored = restore_power()
    print("awake: off" + (", power plan restored" if restored else ""))


def status():
    print("process:", "running" if alive(read_pid()) else "not running")
    print("power plan changed:", os.path.exists(STATE))
    scheme = active_scheme()
    for sub, setting in SETTINGS:
        print(sub, setting, read_setting(scheme, sub, setting))


if __name__ == "__main__":
    {"on": on, "off": off, "status": status}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
