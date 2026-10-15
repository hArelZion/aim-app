"""AIM team chat: Claude leads and hands work to ChatGPT (and Gemini) inside one shared conversation.

  python team.py ask WHO[,WHO...] [--user] [--conv ID] [--image FILE ...]    prompt on stdin; prints the answer(s)
  python team.py models                                                      list WHO keys (see models.py)

WHO: gpt, gemini, or any key from models.py (gem38f, gpt61sol, gemma26 ...). Several, comma-separated, run in parallel.

Every handoff is posted to the team conversation so the phone shows who is working and what they say to each
other: Claude -> model as kind "agent" (text starts with "@gpt"), the model's answer back as kind "agent"
("@claude"), or with --user as a normal reply from that model (write the prompt so it answers in Hebrew).
Between models any language works (English recommended); only what is addressed to the user must be Hebrew.
Message author = id suffix: -c Claude, -g ChatGPT, -m Gemini.

ChatGPT runs through the Codex CLI (ephemeral session, sandbox, no network, no secrets); Gemini through the
Gemini API (gemini_api.py; needs GEMINI_API_KEY in secrets.env).
"""
import os
import re
import subprocess
import sys
import tempfile
import time

import aim

WORK = os.path.join(aim.HOME, "gpt-work")
NAMES = {"claude": "Claude", "gpt": "ChatGPT", "gemini": "Gemini"}
SUFFIX = {"claude": "c", "gpt": "g", "gemini": "m"}


def registry():
    import models
    return {e["key"]: e for e in models.load()}


def author_suffix(who):
    return SUFFIX.get(who) or "x" + who


def post(author, kind, text, conv, images=None):
    imgs = [m for m in re.findall(r"IMG::(\S+)", text or "")]
    if imgs:   # a generated picture: show it as a normal message from that model
        text = re.sub(r"IMG::\S+", "", re.sub(r"^@[a-z0-9]+\n", "", text)).strip()
        kind, images = "reply", (images or []) + imgs
    ts = int(time.time() * 1000)
    row = {"id": "m%d-%s" % (ts, author_suffix(author)), "sender": "claude", "kind": kind, "text": text, "ts": ts}
    if conv:
        row["conv"] = conv
    if images:
        row["images"] = images
    aim.call("POST", "/rest/v1/messages", row, {"Prefer": "return=minimal"})


def set_status(**kv):
    data = aim.get_row("status")
    for k, v in kv.items():
        if v is None:
            data.pop(k, None)
        else:
            data[k] = v
    data["updatedAt"] = aim.now_iso()
    aim.put_row("status", data)


def run_codex(prompt, images, model=None):
    os.makedirs(WORK, exist_ok=True)
    out = os.path.join(tempfile.gettempdir(), "aim-team-%s.txt" % (model or "gpt"))
    if os.path.exists(out):
        os.remove(out)
    cmd = ["codex", "exec", "--ephemeral", "-C", WORK, "-s", "workspace-write", "--skip-git-repo-check", "-o", out]
    if model:
        cmd += ["-m", model]
    for img in images:
        cmd += ["-i", img]
    cmd += ["-"]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=WORK,
                       shell=(os.name == "nt"), timeout=1800)
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            ans = f.read().strip()
        if ans:
            return ans
    raise RuntimeError("Codex failed: " + (r.stderr or r.stdout or "").strip()[-400:])


def runner(who, reg):
    """-> (display name, function(prompt, images) -> text)"""
    if who == "gpt":
        return "ChatGPT", lambda p, im: run_codex(p, im)
    if who == "gemini":
        import gemini_api
        return "Gemini", lambda p, im: gemini_api.ask(p, im)
    e = reg.get(who)
    if not e:
        sys.exit("unknown model %r (python team.py models)" % who)
    if e["provider"] == "image":
        import image_api
        return e["name"], lambda p, im: image_api.generate(p, e["model"])
    if e["provider"] == "codex":
        return e["name"], lambda p, im: run_codex(p, im, e["model"])
    if e["provider"] == "gemini":
        import gemini_api
        return e["name"], lambda p, im: gemini_api.ask(p, im, only=e["model"])
    import compat_api
    return e["name"], lambda p, im: compat_api.ask(e["provider"], e["model"], p)


def ask(args):
    whos = [w for w in args[0].split(",") if w]
    reg = registry()
    for w in whos:
        if w != "all" and (w == "claude" or (w not in ("gpt", "gemini") and w not in reg)):
            sys.exit(__doc__)
    to_user, conv, images = False, None, []
    i = 1
    while i < len(args):
        if args[i] == "--user":
            to_user = True; i += 1
        elif args[i] == "--conv":
            conv = args[i + 1]; i += 2
        elif args[i] == "--image":
            images.append(args[i + 1]); i += 2
        else:
            i += 1
    conv = conv or aim.current_conv()
    members = (aim.get_row("team").get(conv) if conv else None) or ["claude", "gpt", "gemini"]
    if "all" in whos:   # every FREE member (not Claude, ChatGPT or Codex models, which spend paid quota)
        whos = [m for m in members if m not in ("claude", "gpt") and (m == "gemini" or (m in reg and reg[m]["provider"] not in ("codex", "image")))]
    for w in whos:
        if w not in members:
            sys.exit("%s is not a member of this team chat (members: %s)" % (w, ", ".join(members)))
    if not whos:
        sys.exit("no other members in this team chat")
    prompt = sys.stdin.read().strip()
    prev = aim.get_row("status")
    prev_state, prev_activity = prev.get("state"), prev.get("activity")
    runners = {w: runner(w, reg) for w in whos}
    for w in whos:
        post("claude", "agent", "@%s\n%s" % (w, prompt), conv)
    names = [runners[w][0] for w in whos]
    set_status(state="working", who=whos[0], activity=(names[0] + " עובד") if len(whos) == 1 else "%d מודלים עובדים" % len(whos) + (": " + ", ".join(names) if len(whos) <= 3 else ""))

    def one(w):
        name, fn = runners[w]
        try:
            answer = fn(prompt, images)
        except Exception as e:
            post(w, "agent", "@claude\n(error) %s" % e, conv)
            return w, name, None, str(e)
        post(w, "reply" if to_user else "agent", answer if to_user else "@claude\n" + answer, conv)
        return w, name, answer, None

    from concurrent.futures import ThreadPoolExecutor
    started = int(time.time() * 1000)
    ex = ThreadPoolExecutor(max(1, min(len(whos), 12)))
    futs = [ex.submit(one, w) for w in whos]
    ex.shutdown(wait=False)
    if not aim.wait_stoppable(futs, ("team", "claude"), started):   # the phone's stop button
        set_status(state=prev_state, who="claude", activity=prev_activity)
        print("STOPPED: the user pressed stop on the phone. Stop the task, say what was done so far, and wait.")
        sys.stdout.flush()
        os._exit(3)
    results = [f.result() for f in futs]
    set_status(state=prev_state, who="claude", activity=prev_activity)
    failed = [r for r in results if r[2] is None]
    cap = 1500 if len(results) > 6 else None   # the full answers are in the chat; keep the lead's context small
    for w, name, answer, err in results:
        if len(results) > 1:
            print("=== %s (%s) ===" % (name, w))
        text = answer if answer is not None else "(error) " + err
        print(text if not cap or len(text) <= cap else text[:cap] + " [...cut, full text in the chat]")
    if len(results) > 1:
        print("--- %d answered, %d failed ---" % (len(results) - len(failed), len(failed)))
    if len(failed) == len(results):
        sys.exit(1)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    if a and a[0] == "ask" and len(a) > 1:
        ask(a[1:])
    elif a and a[0] == "models":
        print("gpt (ChatGPT, default)\ngemini (Gemini, newest available)")
        for k, e in registry().items():
            print("%-12s %s (%s)" % (k, e["name"], e["provider"]))
    else:
        sys.exit(__doc__)
