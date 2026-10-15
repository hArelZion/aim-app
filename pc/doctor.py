"""AIM doctor: checks every piece of an AIM setup on this computer and says how to fix what is missing.

  python ~/.aim/doctor.py        (or: python ~/.aim/aim.py doctor)
  python ~/.aim/doctor.py --phone   also store the result in control row "doctor" for the phone's settings panel

Nothing secret is printed. Exit code 0 when everything needed works, 1 otherwise.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

HOME = os.path.join(os.path.expanduser("~"), ".aim")
CLAUDE = os.path.join(os.path.expanduser("~"), ".claude")
CODEX = os.path.join(os.path.expanduser("~"), ".codex")
OK, BAD, OPT = "OK  ", "FAIL", "--  "
results = []


def report(state, name, detail="", fix=""):
    results.append({"state": state.strip(), "name": name, "detail": detail, "fix": fix})
    line = "[%s] %s" % (state, name) + (": " + detail if detail else "")
    print(line)
    if fix and state != OK:
        print("       fix: " + fix)


def secrets():
    d = {}
    try:
        with open(os.path.join(HOME, "secrets.env"), encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    d[k.strip()] = v.strip().strip('"')
    except OSError:
        pass
    return d


def rest(env, path, method="GET"):
    req = urllib.request.Request(env["SUPABASE_URL"].rstrip("/") + path, method=method,
                                 headers={"apikey": env["SUPABASE_SERVICE_KEY"],
                                          "Authorization": "Bearer " + env["SUPABASE_SERVICE_KEY"]})
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read()
    return json.loads(body) if body else None


def bash_path():
    for c in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"):
        if os.path.exists(c):
            return c
    return shutil.which("bash")


def main():
    print("AIM doctor\n")
    # tools
    report(OK if sys.version_info >= (3, 10) else BAD, "Python", sys.version.split()[0], "install Python 3.10+ from python.org")
    b = bash_path()
    report(OK if b else BAD, "Git Bash", b or "not found", "install Git for Windows: https://git-scm.com/download/win")
    report(OK if shutil.which("curl") else BAD, "curl", "", "comes with Windows 10+ and Git for Windows")
    missing = []
    for mod in ("PIL", "pypdf", "pywebpush", "cryptography") + (("comtypes",) if os.name == "nt" else ()):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    report(OK if not missing else BAD, "Python packages", "missing " + ", ".join(missing) if missing else "all installed",
           "python -m pip install Pillow pypdf pywebpush cryptography comtypes")
    report(OK if shutil.which("claude") or os.path.isdir(CLAUDE) else BAD, "Claude Code", "",
           "install Claude Code: https://claude.com/claude-code")
    codex = shutil.which("codex")
    report(OK if codex else OPT, "Codex CLI (ChatGPT)", "found" if codex else "not installed (ChatGPT mode will not answer)",
           "npm i -g @openai/codex, then run: codex login")

    # files
    env = secrets()
    need = ["SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY", "AIM_EMAIL", "AIM_PAGE_URL"]
    gone = [k for k in need if not env.get(k)]
    report(OK if not gone else BAD, "secrets.env", "missing " + ", ".join(gone) if gone else "all settings present",
           "run the installer again: python install.py")
    report(OK if env.get("GEMINI_API_KEY") else OPT, "Gemini key", "set" if env.get("GEMINI_API_KEY") else "not set (Gemini mode will not answer)",
           "free key: https://aistudio.google.com/apikey -> add GEMINI_API_KEY=... to ~/.aim/secrets.env")
    for f in ("aim.py", "watch.sh", "aim_tool.py", "aim_gpt.py", "push.py"):
        if not os.path.exists(os.path.join(HOME, f)):
            report(BAD, "AIM scripts", f + " missing in ~/.aim", "run the installer again: python install.py")
            break
    else:
        report(OK, "AIM scripts", "in ~/.aim")
    skills = [s for s in ("phone", "phone-off", "phone-new") if not os.path.exists(os.path.join(CLAUDE, "skills", s, "SKILL.md"))]
    report(OK if not skills else BAD, "/phone commands for Claude", "missing " + ", ".join(skills) if skills else "installed",
           "run the installer again: python install.py")
    try:
        hooks = json.load(open(os.path.join(CLAUDE, "settings.json"), encoding="utf-8")).get("hooks") or {}
        have = [ev for ev in ("PreToolUse", "PostToolUse", "Stop", "PermissionRequest")
                if any("aim_tool.py" in (x.get("command") or "") for h in hooks.get(ev, []) for x in h.get("hooks", []))]
    except (OSError, ValueError):
        have = []
    report(OK if len(have) == 4 else BAD, "Step cards and permissions (hooks)", "%d of 4 installed" % len(have),
           "run the installer again: python install.py")
    report(OK if os.path.exists(os.path.join(HOME, "vapid_private.pem")) else BAD, "Push notification key", "",
           "python ~/.aim/push.py publish-key")

    # Supabase
    if not gone:
        try:
            rest(env, "/rest/v1/messages?select=id&limit=1")
            rest(env, "/rest/v1/conversations?select=id&limit=1")
            report(OK, "Supabase tables", "messages, control, conversations")
        except Exception as e:
            report(BAD, "Supabase tables", str(e)[:120], "run sql/setup.sql in Supabase -> SQL Editor (the installer copies it for you)")
        try:
            rest(env, "/storage/v1/bucket/aim-photos")
            report(OK, "Photo storage", "bucket aim-photos")
        except Exception as e:
            report(BAD, "Photo storage", str(e)[:120], "run sql/setup.sql again (it creates the aim-photos bucket)")
        try:
            row = rest(env, "/rest/v1/control?id=eq.push-key&select=data")
            report(OK if row else BAD, "Push key on the phone side", "published" if row else "not published", "python ~/.aim/push.py publish-key")
            w = rest(env, "/rest/v1/control?id=eq.watcher&select=data")
            at = (w[0]["data"] or {}).get("at") if w else None
            if at:
                age = time.time() - __import__("calendar").timegm(time.strptime(at, "%Y-%m-%dT%H:%M:%SZ"))
                report(OK if age < 90 else OPT, "Phone line", "listening" if age < 90 else "off (last seen %d min ago)" % (age // 60),
                       "type /phone in a Claude Code session")
            else:
                report(OPT, "Phone line", "never turned on", "type /phone in a Claude Code session")
        except Exception as e:
            report(BAD, "Supabase control rows", str(e)[:120], "run sql/setup.sql in Supabase -> SQL Editor")
    if env.get("AIM_PAGE_URL"):
        try:
            with urllib.request.urlopen(env["AIM_PAGE_URL"], timeout=15) as r:
                page = r.read(4000).decode("utf-8", "ignore")
            report(OK if "AIM" in page else BAD, "Phone page", env["AIM_PAGE_URL"], "turn on GitHub Pages for your fork (Settings -> Pages -> main / root)")
        except Exception as e:
            report(BAD, "Phone page", str(e)[:100], "turn on GitHub Pages for your fork (Settings -> Pages -> main / root)")

    bad = [r for r in results if r["state"] == "FAIL"]
    print("\n" + ("Everything needed works." if not bad else "%d thing(s) to fix (see 'fix' above)." % len(bad)))
    if "--phone" in sys.argv and not gone:
        try:
            sys.path.insert(0, HOME)
            import aim
            aim.put_row("doctor", {"at": int(time.time() * 1000), "results": results})
        except Exception:
            pass
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
