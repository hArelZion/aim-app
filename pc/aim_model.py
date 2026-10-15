"""AIM model picker: switch the model and effort of the Claude Code session that runs the phone line, from the phone.

Claude Code may not change its own session's model by tool, so this presses the real buttons of the Claude desktop
app through Windows UI Automation ("Model: <name>" and "Effort: <level>" in the composer), the same as a click.
It only acts when the open session in the Claude window is the phone's session (window title starts with the title
saved in ~/.aim/phone_session_title), so another session is never changed by mistake.

  python aim_model.py state [--full]   publish control row "model" {model, effort, level, models, title, ok, at}
                                       (--full also opens both menus briefly to read the model list and slider)
  python aim_model.py apply            run the phone's pending request (control row "model-req" {at, model?, level?})
  python aim_model.py title T          remember the phone session's title (the /phone skill sets it)
The watcher runs "apply" when the phone asks and "state" every minute; nothing here costs tokens.
"""
import ctypes
import json
import os
import sys
import time

HOME = os.path.join(os.path.expanduser("~"), ".aim")
TITLE = os.path.join(HOME, "phone_session_title")
HANDLED = os.path.join(HOME, "model_req_at")
CACHE = os.path.join(HOME, "model_list.json")

ctypes.windll.shcore.SetProcessDpiAwareness(2)
import comtypes.client  # noqa: E402

comtypes.client.GetModule("UIAutomationCore.dll")
from comtypes.gen.UIAutomationClient import (  # noqa: E402
    CUIAutomation, IUIAutomation, TreeScope_Children, TreeScope_Descendants, IUIAutomationExpandCollapsePattern,
    IUIAutomationRangeValuePattern, IUIAutomationSelectionItemPattern, IUIAutomationLegacyIAccessiblePattern)

uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
BUTTON, RADIO, SLIDER, DOCUMENT = 50000, 50013, 50015, 50030
# Work modes the phone may pick, ("Bypass permissions" stays computer-only).
MODES = ["Auto", "Manual", "Accept edits", "Plan"]
STATUS = ("Running", "Unread response", "Needs input", "Waiting", "Idle", "Error")


def sessions(items):
    """The Claude app's sidebar, read only, as [{title, status, folder}] ("Running X", "Idle X",
    "Unread response X" buttons; a folder starts at its "New session in <folder>" button)."""
    out, folder = [], ""
    for t, n, e in items:
        if t != BUTTON or not n:
            continue
        if n.startswith("New session in "):
            folder = n[len("New session in "):]
            continue
        for st in STATUS:
            if n.startswith(st + " "):
                out.append({"title": n[len(st) + 1:], "status": st, "folder": folder})
                break
    return out[:80]


def claude_window():
    wins = uia.GetRootElement().FindAll(TreeScope_Children, uia.CreateTrueCondition())
    for i in range(wins.Length):
        w = wins.GetElement(i)
        try:
            if w.CurrentName.strip() == "Claude" and w.CurrentClassName.startswith("Chrome"):
                return w
        except Exception:
            pass
    return None


def scan(w):
    """[(type, name, element)]. The first query wakes Chromium's accessibility tree, so retry once if it is thin."""
    for _ in range(3):
        out = []
        els = w.FindAll(TreeScope_Descendants, uia.CreateTrueCondition())
        for i in range(els.Length):
            try:
                e = els.GetElement(i)
                out.append((e.CurrentControlType, e.CurrentName or "", e))
            except Exception:
                pass
        if len(out) > 60:
            return out
        time.sleep(1.2)
    return out


def find(items, typ, prefix):
    for t, n, e in items:
        if t == typ and n.startswith(prefix):
            return e, n
    return None, None


def press_escape():
    u = ctypes.windll.user32
    u.keybd_event(0x1B, 0, 0, 0)
    u.keybd_event(0x1B, 0, 2, 0)


def click(e):
    r = e.CurrentBoundingRectangle
    u = ctypes.windll.user32
    u.SetCursorPos((r.left + r.right) // 2, (r.top + r.bottom) // 2)
    u.mouse_event(2, 0, 0, 0, 0)
    u.mouse_event(4, 0, 0, 0, 0)


def expand(e):
    try:
        e.GetCurrentPattern(10005).QueryInterface(IUIAutomationExpandCollapsePattern).Expand()
    except Exception:   # Expand is refused when the window is not in front: click instead
        click(e)
    time.sleep(0.8)


def session_ok(items):
    """True when the window shows the phone's session (or no title was saved)."""
    try:
        with open(TITLE, encoding="utf-8") as f:
            want = f.read().strip()
    except OSError:
        return True, ""
    doc = [n for t, n, _ in items if t == DOCUMENT]
    return any(n.startswith(want) for n in doc), want


def read_state(full=False):
    w = claude_window()
    if not w:
        return {"ok": False, "error": "window"}
    items = scan(w)
    mb, mname = find(items, BUTTON, "Model: ")
    eb, ename = find(items, BUTTON, "Effort: ")
    if not mb:
        return {"ok": False, "error": "buttons"}
    st = {"ok": True, "model": mname[7:], "effort": ename[8:] if ename else None}
    st["sessions"] = sessions(items)
    st["mode"] = next((n for t, n, _ in items if t == BUTTON and n in MODES + ["Bypass permissions"]), None)
    st["modes"] = MODES
    good, title = session_ok(items)
    st["title"] = title
    st["same"] = good
    try:
        with open(CACHE, encoding="utf-8") as f:
            st.update(json.load(f))
    except (OSError, ValueError):
        pass
    if st.get("efforts") and st.get("effort") in st["efforts"]:
        st["level"] = st["efforts"].index(st["effort"])
    if full and good:
        was = shown(w)
        try:
            expand(mb)
            names = [n for t, n, _ in scan(w) if t == RADIO]
            press_escape(); time.sleep(0.4)
            if names:
                st["models"] = [{"name": n.split(" Requires")[0], "note": "credits" if "Requires" in n else ""} for n in names]
            if eb:
                expand(eb)
                sl, _ = find(scan(w), SLIDER, "")
                if sl:
                    rv = sl.GetCurrentPattern(10003).QueryInterface(IUIAutomationRangeValuePattern)
                    lo = rv.CurrentMinimum
                    n = int(rv.CurrentMaximum - lo) + 1
                    cur = int(rv.CurrentValue - lo)
                    st["levels"], st["level"] = n, cur
                    if len(st.get("efforts") or []) != n:   # learn the names by walking the slider once, then put it back
                        names = []
                        for k in range(n):
                            rv.SetValue(lo + k)
                            time.sleep(0.5)
                            nm = find(scan(w), BUTTON, "Effort: ")[1]
                            names.append(nm[8:] if nm else str(k + 1))
                        rv.SetValue(lo + cur)
                        time.sleep(0.4)
                        if len(set(names)) == n:
                            st["efforts"] = names
                press_escape(); time.sleep(0.3)
            with open(CACHE, "w", encoding="utf-8") as f:
                json.dump({k: st[k] for k in ("models", "levels", "efforts") if k in st}, f, ensure_ascii=False)
        except Exception as ex:
            press_escape()
            st["menuError"] = str(ex)[:120]
        reminimize(w, was)
    return st


def invoke(e):
    try:
        from comtypes.gen.UIAutomationClient import IUIAutomationInvokePattern
        e.GetCurrentPattern(10000).QueryInterface(IUIAutomationInvokePattern).Invoke()
    except Exception:
        click(e)


def dialog(items):
    """The app's "Switch model?" confirmation (the switch makes Claude re-read the session, which costs more of the
    limit): (title, text, cancel, ok) or None. "Don't ask again" is never touched."""
    for t, n, e in items:
        if t == 50032 and n.endswith("?"):
            r = e.CurrentBoundingRectangle
            inside = []
            for t2, n2, e2 in items:
                try:
                    q = e2.CurrentBoundingRectangle
                except Exception:
                    continue
                if q.left >= r.left and q.right <= r.right and q.top >= r.top and q.bottom <= r.bottom:
                    inside.append((t2, n2, e2))
            btns = [(n2, e2) for t2, n2, e2 in inside if t2 == BUTTON and n2]
            cancel = next((e2 for n2, e2 in btns if n2.lower() == "cancel"), None)
            ok = next((e2 for n2, e2 in btns if n2.lower() != "cancel"), None)
            text = " ".join(n2 for t2, n2, _ in inside if t2 == 50020 and n2 != n)
            return n, text, cancel, ok
    return None


def shown(w):
    """The menus cannot open while the window is minimized: show it without taking focus. Returns True when it was minimized."""
    h = w.CurrentNativeWindowHandle
    u = ctypes.windll.user32
    if not u.IsIconic(h):
        return False
    u.ShowWindow(h, 4)   # SW_SHOWNOACTIVATE
    time.sleep(1.0)
    return True


def reminimize(w, was):
    if was:
        ctypes.windll.user32.ShowWindow(w.CurrentNativeWindowHandle, 7)   # SW_SHOWMINNOACTIVE


def apply(req):
    w = claude_window()
    if not w:
        return {"ok": False, "error": "window"}
    was = shown(w)
    try:
        return _apply(req)
    finally:
        reminimize(w, was)


def _apply(req):
    w = claude_window()
    if not w:
        return {"ok": False, "error": "window"}
    items = scan(w)
    good, _ = session_ok(items)
    if not good:
        return {"ok": False, "error": "other-session"}
    if req.get("model"):
        mb, mname = find(items, BUTTON, "Model: ")
        if not mb:
            return {"ok": False, "error": "buttons"}
        if mname[7:] != req["model"]:
            expand(mb)
            it, _ = find(scan(w), RADIO, req["model"])
            if not it:
                press_escape()
                return {"ok": False, "error": "no-model"}
            try:
                it.GetCurrentPattern(10010).QueryInterface(IUIAutomationSelectionItemPattern).Select()
            except Exception:
                try:
                    it.GetCurrentPattern(10018).QueryInterface(IUIAutomationLegacyIAccessiblePattern).DoDefaultAction()
                except Exception:
                    click(it)
            d = None
            for _ in range(6):   # the confirmation takes a moment to appear
                time.sleep(0.5)
                items = scan(w)
                d = dialog(items)
                _, now = find(items, BUTTON, "Model: ")
                if d or (now and now[7:] == req["model"]):
                    break
            if not d and now and now[7:] != req["model"]:   # the menu may still be open: choose by clicking
                it2, _ = find(items, RADIO, req["model"])
                if it2:
                    click(it2); time.sleep(0.8)
                    items = scan(w)
                    d = dialog(items)
            if d:
                title, text, cancel, ok = d
                if req.get("confirm") and ok:
                    invoke(ok)
                    time.sleep(0.8)
                else:
                    if cancel:
                        invoke(cancel)
                    else:
                        press_escape()
                    time.sleep(0.5)
                    st = read_state()
                    st.update(ok=False, error="confirm", ask={"model": req["model"], "title": title, "text": text})
                    return st
            if find(scan(w), RADIO, "")[0]:
                press_escape(); time.sleep(0.3)
    if req.get("mode") in MODES:
        mb = next((e for t, n, e in scan(w) if t == BUTTON and n in MODES + ["Bypass permissions"]), None)
        if not mb:
            return {"ok": False, "error": "buttons"}
        if mb.CurrentName != req["mode"]:
            expand(mb)
            it = next((e for t, n, e in scan(w) if t == RADIO and n.startswith(req["mode"] + " ")), None)
            if not it:
                press_escape()
                return {"ok": False, "error": "no-mode"}
            try:
                it.GetCurrentPattern(10010).QueryInterface(IUIAutomationSelectionItemPattern).Select()
            except Exception:
                click(it)
            time.sleep(0.8)
            if find(scan(w), RADIO, "")[0]:
                press_escape(); time.sleep(0.3)
        st = read_state()
        if st.get("mode") != req["mode"]:
            st.update(ok=False, error="not-changed")
        return st
    if req.get("level") is not None:
        eb, _ = find(scan(w), BUTTON, "Effort: ")
        if eb:
            expand(eb)
            sl, _ = find(scan(w), SLIDER, "")
            if sl:
                rv = sl.GetCurrentPattern(10003).QueryInterface(IUIAutomationRangeValuePattern)
                rv.SetValue(rv.CurrentMinimum + int(req["level"]))
                time.sleep(0.5)
            press_escape(); time.sleep(0.4)
    st = read_state()
    if req.get("model") and st.get("model") != req["model"]:
        st.update(ok=False, error="not-changed")
    return st


def publish(st, req_at=None):
    sys.path.insert(0, HOME)
    import aim
    old = aim.get_row("model")
    for k in ("models", "levels", "efforts", "model", "effort", "level", "mode", "modes", "title"):   # a failed switch must not hide the phone's model button
        if k not in st and k in old:
            st[k] = old[k]
    st["at"] = int(time.time() * 1000)
    if req_at:
        st["req"] = req_at
    aim.put_row("model", st)


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "state"
    if cmd == "title":
        with open(TITLE, "w", encoding="utf-8") as f:
            f.write(" ".join(args[1:]).strip())
        return
    if cmd == "state":
        publish(read_state(full="--full" in args))
    elif cmd == "apply":
        sys.path.insert(0, HOME)
        import aim
        req = aim.get_row("model-req")
        try:
            with open(HANDLED) as f:
                done = int(f.read().strip() or 0)
        except (OSError, ValueError):
            done = 0
        at = int(req.get("at") or 0)
        if at <= done:
            return
        with open(HANDLED, "w") as f:
            f.write(str(at))
        if time.time() * 1000 - at > 5 * 60000:   # a stale request (the computer was asleep): ignore it
            return
        try:
            st = apply(req)
        except Exception as ex:
            press_escape()
            st = {"ok": False, "error": "failed", "detail": str(ex)[:120]}
        publish(st, at)
    print("done")


if __name__ == "__main__":
    main()
