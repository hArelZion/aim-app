"""AIM step cards: a Claude Code PostToolUse hook that mirrors each tool call (command, edit, search...) of the
session running the phone line to the AIM chat as a collapsible "tool" card, like the desktop app shows them.

The hook is registered in ~/.claude/settings.json and reads the hook JSON on stdin. Only the session that turned
the line on (ran "aim.py mode on" or "aim.py newconv") posts; "aim.py mode off" ends it. Other sessions exit at
once. As PreToolUse it also writes the running step (control row "step": {text, at, conv}) so the phone shows it
live with a timer; PostToolUse clears it. Posting runs in a detached child so the hook returns in a moment.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HOME = os.path.join(os.path.expanduser("~"), ".aim")
SESSION = os.path.join(HOME, "phone_session")
LIMIT = 3000

# Plumbing of the phone line itself: not worth a card.
NOISE = re.compile(r"(aim\.py|watch\.sh|team\.py|pcstat\.py|awake\.py|aim_gpt\.py|aim_gemini\.py)")
TOOLS = ("Bash", "PowerShell", "Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "Grep", "Glob",
         "WebFetch", "WebSearch", "Agent", "Task")
BROWSER = ("mcp__Claude_Browser__", "mcp__playwright__", "mcp__claude-in-chrome__")
HIDDEN_FILES = ("secrets.env", ".pem", "voice.token")


def cut(s, n=LIMIT):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n] + "\n… (+%d)" % (len(s) - n)


def base(p):
    return os.path.basename(str(p or "").rstrip("/\\")) or str(p or "")


def output_of(resp):
    if isinstance(resp, str):
        return resp
    if isinstance(resp, list):
        return "\n".join(x.get("text", "") if isinstance(x, dict) else str(x) for x in resp)
    if isinstance(resp, dict):
        if "stdout" in resp or "stderr" in resp:
            return "\n".join(x for x in (resp.get("stdout"), resp.get("stderr")) if x)
        if isinstance(resp.get("file"), dict):
            f = resp["file"]
            return "%s lines" % f.get("numLines", f.get("totalLines", "?"))
        for k in ("content", "result", "output", "text"):
            if isinstance(resp.get(k), (str, list)):
                return output_of(resp[k])
        if "filenames" in resp:
            return "\n".join(resp["filenames"][:50])
    return json.dumps(resp, ensure_ascii=False)[:LIMIT] if resp else ""


def card(name, inp, resp):
    """-> dict(t=tool label, title, in, out) or None to skip."""
    inp = inp or {}
    desc = inp.get("description")
    if name in ("Bash", "PowerShell"):
        cmd = inp.get("command", "")
        if NOISE.search(cmd) and not re.search(r"\b(git|npm|pip)\b", cmd):
            return None
        return {"t": name, "title": desc or cmd.split("\n")[0][:80], "in": "$ " + cmd, "out": output_of(resp)}
    path = inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or ""
    if any(path.endswith(h) for h in HIDDEN_FILES):
        return {"t": name, "title": name + " " + base(path), "in": path, "out": "(hidden)"}
    if name == "Read":
        return {"t": name, "title": "Read " + base(path), "in": path, "out": output_of(resp)}
    if name in ("Edit", "MultiEdit"):
        edits = inp.get("edits") or [inp]
        diff = "\n\n".join("\n".join(["- " + l for l in (e.get("old_string") or "").split("\n")]
                                     + ["+ " + l for l in (e.get("new_string") or "").split("\n")]) for e in edits)
        add = sum(len((e.get("new_string") or "").split("\n")) for e in edits)
        rem = sum(len((e.get("old_string") or "").split("\n")) for e in edits)
        return {"t": "Edit", "title": "Edited " + base(path), "in": path + "\n\n" + diff, "out": "", "diff": 1,
                "add": add, "del": rem}
    if name == "Write":
        body = inp.get("content") or ""
        return {"t": name, "title": "Wrote " + base(path), "in": path + "\n\n" + body, "out": "",
                "add": len(body.split("\n")), "del": 0}
    if name == "NotebookEdit":
        return {"t": name, "title": "Edited " + base(path), "in": inp.get("new_source", ""), "out": ""}
    if name in ("Grep", "Glob"):
        pat = inp.get("pattern", "")
        return {"t": name, "title": ("Searched " if name == "Grep" else "Found files ") + pat[:60],
                "in": pat + ("  in " + path if path else ""), "out": output_of(resp)}
    if name == "WebSearch":
        return {"t": name, "title": "Searched the web: " + inp.get("query", "")[:60], "in": inp.get("query", ""), "out": output_of(resp)}
    if name == "WebFetch":
        return {"t": name, "title": "Read " + inp.get("url", "")[:70], "in": inp.get("url", ""), "out": output_of(resp)}
    if name in ("Agent", "Task"):
        return {"t": "Agent", "title": desc or "Agent", "in": inp.get("prompt", ""), "out": output_of(resp)}
    if name.startswith(BROWSER):
        short = name.split("__")[-1]
        what = inp.get("url") or inp.get("action") or inp.get("query") or inp.get("text") or ""
        return {"t": "Browser", "title": "Browser · " + short + (" " + str(what)[:60] if what else ""),
                "in": json.dumps(inp, ensure_ascii=False), "out": "" if "screenshot" in json.dumps(inp) else output_of(resp)}
    return None


def redact(s):
    try:
        with open(os.path.join(HOME, "secrets.env"), encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    v = line.split("=", 1)[1].strip()
                    if len(v) >= 8:
                        s = s.replace(v, "***")
    except OSError:
        pass
    return re.sub(r"\b(sk-[A-Za-z0-9_-]{16,}|sb_secret_[A-Za-z0-9_-]{10,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_.-]+)", "***", s)


def post(payload_file):
    with open(payload_file, encoding="utf-8") as f:
        c = json.load(f)
    os.remove(payload_file)
    sys.path.insert(0, HOME)
    import aim
    ts = c.pop("ts")
    row = {"id": "m%d-k%s" % (ts, os.getpid() % 1000), "sender": "claude", "kind": "tool",
           "text": json.dumps(c, ensure_ascii=False), "ts": ts}
    conv = aim.current_conv()
    if conv:
        row["conv"] = conv
    aim.call("POST", "/rest/v1/messages", row, {"Prefer": "return=minimal"})
    if aim.get_row("step").get("at") == c.get("started"):
        aim.put_row("step", {})


def step(payload_file):
    with open(payload_file, encoding="utf-8") as f:
        c = json.load(f)
    os.remove(payload_file)
    sys.path.insert(0, HOME)
    import aim
    aim.put_row("step", {"text": c["title"], "at": c["ts"], "conv": aim.current_conv()})


TASKS = os.path.join(HOME, "phone_tasks.json")


def load_tasks():
    try:
        with open(TASKS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def save_tasks(lst):
    with open(TASKS, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False)
    spawn("--tasks", {"list": lst})


def sweep(h, lst):
    """Drop background tasks that finished: Claude Code writes a <task-notification> naming the tool-use id into
    the transcript when one completes, fails or is stopped."""
    if not lst:
        return lst
    try:
        with open(h.get("transcript_path") or "", "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 600000))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return lst
    now = time.time() * 1000
    return [t for t in lst if "<tool-use-id>%s</tool-use-id>" % t["id"] not in tail
            and "<task-id>%s</task-id>" % t.get("task", "-") not in tail and now - t["at"] < 12 * 3600e3]


def tasks_row(payload_file):
    with open(payload_file, encoding="utf-8") as f:
        c = json.load(f)
    os.remove(payload_file)
    sys.path.insert(0, HOME)
    import aim
    aim.put_row("tasks", {"list": [{"id": t["id"], "title": t["title"], "at": t["at"]} for t in c["list"]],
                          "conv": aim.current_conv()})


PERM_WAIT = 180   # seconds the phone gets to answer a permission request before the normal dialog takes over


def ask_permission(h, name, inp):
    """PermissionRequest hook: show the request on the phone with Allow / Deny and wait for the answer (control
    row "perm-ans" {pid, behavior}). No answer in time: print nothing, so the usual dialog appears on the computer."""
    sys.path.insert(0, HOME)
    import aim
    now = int(time.time() * 1000)
    pid = "p%d" % now
    c = None
    try:
        c = card(name, inp, None)
    except Exception:
        pass
    if not c:
        c = {"t": name, "title": (inp or {}).get("description") or name, "in": json.dumps(inp, ensure_ascii=False)}
    payload = {"t": c["t"], "title": redact(c["title"]), "in": redact(cut(c.get("in") or "", 1500)), "pid": pid, "state": "ask"}
    if c.get("diff"):
        payload["diff"] = 1
    mid = "m%d-c" % now
    row = {"id": mid, "sender": "claude", "kind": "perm", "text": json.dumps(payload, ensure_ascii=False), "ts": now}
    conv = aim.current_conv()
    if conv:
        row["conv"] = conv
    aim.call("POST", "/rest/v1/messages", row, {"Prefer": "return=minimal"})
    try:
        import push
        push.send("Claude מבקש אישור: " + payload["title"], conv, "question", None, "🔐 נדרש אישור")
    except Exception:
        pass

    def finish(state):
        payload["state"] = state
        aim.call("PATCH", "/rest/v1/messages?id=eq." + mid, {"text": json.dumps(payload, ensure_ascii=False)},
                 {"Prefer": "return=minimal"})
    end = time.time() + PERM_WAIT
    while time.time() < end:
        ans = aim.get_row("perm-ans")
        if ans.get("pid") == pid and ans.get("behavior") in ("allow", "deny"):
            finish(ans["behavior"])
            dec = {"behavior": ans["behavior"]}
            if ans["behavior"] == "deny":
                dec["message"] = "The user denied this from the phone (AIM)."
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": dec}}))
            return
        time.sleep(2)
    finish("timeout")


MIRROR = os.path.join(HOME, "phone_mirror.json")


def mirror(h, cmd):
    """Post the words Claude wrote between steps to the phone, like the desktop transcript. Reads the session
    transcript from where the last call stopped; the first call of a session only marks the end (no history)."""
    path = h.get("transcript_path") or ""
    if not path:
        return
    size = os.path.getsize(path)
    try:
        with open(MIRROR, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}

    def save(off):
        with open(MIRROR, "w", encoding="utf-8") as f:
            json.dump({"path": path, "off": off}, f)
    if st.get("path") != path or st.get("off", 0) > size:
        save(size)
        return
    if size == st["off"]:
        return
    with open(path, "rb") as f:
        f.seek(st["off"])
        raw = f.read(size - st["off"])
    cut = raw.rfind(b"\n")
    if cut < 0:
        return
    save(st["off"] + cut + 1)
    texts = []
    for line in raw[:cut + 1].decode("utf-8", "replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("isSidechain"):
            continue
        if e.get("type") == "user":
            # A new prompt (the user, or a task notification) starts a new turn: text gathered so far was the
            # previous turn's final answer, which went to the phone with `say` already. Tool results don't count.
            c = (e.get("message") or {}).get("content")
            if not (isinstance(c, list) and c and all(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)):
                texts = []
            continue
        if e.get("type") != "assistant":
            continue
        content = (e.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if isinstance(b, dict) and b.get("type") == "text" and (b.get("text") or "").strip():
                texts.append(b["text"].strip())
    if re.search(r"aim\.py\s+say", cmd):
        return   # that text is posted by the say command itself
    now = int(time.time() * 1000)
    for k, tx in enumerate(texts):
        spawn("--say", {"text": redact(tx), "ts": now - len(texts) + k})


def say_row(payload_file):
    with open(payload_file, encoding="utf-8") as f:
        c = json.load(f)
    os.remove(payload_file)
    sys.path.insert(0, HOME)
    import aim
    row = {"id": "m%d-c" % c["ts"], "sender": "claude", "kind": "reply", "text": c["text"], "ts": c["ts"]}
    conv = aim.current_conv()
    if conv:
        row["conv"] = conv
    aim.call("POST", "/rest/v1/messages", row, {"Prefer": "return=minimal"})


def spawn(mode, c):
    fd, tmp = tempfile.mkstemp(prefix="aimtool-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False)
    flags = (0x08000000 | 0x00000200) if os.name == "nt" else 0   # no window, own process group
    subprocess.Popen([sys.executable, os.path.abspath(__file__), mode, tmp], creationflags=flags,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, start_new_session=os.name != "nt")


def hook():
    try:
        h = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
    except ValueError:
        return
    sid, name, inp = h.get("session_id") or "", h.get("tool_name") or "", h.get("tool_input") or {}
    cmd = inp.get("command", "") if isinstance(inp, dict) else ""
    if re.search(r"aim\.py\s+(mode\s+on|newconv)", cmd):
        with open(SESSION, "w", encoding="utf-8") as f:
            f.write(sid)
    elif re.search(r"aim\.py\s+mode\s+off", cmd):
        try:
            os.remove(SESSION)
        except OSError:
            pass
        if load_tasks():
            save_tasks([])
        return
    try:
        with open(SESSION, encoding="utf-8") as f:
            if f.read().strip() != sid:
                return
    except OSError:
        return
    if h.get("hook_event_name") == "PermissionRequest":
        try:
            ask_permission(h, name, inp if isinstance(inp, dict) else {})
        except BaseException:
            pass   # no answer printed: the normal dialog shows on the computer
        return
    tasks = load_tasks()
    left = sweep(h, tasks)
    if left != tasks:
        save_tasks(left)
        tasks = left
    if h.get("hook_event_name") == "PreToolUse":
        try:
            mirror(h, cmd)
        except Exception:
            pass
    if not name or (name not in TOOLS and not name.startswith(BROWSER)):
        return
    pre = h.get("hook_event_name") == "PreToolUse"
    c = card(name, inp, None if pre else h.get("tool_response"))
    if not c:
        return
    started = os.path.join(tempfile.gettempdir(), "aimtool-started-" + re.sub(r"\W", "", h.get("tool_use_id") or "x"))
    now = int(time.time() * 1000)
    if pre:
        with open(started, "w") as f:
            f.write(str(now))
        spawn("--step", {"title": redact(c["title"]), "ts": now})
        return
    try:
        with open(started) as f:
            c["started"] = int(f.read().strip())
        os.remove(started)
    except (OSError, ValueError):
        pass
    c["in"], c["out"] = redact(cut(c["in"])), redact(cut(c["out"]))
    c["title"] = redact(c["title"])
    c["ts"] = now
    spawn("--post", c)
    if isinstance(inp, dict) and inp.get("run_in_background"):
        m = re.search(r"\bID: (\w+)", output_of(h.get("tool_response")) or "")
        tasks.append({"id": h.get("tool_use_id") or str(now), "task": m.group(1) if m else None,
                      "title": c["title"], "at": now})
        save_tasks(tasks)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--post":
        post(sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "--step":
        step(sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "--tasks":
        tasks_row(sys.argv[2])
    elif len(sys.argv) > 2 and sys.argv[1] == "--say":
        say_row(sys.argv[2])
    else:
        try:
            hook()
        except Exception:
            pass   # a hook must never get in Claude's way
