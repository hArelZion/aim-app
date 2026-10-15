"""Computer status for the phone's settings sheet (control row "pc").

  python pcstat.py                 write battery, CPU and memory now (the watcher runs this about once a minute)
  python pcstat.py use5h=41 reset5h=2026-10-11T12:20:00Z useWeek=27
                                   also merge plan usage (Claude writes it when it reads get_usage)

No third-party packages: Windows APIs through ctypes. Keys already in the row (like usage) are kept.
"""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aim  # noqa: E402


class _Power(ctypes.Structure):
    _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte), ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte), ("BatteryLifeTime", ctypes.c_ulong), ("BatteryFullLifeTime", ctypes.c_ulong)]


class _Mem(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + \
               [(n, ctypes.c_ulonglong) for n in ("total", "avail", "ptotal", "pavail", "vtotal", "vavail", "xavail")]


def _ft(f):
    return f.dwHighDateTime << 32 | f.dwLowDateTime


class _FT(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]


def _times():
    i, k, u = _FT(), _FT(), _FT()
    ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(i), ctypes.byref(k), ctypes.byref(u))
    return _ft(i), _ft(k) + _ft(u)


def sample():
    out = {}
    if os.name != "nt":
        return out
    p = _Power()
    if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(p)) and p.BatteryFlag != 128 and p.BatteryLifePercent <= 100:
        out["battery"] = p.BatteryLifePercent
        out["plugged"] = p.ACLineStatus == 1
    m = _Mem(); m.dwLength = ctypes.sizeof(_Mem)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        out["ram"] = m.dwMemoryLoad
    i1, t1 = _times(); time.sleep(0.5); i2, t2 = _times()
    if t2 > t1:
        out["cpu"] = round(100 * (1 - (i2 - i1) / (t2 - t1)))
    g = gpu()
    if g is not None:
        out["gpu"] = g
    return out


def gpu():
    """3D load of the graphics card in percent (Windows performance counters; about 3 seconds)."""
    import subprocess
    ps = (r"$s=(Get-Counter '\GPU Engine(*engtype_3D)\Utilization Percentage' -ErrorAction Stop).CounterSamples"
          " | Measure-Object -Property CookedValue -Sum; [math]::Round($s.Sum)")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=12,
                           creationflags=0x08000000)
        return max(0, min(100, int(float(r.stdout.strip().splitlines()[-1]))))
    except Exception:
        return None


def gpt_usage():
    """ChatGPT plan limits as Codex last saw them (newest rate_limits event in ~/.codex/sessions)."""
    import glob
    import json
    from datetime import datetime, timezone
    files = sorted(glob.glob(os.path.join(os.path.expanduser("~"), ".codex", "sessions", "*", "*", "*", "*.jsonl")),
                   key=os.path.getmtime, reverse=True)[:15]
    for path in files:
        last = None
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if '"rate_limits"' in line and '"used_percent"' in line:
                        last = line
        except OSError:
            continue
        if not last:
            continue
        ev = json.loads(last)
        stack, rl = [ev], None
        while stack and rl is None:
            o = stack.pop()
            if isinstance(o, dict):
                if isinstance(o.get("rate_limits"), dict):
                    rl = o["rate_limits"]
                stack.extend(o.values())
        if not rl:
            continue
        out = {"plan": rl.get("plan_type"), "at": ev.get("timestamp")}
        for w in (rl.get("primary"), rl.get("secondary")):
            if not w:
                continue
            iso = datetime.fromtimestamp(w["resets_at"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if w.get("resets_at") else None
            key = "Week" if (w.get("window_minutes") or 0) >= 1440 else "5h"
            out["use" + key], out["reset" + key] = w.get("used_percent"), iso
        if rl.get("rate_limit_reached_type"):
            out["reached"] = rl["rate_limit_reached_type"]
        return out
    return None


def gemini_usage():
    import json
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gemini-usage.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def claude_usage():
    """Weekly usage as the Claude app shows it in its own window (read through UI Automation, no tokens).
    The app lists the 5-hour window too once it is the tight one; otherwise only the weekly line."""
    import re
    from datetime import datetime, timedelta, timezone
    import aim_model as m
    w = m.claude_window()
    if not w:
        return {}
    name = next((n for t, n, _ in m.scan(w) if n.startswith("Usage:")), "")
    out = {}
    wk = re.search(r"Weekly[^:]*:\s*(\d+)%", name)
    if wk:
        out["useWeek"] = float(wk.group(1))
    h5 = re.search(r"5-hour[^:]*:\s*(\d+)%", name)
    if h5:
        out["use5h"] = float(h5.group(1))
    rs = re.search(r"Resets (\w{3}) (\d+):(\d+) ([AP]M)", name)
    if rs and wk:
        day = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].index(rs.group(1))
        hr = int(rs.group(2)) % 12 + (12 if rs.group(4) == "PM" else 0)
        now = datetime.now().astimezone()
        t = now.replace(hour=hr, minute=int(rs.group(3)), second=0, microsecond=0)
        t += timedelta(days=(day - now.weekday()) % 7)
        if t <= now:
            t += timedelta(days=7)
        out["resetWeek"] = t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def main():
    data = aim.get_row("pc")
    data.update(sample())
    for k, fn in (("gpt", gpt_usage), ("gemini", gemini_usage)):
        try:
            v = fn()
            if v:
                data[k] = v
        except Exception:
            pass
    if not any(a.startswith("use") for a in sys.argv[1:]):
        try:
            data.update(claude_usage())
        except Exception:
            pass
    for pair in sys.argv[1:]:
        k, v = pair.split("=", 1)
        if v == "-":
            data.pop(k, None)
        else:
            data[k] = float(v) if v.replace(".", "", 1).isdigit() else v
    data["at"] = aim.now_iso()
    aim.put_row("pc", data)
    print(data)


if __name__ == "__main__":
    main()
