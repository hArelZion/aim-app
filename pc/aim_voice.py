"""AIM fast voice mode: answers the Siri shortcut in about a second, without waking Claude.

  python aim_voice.py on|off        start / stop the background loop (started with the line by `aim.py mode on`)
  python aim_voice.py mode fast|claude   fast = a quick free model answers; claude = everything goes to Claude

Voice messages are the ones created by the shortcut (message id starts with "mv"). In fast mode a fast free Gemini
model answers in one or two spoken sentences; if the request needs the computer, files, the store, code or long
work, it says so and hands the job up to Claude with an "escalate" message (Claude's watcher picks that up).
Claude's own watcher ignores "mv" messages, so there is no double answer.
"""
import os
import re
import subprocess
import sys
import time

import aim
import gemini_api
import team

HOME = aim.HOME
PIDFILE = os.path.join(HOME, "voice.pid")
LOG = os.path.join(HOME, "voice.log")
MODEFILE = os.path.join(HOME, "voice-mode")
FAST_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash"]
SYSTEM = (
    "You are the FAST VOICE MODE of the user's private assistant AIM. Claude, a stronger model on the user's computer, "
    "does the big jobs. Your answer is read aloud, so reply in one or two short plain sentences: no markdown, no lists, "
    "no emojis, no preamble. Reply in the language the user spoke (Hebrew or English). Greetings, chit-chat, questions, jokes and tests (hello, can you hear me) are NEVER escalated: just answer them. "
    "OPENING APPS: unless the user says the computer (PC, laptop, במחשב), they mean their PHONE. For the phone reply "
    "exactly: PHONE: <app> | <short confirmation in the user's language>, with <app> one of: safari, spotify, settings, "
    "maps, messages, phone, mail, music, youtube, whatsapp, instagram, chatgpt, notes, calendar, appstore, photos, "
    "facetime, telegram, tiktok, netflix. If the user says the computer, reply exactly: OPEN: <app> | <confirmation> with "
    "<app> one of: spotify, chrome, edge, notepad, calculator, explorer, downloads, settings, terminal, vscode. "
    "Always reply in the SAME language as the user's latest message (English to English, Hebrew to Hebrew). "
    "Only if the user clearly asks you to DO "
    "something on the computer, in the store, with files or code, or anything that needs tools or long work, reply "
    "exactly: ESCALATE: <a short acknowledgement in the user's language saying you passed it to Claude>. If asked who "
    "you are, say you are the fast voice mode and Claude handles bigger tasks. If the user says they are finished "
    "(סיימתי, done, bye), answer with a very short goodbye."
)


def mode():
    try:
        with open(MODEFILE, encoding="utf-8") as f:
            return "claude" if f.read().strip() == "claude" else "fast"
    except OSError:
        return "fast"


def history(conv, skip_id):
    rows = aim.call("GET", "/rest/v1/messages?conv=eq.%s&order=ts.desc&limit=10&select=id,sender,kind,text" % conv) or []
    out = []
    for m in reversed(rows):
        if m["id"] == skip_id or m["kind"] in ("system", "agent", "escalate") or not m["text"]:
            continue
        r = "user" if m["sender"] == "me" else "model"
        t = re.sub(r"^@[a-z0-9]+\n", "", m["text"])[:500]
        if out and out[-1][0] == r:
            out[-1] = (r, out[-1][1] + "\n" + t)
        else:
            out.append((r, t))
    while out and out[0][0] != "user":
        out.pop(0)
    if out and out[-1][0] == "user":
        out.pop()
    return out


def escalate(conv, text):
    ts = int(time.time() * 1000)
    aim.call("POST", "/rest/v1/messages", {"id": "m%d-c" % ts, "sender": "claude", "kind": "escalate",
                                           "text": "Voice request that needs real work: " + text, "ts": ts,
                                           "seen": False, "conv": conv}, {"Prefer": "return=minimal"})


APPS = {   # apps the voice mode may open on this computer by itself (name -> command); nothing else is ever launched
    "spotify": ["cmd", "/c", "start", "", "spotify:"],
    "chrome": ["cmd", "/c", "start", "", "chrome"],
    "edge": ["cmd", "/c", "start", "", "msedge"],
    "notepad": ["cmd", "/c", "start", "", "notepad"],
    "calculator": ["cmd", "/c", "start", "", "calc"],
    "explorer": ["cmd", "/c", "start", "", "explorer"],
    "downloads": ["cmd", "/c", "start", "", "explorer", "shell:Downloads"],
    "settings": ["cmd", "/c", "start", "", "ms-settings:"],
    "terminal": ["cmd", "/c", "start", "", "wt"],
    "vscode": ["cmd", "/c", "start", "", "code"],
}


PHONE_APPS = {   # iPhone apps by URL scheme: the shortcut opens the URL that voice_open returns
    "safari": "https://www.google.com", "spotify": "spotify://", "settings": "app-prefs:", "maps": "maps://",
    "messages": "sms://", "phone": "tel://", "mail": "message://", "music": "music://", "youtube": "youtube://",
    "whatsapp": "whatsapp://", "instagram": "instagram://", "chatgpt": "chatgpt://", "notes": "mobilenotes://",
    "calendar": "calshow://", "appstore": "itms-apps://", "photos": "photos-redirect://", "facetime": "facetime://",
    "telegram": "tg://", "tiktok": "snssdk1233://", "netflix": "nflx://",
}


def queue_phone_open(url):
    row = aim.get_row("voice")
    row["open_url"] = url
    aim.put_row("voice", row)


def open_app(name):
    cmd = APPS.get(re.sub(r"[^a-z]", "", name.lower()))
    if not cmd:
        return False
    subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x08000000)
    return True


OPEN_WORDS = re.compile(r"\b(open|launch|start|run)\b|פתח|תפתח|תפתחי|הפעל|תפעיל", re.I)
PC_WORDS = re.compile(r"\b(computer|pc|laptop|desktop)\b|במחשב|מחשב", re.I)
APP_NAMES = {   # spoken name -> app key (English words and common Hebrew spellings)
    "safari": "safari", "סאפרי": "safari", "ספארי": "safari", "spotify": "spotify", "ספוטיפיי": "spotify",
    "ספוטיפי": "spotify", "settings": "settings", "הגדרות": "settings", "maps": "maps", "מפות": "maps",
    "messages": "messages", "הודעות": "messages", "mail": "mail", "מייל": "mail", "music": "music", "מוזיקה": "music",
    "youtube": "youtube", "יוטיוב": "youtube", "whatsapp": "whatsapp", "וואטסאפ": "whatsapp", "ווטסאפ": "whatsapp",
    "instagram": "instagram", "אינסטגרם": "instagram", "chatgpt": "chatgpt", "notes": "notes", "הערות": "notes",
    "calendar": "calendar", "יומן": "calendar", "appstore": "appstore", "photos": "photos", "תמונות": "photos",
    "facetime": "facetime", "telegram": "telegram", "טלגרם": "telegram", "tiktok": "tiktok", "טיקטוק": "tiktok",
    "netflix": "netflix", "נטפליקס": "netflix", "chrome": "chrome", "כרום": "chrome", "edge": "edge",
    "notepad": "notepad", "פנקס": "notepad", "calculator": "calculator", "מחשבון": "calculator",
    "explorer": "explorer", "downloads": "downloads", "הורדות": "downloads", "terminal": "terminal",
    "vscode": "vscode", "phone": "phone", "טלפון": "phone",
}


def parse_open(text):
    """-> (target, app key, shown name, hebrew?) when the text is a plain 'open <app>' request, else None."""
    if not OPEN_WORDS.search(text):
        return None
    low = re.sub(r"[^\w\s]", " ", text.lower().replace("app store", "appstore").replace("vs code", "vscode"))
    words = low.split()
    app = None
    for w in words:
        for prefix in ("", "ה", "את", "את ה"):
            if w.startswith(prefix) and w[len(prefix):] in APP_NAMES and w[len(prefix):]:
                app = APP_NAMES[w[len(prefix):]]; break
        if app:
            break
    if not app:
        return None
    heb = any("֐" <= c <= "׿" for c in text)
    pc = bool(PC_WORDS.search(text))
    if pc:
        return ("pc", app, app, heb) if app in APPS else None
    return ("phone", app, app, heb) if app in PHONE_APPS else (("pc", app, app, heb) if app in APPS else None)


def handle(m):
    aim.call("PATCH", "/rest/v1/messages?id=eq.%s" % m["id"], {"seen": True, "seen_at": aim.now_iso()},
             {"Prefer": "return=minimal"})
    conv, text = m.get("conv"), (m.get("text") or "").strip()
    if not text:   # silence: answer with a dot at once so the shortcut's wait ends and it listens again
        team.post("gemini", "reply", ".", conv)
        return
    if mode() == "claude":
        escalate(conv, text)
        return
    direct = parse_open(text)   # "open Netflix" / "תפתח ספוטיפיי": no model needed
    if direct:
        target, app, shown, heb = direct
        if target == "phone":
            queue_phone_open(PHONE_APPS[app])
            team.post("gemini", "reply", ("פותח את %s בטלפון." % shown) if heb else ("Opening %s on your phone." % shown), conv)
        else:
            open_app(app)
            team.post("gemini", "reply", ("פותח את %s במחשב." % shown) if heb else ("Opening %s on the computer." % shown), conv)
        return
    answer = None
    hebrew = any("֐" <= c <= "׿" for c in text)
    prompt = text if hebrew else "(The user spoke English: reply in English only.)\n" + text
    for model in FAST_MODELS:
        try:
            answer = gemini_api.ask(prompt, history=history(conv, m["id"]), only=model, system=SYSTEM, timeout=12)
            break
        except Exception:
            continue
    if answer is None:
        team.post("gemini", "reply", "I could not answer fast, passing this to Claude.", conv)
        escalate(conv, text)
        return
    if answer.upper().startswith("PHONE:"):   # "PHONE: safari | opening Safari"
        body = answer.split(":", 1)[1]
        app, _, ack = body.partition("|")
        url = PHONE_APPS.get(re.sub(r"[^a-z]", "", app.lower()))
        if url:
            queue_phone_open(url)   # before the reply, so the shortcut finds it when the reply arrives
            team.post("gemini", "reply", ack.strip() or ("Opening " + app.strip() + " on your phone."), conv)
        else:
            team.post("gemini", "reply", ("Say Hey Siri, open " + app.strip() + ".") if not hebrew else
                      ("אמור: היי סירי, תפתח " + app.strip() + "."), conv)
        return
    if answer.upper().startswith("OPEN:"):   # "OPEN: spotify | opening Spotify"
        body = answer.split(":", 1)[1]
        app, _, ack = body.partition("|")
        if open_app(app.strip()):
            team.post("gemini", "reply", ack.strip() or ("Opening " + app.strip() + "."), conv)
        else:
            team.post("gemini", "reply", "I can open: " + ", ".join(sorted(APPS)) + "." if not hebrew else
                      "אני יכול לפתוח: " + ", ".join(sorted(APPS)) + ".", conv)
        return
    if answer.upper().startswith("ESCALATE"):
        ack = answer.split(":", 1)[1].strip() if ":" in answer else "Passing this to Claude."
        team.post("gemini", "reply", ack or "Passing this to Claude.", conv)
        escalate(conv, text)
    else:
        team.post("gemini", "reply", answer, conv)


def run():
    while True:
        try:
            rows = aim.call("GET", "/rest/v1/messages?seen=is.false&sender=eq.me&id=like.mv*&order=ts.asc"
                            "&select=id,text,conv,ts") or []
            for m in rows:
                handle(m)
        except SystemExit:
            pass
        except Exception as e:
            print("voice error:", e, flush=True)
        time.sleep(0.6)


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
    if alive(read_pid()):
        print("voice: already on"); return
    log = open(LOG, "ab")
    flags = 0x00000008 | 0x00000200 | 0x08000000
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "run"], stdout=log, stderr=log,
                         stdin=subprocess.DEVNULL, creationflags=flags, close_fds=True)
    with open(PIDFILE, "w") as f:
        f.write(str(p.pid))
    print("voice: on (pid %d), mode %s" % (p.pid, mode()))


def off():
    pid = read_pid()
    if pid and alive(pid):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    try:
        os.remove(PIDFILE)
    except OSError:
        pass
    print("voice: off")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    c = sys.argv[1] if len(sys.argv) > 1 else ""
    if c == "run":
        run()
    elif c == "on":
        on()
    elif c == "off":
        off()
    elif c == "mode" and len(sys.argv) > 2 and sys.argv[2] in ("fast", "claude"):
        with open(MODEFILE, "w", encoding="utf-8") as f:
            f.write(sys.argv[2])
        print("voice mode:", sys.argv[2])
    else:
        sys.exit(__doc__)
