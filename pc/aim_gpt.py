"""AIM line for ChatGPT (Codex CLI): the same idea as /phone, for the ChatGPT side of the app.

  python aim_gpt.py on [project]   connect: new ChatGPT conversation, start the background loop
  python aim_gpt.py off            disconnect: stop the loop and mark the line off
  python aim_gpt.py run            the loop itself (started by "on"; can also be run by hand)

The loop costs nothing while idle: watch.sh polls Supabase with curl and only returns when the phone
sent a message in a ChatGPT conversation (ids starting with "g"). Then Codex answers in a sandbox with
no network and no secrets; this script does all the chat I/O (read, mark seen, post the reply).

Environment (optional):
  AIM_GPT_DIR      folder Codex works in (default: ~/.aim/gpt-work)
  AIM_GPT_SANDBOX  read-only | workspace-write (default: workspace-write)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HOME = os.path.join(os.path.expanduser("~"), ".aim")
AIM = [sys.executable, os.path.join(HOME, "aim.py")]
WORK = os.environ.get("AIM_GPT_DIR") or os.path.join(HOME, "gpt-work")
SANDBOX = os.environ.get("AIM_GPT_SANDBOX") or "workspace-write"
STATE = os.path.join(HOME, "gpt-state.json")
PIDFILE = os.path.join(HOME, "gpt.pid")
LOG = os.path.join(HOME, "gpt.log")
ENV = dict(os.environ, AIM_MODEL="gpt", PYTHONIOENCODING="utf-8")

RULES = (
    "You are ChatGPT, answering the user's private phone chat (AIM). Reply in the language of the "
    "user's message (Hebrew by default), concisely, in light Markdown: **bold**, `code`, lists, "
    "headings. No tables. Your final message is posted to the phone word for word. "
    "You have no network access here. If something needs the internet or a permission you lack, say so. "
    "To send the user a picture, save it as a PNG/JPG/GIF/WEBP file inside your working folder; every new "
    "image file there is attached to your reply automatically."
)
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")


def snapshot_images():
    seen = {}
    for root, _, files in os.walk(WORK):
        for name in files:
            if name.lower().endswith(IMG_EXT):
                path = os.path.join(root, name)
                try:
                    seen[path] = os.path.getmtime(path)
                except OSError:
                    pass
    return seen


def bash_exe():
    for c in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if os.path.exists(c):
            return c
    return shutil.which("bash") or "bash"


def aim(*args, stdin=None):
    r = subprocess.run(AIM + list(args), input=stdin, capture_output=True, text=True,
                       encoding="utf-8", env=ENV)
    return r.stdout.strip()


def load_state():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(st):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f)


def read_pid():
    try:
        with open(PIDFILE) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def alive(pid):
    if not pid:
        return False
    r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"],
                       capture_output=True, text=True)
    return str(pid) in r.stdout


def kill_tree(pid):
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def cmd_on(project):
    old = read_pid()
    if alive(old):
        print("already running (pid %d)" % old)
        return
    subprocess.run([sys.executable, os.path.join(HOME, "awake.py"), "on"], capture_output=True)
    subprocess.run([sys.executable, os.path.join(HOME, "aim_gemini.py"), "on", project], capture_output=True)
    subprocess.run([sys.executable, os.path.join(HOME, "aim_team.py"), "on", project], capture_output=True)
    subprocess.run([sys.executable, os.path.join(HOME, "screen.py"), "on"], capture_output=True)
    aim("mode", "on")
    aim("newconv", "--project", project)
    aim("status", "state=idle", "project=" + project, "activity=-")
    aim("say", "--kind", "system", stdin="מחובר · " + project)
    log = open(LOG, "ab")
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "run"], stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, env=ENV, creationflags=flags, close_fds=True)
    with open(PIDFILE, "w") as f:
        f.write(str(p.pid))
    print("ChatGPT line is on (pid %d). Log: %s" % (p.pid, LOG))


def cmd_off():
    subprocess.run([sys.executable, os.path.join(HOME, "aim_gemini.py"), "off"], capture_output=True)
    subprocess.run([sys.executable, os.path.join(HOME, "aim_team.py"), "off"], capture_output=True)
    subprocess.run([sys.executable, os.path.join(HOME, "screen.py"), "off"], capture_output=True)
    aim("mode", "off")
    subprocess.run([sys.executable, os.path.join(HOME, "awake.py"), "off"], capture_output=True)
    pid = read_pid()
    if pid and alive(pid):
        kill_tree(pid)
    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    aim("status", "state=off", "activity=-")
    aim("say", "--kind", "system", stdin="הקו הושהה.")
    print("ChatGPT line is off.")


def wait_for_phone():
    r = subprocess.run([bash_exe(), os.path.join(HOME, "watch.sh"), "gpt"], capture_output=True,
                       text=True, encoding="utf-8")
    return r.stdout.strip()


CODEX_HOME = os.path.join(os.path.expanduser("~"), ".codex")
SANDBOXES = ("read-only", "workspace-write")   # "danger-full-access" is not offered from the phone
TEXT_MAX = 400000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


def codex_models():
    """The models the Codex app lists, with their reasoning levels (from Codex's own cache)."""
    try:
        with open(os.path.join(CODEX_HOME, "models_cache.json"), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return []
    out = []
    for m in (d.get("models") if isinstance(d, dict) else d) or []:
        if m.get("visibility") != "list" or not m.get("slug"):
            continue
        out.append({"slug": m["slug"], "name": (m.get("display_name") or m["slug"]).replace("-", " "),
                    "efforts": [x.get("effort") for x in m.get("supported_reasoning_levels") or [] if x.get("effort")],
                    "def": m.get("default_reasoning_level") or "medium"})
    return out


def codex_defaults():
    model, effort = "", ""
    try:
        with open(os.path.join(CODEX_HOME, "config.toml"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r'\s*(model|model_reasoning_effort)\s*=\s*"([^"]+)"', line)
                if m and m.group(1) == "model" and not model:
                    model = m.group(2)
                elif m and m.group(1) == "model_reasoning_effort" and not effort:
                    effort = m.group(2)
    except OSError:
        pass
    return model, effort


def pick():
    """What the phone picked (control row "gpt-pick"), checked against the real lists."""
    sys.path.insert(0, HOME)
    import aim as A
    try:
        p = A.get_row("gpt-pick") or {}
    except BaseException:
        p = {}
    models = codex_models()
    dm, de = codex_defaults()
    model = p.get("model") if any(m["slug"] == p.get("model") for m in models) else dm
    info = next((m for m in models if m["slug"] == model), None)
    effort = p.get("effort") or de
    if info and effort not in info["efforts"]:
        effort = de if de in info["efforts"] else info["def"]
    sandbox = p.get("sandbox") if p.get("sandbox") in SANDBOXES else SANDBOX
    return {"model": model, "effort": effort, "sandbox": sandbox}


def publish_cfg():
    """Tell the phone what it can pick and where Codex works (control row "gpt-models")."""
    sys.path.insert(0, HOME)
    import aim as A
    cur = pick()
    try:
        A.put_row("gpt-models", {"list": codex_models(), "host": os.environ.get("COMPUTERNAME") or "PC",
                                 "dir": os.path.basename(WORK.rstrip("\\/")) or WORK, "path": WORK,
                                 "sandboxes": list(SANDBOXES), "at": int(time.time() * 1000), **cur})
    except BaseException:
        pass


def snap_text():
    """Text files in the work folder before the turn, so file edits show a real diff."""
    d = {}
    for root, dirs, files in os.walk(WORK):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for n in files:
            p = os.path.join(root, n)
            try:
                if os.path.getsize(p) > TEXT_MAX:
                    continue
                with open(p, encoding="utf-8") as f:
                    d[os.path.normcase(os.path.abspath(p))] = f.read()
            except (OSError, UnicodeDecodeError, ValueError):
                pass
        if len(d) > 3000:
            break
    return d


def read_text(path):
    try:
        if os.path.getsize(path) > TEXT_MAX:
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def file_card(path, kind, cache):
    import difflib
    full = path if os.path.isabs(path) else os.path.join(WORK, path)
    key = os.path.normcase(os.path.abspath(full))
    old = cache.get(key, "")
    new = "" if kind == "delete" else read_text(full)
    body, add, rem = [], 0, 0
    if new is None:
        body = ["(binary or large file)"]
    else:
        for l in list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=2))[2:]:
            if l.startswith("@@"):
                body.append("  ⋯")
            elif l.startswith("+"):
                body.append("+ " + l[1:])
                add += 1
            elif l.startswith("-"):
                body.append("- " + l[1:])
                rem += 1
            else:
                body.append("  " + l[1:])
        cache[key] = new
    text = "\n".join(body)
    if len(text) > 12000:
        text = text[:12000] + "\n  …"
    return {"t": "FileChange", "kind": kind, "title": full, "in": full + "\n\n" + text, "out": "", "diff": 1,
            "add": add, "del": rem}


SHELL_RE = re.compile(r'^"?[^"]*?(?:powershell|pwsh|bash|cmd)(?:\.exe)?"?\s+(?:-NoProfile\s+|-NoLogo\s+)*(?:-Command|-lc|-c|/c)\s+(.*)$',
                      re.I | re.S)
READERS = {"get-content", "gc", "cat", "type", "head", "tail", "sed", "nl"}
VALUE_FLAGS = {"-totalcount", "-head", "-tail", "-encoding", "-first", "-last", "-n", "-c", "-delimiter"}


def read_target(s):
    """The file a plain one-file read command shows (Get-Content x, cat x, sed -n 1,80p x), else None."""
    if "\n" in s or ";" in s or "&&" in s or ">" in s:
        s2 = None
    else:
        s2 = s.split("|")[0].strip()
    if not s2:
        return None
    toks = re.findall(r'"[^"]*"|\'[^\']*\'|\S+', s2)
    if not toks or toks[0].lower() not in READERS:
        return None
    files, skip = [], False
    for k, tok in enumerate(toks[1:]):
        if skip:
            skip = False
            continue
        if tok.startswith("-"):
            skip = tok.lower() in VALUE_FLAGS
            continue
        if toks[0].lower() == "sed" and re.match(r"^['\"]?\d+(,\d+)?p['\"]?$", tok):
            continue
        files.append(tok.strip("'\""))
    return files[0] if len(files) == 1 else None


def strip_shell(cmd):
    m = SHELL_RE.match((cmd or "").strip())
    s = m.group(1).strip() if m else (cmd or "").strip()
    if len(s) > 1 and s[0] == s[-1] and s[0] in "\"'":
        s = s[1:-1]
    return s.replace('\\"', '"')


def cmd_card(item):
    s = strip_shell(item.get("command"))
    out = (item.get("aggregated_output") or "").strip()
    code = item.get("exit_code")
    if code not in (None, 0):
        out = (out + "\n" if out else "") + "exit code %s" % code
    target = read_target(s)
    if target and code in (None, 0):
        return {"t": "Read", "title": os.path.basename(target.rstrip("\\/")) or target, "in": "$ " + s, "out": out}
    return {"t": "Command", "title": s.split("\n")[0][:120], "in": "$ " + s, "out": out, "code": code}


def headline(text):
    t = (text or "").strip()
    m = re.match(r"^\*\*(.+?)\*\*\s*", t)
    if m:
        return m.group(1).strip(), t[m.end():].strip()
    first = t.split("\n")[0]
    return first[:100], t[len(first):].strip()


class Poster:
    """Posts step cards and the live activity of one Codex turn to the ChatGPT conversation."""

    def __init__(self, conv):
        sys.path.insert(0, HOME)
        import aim as A
        self.A, self.conv, self.last, self.act_at = A, conv, 0, 0
        try:
            from aim_tool import redact
        except Exception:
            redact = lambda s: s
        self.redact = redact

    def ts(self):
        n = max(int(time.time() * 1000), self.last + 1)
        self.last = n
        return n

    def card(self, c):
        for k in ("title", "in", "out"):
            if c.get(k):
                c[k] = self.redact(c[k])
        ts = self.ts()
        row = {"id": "m%d-gk" % ts, "sender": "claude", "kind": "tool", "text": json.dumps(c, ensure_ascii=False), "ts": ts}
        if self.conv:
            row["conv"] = self.conv
        try:
            self.A.call("POST", "/rest/v1/messages", row, {"Prefer": "return=minimal"})
        except BaseException:
            pass

    def activity(self, text, force=False):
        now = time.time()
        if not force and now - self.act_at < 1.5:
            return
        self.act_at = now
        try:
            cur = self.A.get_row(self.A.STATUS_ROW) or {}
            cur.update({"state": "working", "activity": (text or "")[:90], "stepAt": int(now * 1000),
                        "updatedAt": self.A.now_iso()})
            self.A.put_row(self.A.STATUS_ROW, cur)
        except BaseException:
            pass


def turn(unread, st):
    ids = [m["id"] for m in unread]
    aim("seen", *ids)
    unread = [m for m in unread if m.get("kind") != "stop"]   # a stop with nothing running: just mark it read
    if not unread:
        aim("status", "state=idle", "activity=-")
        return
    started = int(time.time() * 1000)
    aim("status", "state=working", "activity=Thinking")
    texts, images = [], []
    for m in unread:
        if m.get("text"):
            texts.append(m["text"])
        for path in m.get("images") or []:
            local = aim("photo-get", path)
            if local:
                images.append(local)
    sys.path.insert(0, HOME)
    from aim import split_files, stop_requested   # photos go to Codex as images, text files and PDFs into the prompt
    images, extra = split_files(images)
    if extra:
        texts.append(extra)
    body = "\n\n".join(texts) or "(תמונה)"
    conv = aim("current")
    threads = st.setdefault("threads", {})
    tid = threads.get(conv)
    os.makedirs(WORK, exist_ok=True)
    before = snapshot_images()
    cache = snap_text()
    cfg = pick()
    publish_cfg()
    prompt = body if tid else RULES + "\n\n" + body
    cmd = ["codex", "exec"]
    cmd += ["resume", tid] if tid else ["-C", WORK]
    cmd += ["--json", "--skip-git-repo-check", "-c", "sandbox_mode=" + cfg["sandbox"]]
    if cfg["model"]:
        cmd += ["-m", cfg["model"]]
    if cfg["effort"]:
        cmd += ["-c", "model_reasoning_effort=" + cfg["effort"]]
    for img in images:
        cmd += ["-i", img]
    cmd += ["-"]
    import queue
    import threading
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace", cwd=WORK, shell=(os.name == "nt"))
    try:
        p.stdin.write(prompt)
        p.stdin.close()
    except OSError:
        pass
    q, err = queue.Queue(), []
    threading.Thread(target=lambda: [q.put(l) for l in p.stdout] + [q.put(None)], daemon=True).start()
    threading.Thread(target=lambda: err.extend(p.stderr), daemon=True).start()
    post = Poster(conv)
    pending, failure = None, None   # a message waits until the next step shows it was not the final answer

    def flush():
        nonlocal pending
        if pending:
            aim("say", "--kind", "reply", stdin=pending)
            pending = None

    while True:
        try:
            line = q.get(timeout=2)
        except queue.Empty:
            if stop_requested(started, ("gpt",)):   # the phone's stop button ends Codex right away
                kill_tree(p.pid)
                flush()
                aim("say", "--kind", "system", stdin="⏹ ChatGPT נעצר לפי בקשתך.")
                aim("status", "state=idle", "activity=-")
                return
            continue
        if line is None:
            break
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        typ, item = ev.get("type"), ev.get("item") or {}
        it = item.get("type")
        if typ == "thread.started" and ev.get("thread_id"):
            threads[conv] = ev["thread_id"]
            st["conv"] = conv
            save_state(st)
        elif typ == "item.started":
            if it != "agent_message":
                flush()
            if it == "command_execution":
                post.activity(cmd_card(item)["title"], force=True)
            elif it == "file_change":
                post.activity("Editing files", force=True)
            elif it == "web_search":
                post.activity("Searching the web", force=True)
        elif typ == "item.completed":
            if it == "agent_message":
                flush()
                pending = (item.get("text") or "").strip() or None
                continue
            flush()
            if it == "reasoning":
                h, rest = headline(item.get("text"))
                if h:
                    post.card({"t": "Reasoning", "title": h, "in": "", "out": rest})
                    post.activity(h, force=True)
            elif it == "command_execution":
                post.card(cmd_card(item))
                post.activity("Thinking")
            elif it == "file_change":
                for ch in item.get("changes") or []:
                    if ch.get("path"):
                        post.card(file_card(ch["path"], ch.get("kind") or "update", cache))
            elif it == "web_search":
                post.card({"t": "Web", "title": item.get("query") or "Web search", "in": item.get("query") or "", "out": ""})
            elif it == "mcp_tool_call":
                name = "%s · %s" % (item.get("server") or "", item.get("tool") or "")
                post.card({"t": "Tool", "title": name.strip(" ·"),
                           "in": json.dumps(item.get("arguments") or {}, ensure_ascii=False)[:3000],
                           "out": json.dumps(item.get("result") or item.get("error") or "", ensure_ascii=False)[:3000]})
            elif it == "todo_list":
                todo = item.get("items") or []
                post.card({"t": "Plan", "title": "%d/%d" % (sum(1 for x in todo if x.get("completed")), len(todo)),
                           "in": "\n".join(("[x] " if x.get("completed") else "[ ] ") + (x.get("text") or "") for x in todo),
                           "out": ""})
            elif it == "error":
                post.card({"t": "Error", "title": (item.get("message") or "Error")[:120], "in": "", "out": item.get("message") or ""})
        elif typ in ("turn.failed", "error"):
            e = ev.get("error")
            failure = (e.get("message") if isinstance(e, dict) else None) or ev.get("message") or "error"
    p.wait()
    answer = pending
    if not answer:
        tail = (failure or "".join(err[-3:]) or "").strip()
        answer = "ChatGPT לא הצליח לענות." + ("\n```\n" + tail[-600:] + "\n```" if tail else "")
        if tid:   # the thread may be gone: start a fresh one next time
            threads.pop(conv, None)
            save_state(st)
    say = ["say", "--kind", "reply"]
    after = snapshot_images()
    new = sorted((x for x, m in after.items() if before.get(x) != m), key=lambda x: after[x])[:4]
    for path in new:
        stored = aim("photo-put", path)
        if stored and "error" not in stored.lower():
            say += ["--image", stored]
    aim(*say, stdin=answer)
    aim("status", "state=idle", "activity=-")


def cmd_run():
    st = load_state()
    publish_cfg()
    while True:
        out = wait_for_phone()
        if out.startswith("AIM stop"):
            time.sleep(15)
            continue
        if not out.startswith("AIM new"):
            time.sleep(5)
            continue
        unread = json.loads(aim("unread") or "[]")
        if unread:
            try:
                turn(unread, st)
            except Exception as e:  # keep the line alive
                aim("say", "--kind", "system", stdin="שגיאה בגשר של ChatGPT: %s" % e)
                aim("status", "state=idle", "activity=-")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "on":
        cmd_on(sys.argv[2] if len(sys.argv) > 2 else os.path.basename(os.getcwd()) or "codex")
    elif cmd == "off":
        cmd_off()
    elif cmd == "run":
        cmd_run()
    elif cmd == "restart":   # reload the loop after a code change, same conversation, line stays on
        pid = read_pid()
        if pid and alive(pid):
            kill_tree(pid)
        log = open(LOG, "ab")
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "run"], stdout=log, stderr=log,
                             stdin=subprocess.DEVNULL, env=ENV, creationflags=0x00000008 | 0x00000200 | 0x08000000,
                             close_fds=True)
        with open(PIDFILE, "w") as f:
            f.write(str(p.pid))
        print("ChatGPT loop restarted (pid %d)" % p.pid)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
