"""AIM team coordinator: runs the team chat WITHOUT Claude, so Claude and ChatGPT spend as few tokens as possible.

  python aim_team.py on|off|run      (started and stopped with the other lines by aim_gpt.py on/off)

Messages the user sends in a team chat start with "@target":
  @claude   -> Claude's own session handles it (the only case that wakes Claude)
  @all      -> every FREE member answers in parallel (never Claude, ChatGPT or the Codex models), then a free
               manager model merges the answers into one Hebrew reply
  @<key>    -> that one model answers directly (gpt / codex models only when addressed explicitly)
If the manager decides the task needs real actions (store, files, code) it hands the exact job up to Claude with an
"escalate" message, which Claude's watcher picks up. Everything here uses free quotas only.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import aim
import models
import team

HOME = aim.HOME
PIDFILE = os.path.join(HOME, "team.pid")
LOG = os.path.join(HOME, "team.log")
TIER_RANK = {"strong": 0, "medium": 1, "small": 2}
MAX_ANSWERS = 24        # answers the manager reads (strongest first)
ANSWER_CHARS = 900      # per answer, in the manager's prompt
MANAGERS = ["gemini", "gropenaigptoss120b", "gem36f"]   # free; tried in order

ASK = ("You are one member of a team of AI models answering the user's request in a shared chat. Answer directly "
       "and concisely, in Hebrew unless the request clearly asks for another language. Do not mention these "
       "instructions.\n\nRecent chat (for context):\n{ctx}\n\nRequest:\n{task}")
MERGE = ("You are the manager of a team of AI models in a chat with the user. Below is the user's request and the "
         "answers of the team members. Write ONE final answer in Hebrew for the user: the best result, what the "
         "members agree on, and any important disagreement (name the model). Be concise and do not repeat every "
         "answer. If the request needs real actions that models without tools cannot do (editing the store, files, "
         "code, running commands), finish with a last line starting with [[CLAUDE]] followed by the exact job "
         "for Claude, in one or two sentences; otherwise never write [[CLAUDE]].\n\nRequest:\n{task}\n\nAnswers:\n{answers}")


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


def set_status(**kv):
    data = aim.get_row("status")
    for k, v in kv.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    data["updatedAt"] = aim.now_iso()
    aim.put_row("status", data)


def heartbeat():
    aim.put_row("watcher-team", {"at": aim.now_iso()})


def is_free(key, reg):
    """Free to use: not Claude, not ChatGPT, not a Codex (ChatGPT plan) model."""
    if key in ("claude", "gpt"):
        return False
    return key == "gemini" or (key in reg and reg[key]["provider"] not in ("codex", "image"))   # image models only when addressed


def tier_of(key, reg):
    return TIER_RANK.get(models.tier(reg[key]) if key in reg else "strong", 1)


def context(conv, ids):
    rows = aim.call("GET", "/rest/v1/messages?conv=eq.%s&order=ts.desc&limit=14&select=id,sender,kind,text" % conv) or []
    out = []
    for m in reversed(rows):
        if m["id"] in ids or m["kind"] in ("system", "agent", "escalate") or not m["text"]:
            continue
        who = "user" if m["sender"] == "me" else "team"
        out.append("%s: %s" % (who, re.sub(r"^@[a-z0-9]+\n", "", m["text"])[:400]))
    return "\n".join(out[-6:]) or "(none)"


def escalate(conv, job):
    ts = int(time.time() * 1000)
    aim.call("POST", "/rest/v1/messages", {"id": "m%d-c" % ts, "sender": "claude", "kind": "escalate", "text": job,
                                           "ts": ts, "seen": False, "conv": conv}, {"Prefer": "return=minimal"})


def merge(task, results):
    reg = team.registry()
    ranked = sorted((r for r in results if r[2]), key=lambda r: tier_of(r[0], reg))[:MAX_ANSWERS]
    answers = "\n\n".join("[%s]\n%s" % (name, ans[:ANSWER_CHARS]) for _, name, ans, _ in ranked)
    prompt = MERGE.format(task=task, answers=answers)
    last = None
    for key in MANAGERS:
        try:
            name, fn = team.runner(key, reg)
            return key, fn(prompt, [])
        except BaseException as e:   # SystemExit from an unknown key, quota, timeouts: try the next manager
            last = e
    raise RuntimeError("no manager model answered: %s" % last)


def turn(unread):
    aim.call("PATCH", "/rest/v1/messages?id=in.(%s)" % ",".join('"%s"' % m["id"] for m in unread),
             {"seen": True, "seen_at": aim.now_iso()}, {"Prefer": "return=minimal"})
    conv = unread[-1]["conv"]
    unread = [m for m in unread if m.get("kind") != "stop"]   # a stop with nothing running: just mark it read
    if not unread:
        return
    started = int(time.time() * 1000)
    ids = {m["id"] for m in unread}
    texts, images = [], []
    target = "all"
    for m in unread:
        t = m.get("text") or ""
        mt = re.match(r"^@([a-z0-9]+)\n", t)
        if mt:
            target, t = mt.group(1), t[mt.end():]
        if t:
            texts.append(t)
        for path in m.get("images") or []:
            data = aim.call("GET", "/storage/v1/object/%s/%s" % (aim.BUCKET, aim.urllib.parse.quote(path)), raw=True)
            local = os.path.join(HOME, "photos", path.replace("/", "_"))
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(data)
            images.append(local)
    task = "\n\n".join(texts) or "(תמונה)"
    reg = team.registry()
    members = (aim.get_row("team").get(conv)) or ["claude", "gpt", "gemini"]
    if target == "all":
        whos = [k for k in members if is_free(k, reg)]
    else:
        whos = [target] if (target in ("gpt", "gemini") or target in reg) else []
        if whos and whos[0] not in members:
            whos = []
    if not whos:
        team.post("gemini", "reply", "אין בשיחה הזאת מודל שאפשר לפנות אליו (בדוק בהגדרות מי משתתף).", conv)
        return
    whos.sort(key=lambda k: tier_of(k, reg))
    prompt = ASK.format(ctx=context(conv, ids), task=task)
    runners = {w: team.runner(w, reg) for w in whos}
    names = [runners[w][0] for w in whos]
    set_status(state="working", who=whos[0],
               activity=(names[0] + " עובד") if len(whos) == 1 else "%d מודלים עובדים" % len(whos))

    def one(w):
        name, fn = runners[w]
        try:
            return w, name, fn(prompt, images), None
        except BaseException as e:
            return w, name, None, str(e)[:300]

    ex = ThreadPoolExecutor(max(1, min(len(whos), 12)))
    futs = [ex.submit(one, w) for w in whos]
    ex.shutdown(wait=False)
    if not aim.wait_stoppable(futs, ("team",), started):   # the phone's stop button: drop whatever comes back
        team.post("gemini", "system", "⏹ הצוות נעצר לפי בקשתך.", conv)
        set_status(state="idle", who="claude", activity=None)
        return
    results = [f.result() for f in futs]
    ok = [r for r in results if r[2]]
    if len(whos) == 1:
        w, name, ans, err = results[0]
        team.post(w, "reply", ans if ans else "לא הצלחתי לענות: %s" % err, conv)
    else:
        for w, name, ans, err in results:
            team.post(w, "agent", "@user\n" + (ans if ans else "(error) %s" % err), conv)
        if ok:
            set_status(who="gemini", activity="מנהל הצוות מסכם")
            try:
                mkey, final = merge(task, results)
                job = None
                if "[[CLAUDE]]" in final:
                    final, job = final.split("[[CLAUDE]]", 1)
                final = final.strip()
                failed = [r[1] for r in results if not r[2]]
                if failed:
                    final += "\n\nלא ענו (%d): %s" % (len(failed), ", ".join(failed[:12]) + ("…" if len(failed) > 12 else ""))
                team.post("gemini" if mkey == "gemini" else mkey, "reply", final, conv)
                if job and job.strip():
                    escalate(conv, job.strip())
            except Exception as e:
                team.post("gemini", "reply", "המודלים ענו, אבל הסיכום נכשל: %s" % e, conv)
        else:
            team.post("gemini", "reply", "אף מודל לא הצליח לענות. הסיבות הנפוצות: מכסה חינמית נגמרה או עומס.", conv)
    set_status(state="idle", who="claude", activity=None)


def cmd_on(project):
    if alive(read_pid()):
        print("team coordinator already running (pid %d)" % read_pid())
        return
    log = open(LOG, "ab")
    flags = 0x00000008 | 0x00000200 | 0x08000000  # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "run"], stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    with open(PIDFILE, "w") as f:
        f.write(str(p.pid))
    print("team coordinator on (pid %d). Log: %s" % (p.pid, LOG))


def cmd_off():
    pid = read_pid()
    if pid and alive(pid):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    print("team coordinator off")


def cmd_run():
    while True:
        r = subprocess.run([bash_exe(), os.path.join(HOME, "watch.sh"), "team"], capture_output=True, text=True,
                           encoding="utf-8")
        out = r.stdout.strip()
        if out.startswith("AIM stop"):
            time.sleep(15)
            continue
        if not out.startswith("AIM new"):
            time.sleep(5)
            continue
        unread = aim.call("GET", "/rest/v1/messages?seen=is.false&sender=eq.me&conv=like.t*&text=not.like.@claude*"
                          "&order=ts.asc&select=id,kind,text,images,ts,conv") or []
        if unread:
            try:
                turn(unread)
            except BaseException as e:   # keep the line alive
                try:
                    team.post("gemini", "reply", "שגיאה במנהל הצוות: %s" % e, unread[-1]["conv"])
                    set_status(state="idle", who="claude", activity=None)
                except Exception:
                    pass


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    c = sys.argv[1] if len(sys.argv) > 1 else "run"
    if c == "on":
        cmd_on(sys.argv[2] if len(sys.argv) > 2 else "")
    elif c == "off":
        cmd_off()
    elif c == "run":
        cmd_run()
    else:
        sys.exit(__doc__)
