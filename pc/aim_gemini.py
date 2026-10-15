"""AIM line for Gemini: the same idea as aim_gpt.py, for the Gemini side of the app.

  python aim_gemini.py on [project]   connect: new Gemini conversation, start the background loop
  python aim_gemini.py off            disconnect: stop the loop and mark the line off
  python aim_gemini.py run            the loop itself (started by "on")

watch.sh gemini polls Supabase with curl (free while idle) and returns when the phone sent a message in a Gemini
conversation (ids starting with "m"). The answer comes from the Gemini API (gemini_api.py: no tools, no network
access for the model, no secrets in the prompt); this script does all the chat I/O.
"""
import os
import shutil
import subprocess
import sys
import time

os.environ["AIM_MODEL"] = "gemini"
import aim  # noqa: E402  (reads AIM_MODEL: Gemini conversations, status row, pause switch, "-m" ids)
import gemini_api  # noqa: E402

HOME = aim.HOME
PIDFILE = os.path.join(HOME, "gemini.pid")
LOG = os.path.join(HOME, "gemini.log")
HISTORY = 14   # earlier messages of the conversation sent along as context


def bash_exe():
    for c in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if os.path.exists(c):
            return c
    return shutil.which("bash") or "bash"


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


def say(text, kind="reply"):
    ts = int(time.time() * 1000)
    row = {"id": "m%d-m" % ts, "sender": "claude", "kind": kind, "text": text, "ts": ts}
    conv = aim.current_conv()
    if conv:
        row["conv"] = conv
    aim.call("POST", "/rest/v1/messages", row, {"Prefer": "return=minimal"})


def status(**kv):
    data = aim.get_row(aim.STATUS_ROW)
    for k, v in kv.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    data["updatedAt"] = aim.now_iso()
    aim.put_row(aim.STATUS_ROW, data)


def cmd_on(project):
    if alive(read_pid()):
        print("already running (pid %d)" % read_pid())
        return
    subprocess.run([sys.executable, os.path.join(HOME, "awake.py"), "on"], capture_output=True)
    data = aim.get_row("settings")
    data["mode_gemini"] = "on"
    data["changedAt"] = aim.now_iso()
    aim.put_row("settings", data)
    cid = "m%d" % int(time.time() * 1000)
    aim.call("POST", "/rest/v1/conversations", {"id": cid, "title": time.strftime("%d/%m %H:%M"), "project": project},
             {"Prefer": "return=minimal"})
    cur = aim.get_row("current")
    cur["gemini"] = cid
    aim.put_row("current", cur)
    status(state="idle", project=project, activity=None)
    say("מחובר · " + project, "system")
    log = open(LOG, "ab")
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "run"], stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    with open(PIDFILE, "w") as f:
        f.write(str(p.pid))
    print("Gemini line is on (pid %d). Log: %s" % (p.pid, LOG))


def cmd_off():
    data = aim.get_row("settings")
    data["mode_gemini"] = "off"
    data["changedAt"] = aim.now_iso()
    aim.put_row("settings", data)
    pid = read_pid()
    if pid and alive(pid):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    status(state="off", activity=None)
    say("הקו הושהה.", "system")
    print("Gemini line is off.")


def turn(unread):
    aim.call("PATCH", "/rest/v1/messages?id=in.(%s)" % ",".join('"%s"' % m["id"] for m in unread),
             {"seen": True, "seen_at": aim.now_iso()}, {"Prefer": "return=minimal"})
    conv = unread[-1].get("conv") or aim.current_conv()
    unread = [m for m in unread if m.get("kind") != "stop"]   # a stop with nothing running: just mark it read
    if not unread:
        status(state="idle", activity=None)
        return
    started = int(time.time() * 1000)
    status(state="working", activity="Gemini חושב")
    texts, images = [], []
    for m in unread:
        if m.get("text"):
            texts.append(m["text"])
        for path in m.get("images") or []:
            data = aim.call("GET", "/storage/v1/object/%s/%s" % (aim.BUCKET, aim.urllib.parse.quote(path)), raw=True)
            local = os.path.join(HOME, "photos", path.replace("/", "_"))
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(data)
            images.append(local)
    images, extra = aim.split_files(images, inline_pdf=True)   # Gemini reads photos and PDFs natively
    if extra:
        texts.append(extra)
    ids = {m["id"] for m in unread}
    prior = aim.call("GET", "/rest/v1/messages?conv=eq.%s&order=ts.desc&limit=%d&select=id,sender,kind,text"
                     % (conv, HISTORY + len(unread))) or []
    history = [("user" if m["sender"] == "me" else "model", m["text"]) for m in reversed(prior)
               if m["id"] not in ids and m["kind"] not in ("system", "agent") and m["text"]]
    while history and history[0][0] != "user":
        history.pop(0)
    merged = []   # the API wants strictly alternating roles
    for r, t in history:
        if merged and merged[-1][0] == r:
            merged[-1] = (r, merged[-1][1] + "\n\n" + t)
        else:
            merged.append((r, t))
    if merged and merged[-1][0] == "user":
        merged.pop()
    def run():
        try:
            return gemini_api.ask("\n\n".join(texts) or "(תמונה)", images, merged)
        except Exception as e:
            return "Gemini לא הצליח לענות.\n```\n%s\n```" % e
    from concurrent.futures import ThreadPoolExecutor
    ex = ThreadPoolExecutor(1)
    fut = ex.submit(run)
    ex.shutdown(wait=False)
    if not aim.wait_stoppable([fut], ("gemini",), started):   # the phone's stop button: drop the answer
        say("⏹ Gemini נעצר לפי בקשתך.", "system")
        status(state="idle", activity=None)
        return
    answer = fut.result()
    say(answer)
    status(state="idle", activity=None)


def cmd_run():
    while True:
        r = subprocess.run([bash_exe(), os.path.join(HOME, "watch.sh"), "gemini"], capture_output=True, text=True,
                           encoding="utf-8")
        out = r.stdout.strip()
        if out.startswith("AIM stop"):
            time.sleep(15)
            continue
        if not out.startswith("AIM new"):
            time.sleep(5)
            continue
        unread = aim.call("GET", "/rest/v1/messages?sender=eq.me&seen=is.false&order=ts.asc&conv=like.m*"
                          "&select=id,kind,text,images,reply_to,ts,conv") or []
        if unread:
            try:
                turn(unread)
            except Exception as e:  # keep the line alive
                say("שגיאה בגשר של Gemini: %s" % e, "system")
                status(state="idle", activity=None)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "on":
        cmd_on(sys.argv[2] if len(sys.argv) > 2 else os.path.basename(os.getcwd()) or "gemini")
    elif cmd == "off":
        cmd_off()
    elif cmd == "run":
        cmd_run()
    elif cmd == "restart":   # reload the loop after a code change, same conversation, line stays on
        pid = read_pid()
        if pid and alive(pid):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        log = open(LOG, "ab")
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "run"], stdout=log, stderr=log,
                             stdin=subprocess.DEVNULL, creationflags=0x00000008 | 0x00000200 | 0x08000000,
                             close_fds=True)
        with open(PIDFILE, "w") as f:
            f.write(str(p.pid))
        print("Gemini loop restarted (pid %d)" % p.pid)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
