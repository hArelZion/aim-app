"""Web Push for AIM: wake the phone (vibrate + banner) even when the app is asleep or the screen is locked.

The page stores each phone's push subscription in the `control` row "push" ({"subs": [...]}). `send()` is called by
`aim.py say` after a reply or question is posted. The VAPID private key lives in vapid_private.pem (this folder only).
Best effort: any failure is swallowed so a push problem never blocks the chat.
"""
import json
import os
import re
import time

HOME = os.path.join(os.path.expanduser("~"), ".aim")
KEYFILE = os.path.join(HOME, "vapid_private.pem")


def _owner_email():
    try:
        with open(os.path.join(HOME, "secrets.env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("AIM_EMAIL="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "aim@example.com"


CLAIMS_SUB = "mailto:" + _owner_email()   # Web Push asks for a contact address: the owner's own email


def _plain(text, n=120):
    t = re.sub(r"```.*?```", " ", text or "", flags=re.S)
    t = re.sub(r"[*_`#>\[\]]", "", t)
    return re.sub(r"\s+", " ", t).strip()[:n]


CODE_HINT = re.compile(r"```|\.(py|js|ts|html|css|json|sh|md)\b|\b(commit|push|git|bug|deploy|build|refactor|api)\b|קוד|קובץ|באג|פונקציה|ספרי", re.I)


def pick_style(text, style=None):
    """code = big-picture banner (programming tasks), general = dark card with buttons (everything else)."""
    if style in ("code", "general"):
        return style
    return "code" if CODE_HINT.search(text or "") else "general"


def make_title(kind, style, text, ios=False):
    # iPhone shows no big banner and no buttons, so the look is carried by an emoji in the title instead
    if kind == "question":
        return "❓ Claude שואל אותך" if ios else "Claude שואל אותך"
    if len(text or "") > 300:
        if style == "code":
            return "💻 Claude סיים את המשימה" if ios else "Claude סיים את המשימה"
        return "✅ המשימה הושלמה" if ios else "✓ המשימה הושלמה"
    return "💬 Claude ענה" if ios else "Claude ענה"


def _app_visible(aim):
    """True while the phone's page reports it is on screen (it pings every 20 s; older than 50 s counts as gone)."""
    try:
        p = aim.get_row("presence") or {}
        return bool(p.get("visible")) and (time.time() * 1000 - float(p.get("ts") or 0)) < 50000
    except Exception:
        return False


def send(text, conv=None, kind="reply", style=None, title=None, force=False, url=None, row="push"):
    """`row`: the control row holding the subscriptions ("push" = the AIM chat)."""
    try:
        from pywebpush import webpush, WebPushException
        import aim
        subs = (aim.get_row(row) or {}).get("subs") or []
        if not subs or not os.path.exists(KEYFILE):
            return 0
        if not force and _app_visible(aim):
            return 0
        style = pick_style(text, style)
        def payload_for(sub):
            ios = "web.push.apple.com" in (sub.get("endpoint") or "")
            return json.dumps({"title": title or make_title(kind, style, text, ios), "body": _plain(text), "conv": conv or "",
                               "style": style, "kind": kind, "url": url or ""}, ensure_ascii=False)
        alive, sent = [], 0
        for s in subs:
            try:
                webpush(subscription_info=s, data=payload_for(s), vapid_private_key=KEYFILE,
                        vapid_claims={"sub": CLAIMS_SUB}, ttl=3600, timeout=10)
                alive.append(s); sent += 1
            except WebPushException as e:
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code not in (404, 410):   # gone subscriptions are dropped, anything else is kept
                    alive.append(s)
            except Exception:
                alive.append(s)
        if len(alive) != len(subs):
            aim.put_row(row, {"subs": alive})
        return sent
    except Exception:
        return 0


def make_keys():
    """Create this computer's VAPID key pair (once) and return the public key the phone subscribes with."""
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    if os.path.exists(KEYFILE):
        with open(KEYFILE, "rb") as f:
            key = serialization.load_pem_private_key(f.read(), password=None)
    else:
        key = ec.generate_private_key(ec.SECP256R1())
        with open(KEYFILE, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
    raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["publish-key"]:   # run by the installer: the page reads the public key from control row "push-key"
        sys.path.insert(0, HOME)
        import aim
        pub = make_keys()
        aim.put_row("push-key", {"public": pub})
        print("push key published")
    else:
        sys.exit("usage: python push.py publish-key")
