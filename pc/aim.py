"""AIM helper for Claude: read and write the phone chat in Supabase with the secret key.

Usage (text is read from stdin where noted):
  python aim.py unread                      unread phone messages as JSON
  python aim.py seen ID [ID ...]            mark phone messages as read
  python aim.py say [--kind K] [--image P] [--style code|general]  post stdin as a Claude message (K: reply, question, system); --style picks the phone notification look (default: guessed from the text; code = big banner for programming tasks)
  python aim.py status key=value ...        merge fields into the status row ("-" deletes a field)
  python aim.py settings                    print the settings row
  python aim.py photo-get PATH              download a photo from storage, print the local file path
  python aim.py photo-put FILE              upload a photo, print its storage path
  python aim.py newconv [--title T] [--project P]   start a new conversation and make it current
  python aim.py title T                     rename the current conversation
  python aim.py current                     print the conversation replies go to (Claude: where the phone last wrote)
  (team chats, conversation ids starting with "t": see team.py)
  python aim.py mode on|off                 resume or pause the line for all models; also keeps the computer awake (on) or restores it (off)
"""
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HOME = os.path.join(os.path.expanduser("~"), ".aim")
BUCKET = "aim-photos"


def load_env():
    env = {}
    with open(os.path.join(HOME, "secrets.env"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


ENV = load_env()
URL = ENV["SUPABASE_URL"].rstrip("/")
KEY = ENV["SUPABASE_SERVICE_KEY"]


def call(method, path, body=None, headers=None, raw=False):
    h = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        else:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(URL + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            out = r.read()
    except urllib.error.HTTPError as e:
        sys.exit("AIM error %s: %s" % (e.code, e.read().decode("utf-8", "replace")))
    if raw:
        return out
    return json.loads(out) if out else None


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_row(row_id):
    rows = call("GET", "/rest/v1/control?id=eq.%s&select=data" % row_id)
    return rows[0]["data"] if rows else {}


def put_row(row_id, data):
    call("POST", "/rest/v1/control", {"id": row_id, "data": data, "updated_at": now_iso()},
         {"Prefer": "resolution=merge-duplicates,return=minimal"})


# AIM_MODEL: claude (default) | gpt | gemini. ChatGPT and Gemini have their own conversations (ids start with
# "g" / "m"), status row and pause switch; Claude's conversations are "c..." and team chats "t...".
MODEL = os.environ.get("AIM_MODEL") or "claude"
if MODEL not in ("claude", "gpt", "gemini"):
    MODEL = "claude"
GPT = MODEL != "claude"   # a non-Claude bridge
CONV_KEY = {"claude": "conv", "gpt": "gpt", "gemini": "gemini"}[MODEL]
STATUS_ROW = {"claude": "status", "gpt": "status-gpt", "gemini": "status-gemini"}[MODEL]
MODE_KEY = {"claude": "mode", "gpt": "mode_gpt", "gemini": "mode_gemini"}[MODEL]
PREFIX = {"claude": "c", "gpt": "g", "gemini": "m"}[MODEL]
SUFFIX = PREFIX
UNREAD_FILTER = {
    # Claude: the user's messages outside ChatGPT/Gemini chats; in team chats only those addressed "@claude"
    # (the rest is handled by aim_team.py without Claude), plus escalations the free team hands up.
    "claude": "&and=(or(and(sender.eq.me,or(conv.is.null,conv.not.like.t*,text.like.@claude*)),kind.eq.escalate,kind.eq.stop),"
              "or(conv.is.null,and(conv.not.like.g*,conv.not.like.m*)),id.not.like.mv*)",
    "gpt": "&sender=eq.me&conv=like.g*", "gemini": "&sender=eq.me&conv=like.m*"}[MODEL]


LAST = os.path.join(HOME, "last_conv")   # Claude side: the conversation the phone last wrote in (a team chat or a solo one)


def last_conv():
    try:
        with open(LAST, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def current_conv():
    if not GPT:
        # A chat the user opened on the phone (control row "current": {changed, at}) after their last message
        # wins over the chat that message came from.
        row = get_row("current")
        try:
            last_at = os.path.getmtime(LAST) * 1000
        except OSError:
            last_at = 0
        if row.get("changed") in ("claude", "team") and (row.get("at") or 0) > last_at:
            pick = row.get("conv" if row["changed"] == "claude" else "team")
            if pick:
                return pick
        return last_conv() or row.get(CONV_KEY)
    return get_row("current").get(CONV_KEY)


def stop_requested(since_ms, scope):
    """True when the phone's stop button was pressed after since_ms for one of the models in scope
    (control row "stop": {at: ms, model: claude|gpt|gemini|team, conv})."""
    try:
        row = get_row("stop")
    except SystemExit:
        return False
    return (row.get("at") or 0) > since_ms and row.get("model") in scope


def wait_stoppable(futures, scope, since_ms, poll=2.0):
    """Wait for concurrent futures; returns False (and leaves them running, results discarded) if stopped."""
    import concurrent.futures as cf
    pending = set(futures)
    while pending:
        _, pending = cf.wait(pending, timeout=poll)
        if pending and stop_requested(since_ms, scope):
            return False
    return True


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif", ".bmp", ".avif")


def split_files(paths, inline_pdf=False):
    """Phone attachments (local files) -> (images, text). Photos (and PDFs when the model reads them natively) go
    in the first list; text files, and the text of a PDF, are folded into a block to add to the prompt."""
    images, notes = [], []
    for p in paths:
        name = os.path.basename(p).split("_", 2)[-1].split("-", 1)[-1]   # photos/me_<msg>_<n>-<name> -> <name>
        low = p.lower()
        if low.endswith(IMAGE_EXT) or (inline_pdf and low.endswith(".pdf")):
            images.append(p)
            continue
        body = None
        try:
            if low.endswith(".pdf"):
                import pypdf
                body = "\n".join((pg.extract_text() or "") for pg in pypdf.PdfReader(p).pages[:60])
            elif os.path.getsize(p) <= 400_000:
                with open(p, "rb") as f:
                    raw = f.read()
                if b"\0" not in raw[:4096]:
                    body = raw.decode("utf-8", "replace")
        except Exception:
            body = None
        if body and body.strip():
            notes.append("--- attached file: %s ---\n%s\n--- end of %s ---" % (name, body[:60000], name))
        else:
            notes.append("[attached file %s (%d KB) could not be read as text]" % (name, os.path.getsize(p) // 1024))
    return images, "\n\n".join(notes)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    cmd = args[0]

    if cmd == "unread":
        rows = call("GET", "/rest/v1/messages?seen=is.false&order=ts.asc"
                    + UNREAD_FILTER
                    + "&select=id,kind,text,images,reply_to,ts,conv")
        if not GPT and rows:
            conv = rows[-1].get("conv")
            if conv:
                with open(LAST, "w", encoding="utf-8") as f:
                    f.write(conv)
            elif os.path.exists(LAST):
                os.remove(LAST)
        print(json.dumps(rows, ensure_ascii=False))

    elif cmd == "seen":
        ids = ",".join('"%s"' % i for i in args[1:])
        call("PATCH", "/rest/v1/messages?id=in.(%s)" % urllib.parse.quote(ids, safe='",'),
             {"seen": True, "seen_at": now_iso()}, {"Prefer": "return=minimal"})
        print("seen %d" % len(args[1:]))

    elif cmd == "say":
        kind, images, style, title = "reply", [], None, None
        i = 1
        while i < len(args):
            if args[i] == "--kind":
                kind = args[i + 1]; i += 2
            elif args[i] == "--style":
                style = args[i + 1]; i += 2
            elif args[i] == "--title":
                title = args[i + 1]; i += 2
            elif args[i] == "--image":
                images.append(args[i + 1]); i += 2
            else:
                i += 1
        text = sys.stdin.read().strip()
        ts = int(time.time() * 1000)
        row = {"id": "m%d-%s" % (ts, SUFFIX), "sender": "claude", "kind": kind, "text": text, "ts": ts}
        conv = current_conv()
        if conv:
            row["conv"] = conv
        if images:
            row["images"] = images
        call("POST", "/rest/v1/messages", row, {"Prefer": "return=minimal"})
        print("posted " + row["id"])
        if kind in ("reply", "question"):
            try:
                import push
                n = push.send(text, conv, kind, style, title)
                print("push sent to %d phone(s)" % n)
            except Exception:
                pass

    elif cmd == "status":
        data = get_row(STATUS_ROW)
        for pair in args[1:]:
            k, v = pair.split("=", 1)
            if v == "-":
                data.pop(k, None)
            else:
                data[k] = v
        data["updatedAt"] = now_iso()
        put_row(STATUS_ROW, data)
        print(json.dumps(data, ensure_ascii=False))

    elif cmd == "settings":
        print(json.dumps(get_row("settings"), ensure_ascii=False))

    elif cmd == "photo-get":
        path = args[1]
        out = call("GET", "/storage/v1/object/%s/%s" % (BUCKET, urllib.parse.quote(path)), raw=True)
        dest = os.path.join(HOME, "photos", path.replace("/", "_"))
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(out)
        print(dest)

    elif cmd == "photo-put":
        src = args[1]
        ctype = mimetypes.guess_type(src)[0] or "image/jpeg"
        path = "claude/%d-%s" % (int(time.time() * 1000), os.path.basename(src))
        with open(src, "rb") as f:
            call("POST", "/storage/v1/object/%s/%s" % (BUCKET, urllib.parse.quote(path)), f.read(),
                 {"Content-Type": ctype, "x-upsert": "true"})
        print(path)

    elif cmd == "newconv":
        title, project = "", ""
        i = 1
        while i < len(args):
            if args[i] == "--title":
                title = args[i + 1]; i += 2
            elif args[i] == "--project":
                project = args[i + 1]; i += 2
            else:
                i += 1
        cid = "%s%d" % (PREFIX, int(time.time() * 1000))
        if not title:
            title = datetime.now().strftime("%d/%m %H:%M")
        call("POST", "/rest/v1/conversations", {"id": cid, "title": title, "project": project or None},
             {"Prefer": "return=minimal"})
        if not GPT and os.path.exists(LAST):
            os.remove(LAST)
        cur = get_row("current")
        cur[CONV_KEY] = cid
        put_row("current", cur)
        print(cid)

    elif cmd == "title":
        cid = current_conv()
        call("PATCH", "/rest/v1/conversations?id=eq.%s" % cid, {"title": " ".join(args[1:])},
             {"Prefer": "return=minimal"})
        print("renamed " + cid)

    elif cmd == "mode":
        # One switch for both models, and the computer stays awake exactly while the line is on.
        data = get_row("settings")
        was_on = data.get("mode") == "on"
        data["mode"] = data["mode_gpt"] = data["mode_gemini"] = "off" if args[1] == "off" else "on"
        data["changedAt"] = now_iso()
        put_row("settings", data)
        if args[1] != "off" and not was_on:   # every time the line is switched on, wake the phone (vibrate + banner)
            try:
                import push
                push.send("הקו פעיל והמחשב מקשיב. מעכשיו אפשר לכתוב לי מהטלפון. (%s)" % datetime.now().strftime("%H:%M"),
                          current_conv(), "reply", "code", "🟢 הקו הופעל")
            except Exception:
                pass
        import subprocess
        subprocess.run([sys.executable, os.path.join(HOME, "awake.py"), "off" if args[1] == "off" else "on"],
                       capture_output=True)
        subprocess.run([sys.executable, os.path.join(HOME, "aim_voice.py"), "off" if args[1] == "off" else "on"],
                       capture_output=True)   # fast voice mode answers the Siri shortcut without waking Claude
        print(json.dumps(data, ensure_ascii=False))

    elif cmd == "team-members":
        # which models take part in the team chat (default: all three); set from the phone's settings
        conv = args[1] if len(args) > 1 else current_conv()
        print(json.dumps((get_row("team").get(conv) if conv else None) or ["claude", "gpt", "gemini"]))

    elif cmd == "current":
        print(current_conv())

    elif cmd == "doctor":   # check every piece of the setup and say how to fix what is missing
        import subprocess
        sys.exit(subprocess.run([sys.executable, os.path.join(HOME, "doctor.py")] + args[1:]).returncode)

    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
