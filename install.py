"""AIM (AI Manager) installer for Windows.

    python install.py

Run it from your fork of the AIM repo. It checks what is installed, asks for your Supabase project details,
prepares the database script (copied to the clipboard), installs the computer scripts in ~/.aim, the /phone
commands for Claude Code and Codex, the Claude Code hooks, and shows a QR code that sets up the phone page.
Re-running it is safe: it keeps what is already there and backs up anything it replaces.
"""
import base64
import datetime
import getpass
import json
import os
import secrets
import shutil
import subprocess
import sys
import urllib.request
import webbrowser

REPO = os.path.dirname(os.path.abspath(__file__))
USER = os.path.expanduser("~")
HOME = os.path.join(USER, ".aim")
CLAUDE = os.path.join(USER, ".claude")
CODEX = os.path.join(USER, ".codex")
STAMP = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
PACKAGES = ["Pillow", "pypdf", "pywebpush", "cryptography", "qrcode"] + (["comtypes"] if os.name == "nt" else [])
HOOK_EVENTS = {"PreToolUse": "*", "PostToolUse": "*", "Stop": None, "PermissionRequest": "*"}


def say(s=""):
    print(s, flush=True)


def step(n, s):
    say("\n== %d. %s" % (n, s))


def ask(label, current="", secret=False, check=None, optional=False):
    while True:
        hint = " [press Enter to keep the current one]" if current else (" [optional, Enter to skip]" if optional else "")
        v = (getpass.getpass if secret else input)("%s%s: " % (label, hint)).strip().strip('"')
        if not v:
            if current or optional:
                return current
            continue
        if check and not check(v):
            say("   That doesn't look right, please try again.")
            continue
        return v


def read_env(path):
    d = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    d[k.strip()] = v.strip().strip('"')
    return d


def write_env(path, d):
    lines, seen = [], set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f.read().split("\n"):
                k = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
                if k in d:
                    lines.append("%s=%s" % (k, d[k])); seen.add(k)
                else:
                    lines.append(line)
    else:
        lines = ["# AIM settings. Secret: never share, never commit, never paste into a chat."]
    lines += ["%s=%s" % (k, v) for k, v in d.items() if k not in seen and v]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")


def backup(path):
    if os.path.exists(path):
        dst = os.path.join(HOME, "backup-" + STAMP, os.path.relpath(path, USER))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        (shutil.copytree if os.path.isdir(path) else shutil.copy2)(path, dst)


def check_tools():
    step(1, "Checking this computer")
    if os.name != "nt":
        say("   AIM's computer side runs on Windows for now. Mac/Linux support is planned.")
        sys.exit(1)
    if sys.version_info < (3, 10):
        sys.exit("   Python 3.10 or newer is needed: https://www.python.org/downloads/")
    bash = next((c for c in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe") if os.path.exists(c)), shutil.which("bash"))
    say("   Python %s: ok" % sys.version.split()[0])
    say("   Git Bash: " + ("ok" if bash else "MISSING. Install Git for Windows: https://git-scm.com/download/win"))
    say("   Claude Code: " + ("ok" if shutil.which("claude") or os.path.isdir(CLAUDE) else "MISSING. Install it: https://claude.com/claude-code"))
    say("   Codex CLI (for ChatGPT, optional): " + ("ok" if shutil.which("codex") else "not installed. Later: npm i -g @openai/codex, then codex login"))
    if not bash:
        sys.exit("\nInstall Git for Windows first, then run this installer again.")
    say("   Installing Python packages: " + ", ".join(PACKAGES))
    r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--upgrade"] + PACKAGES)
    if r.returncode:
        sys.exit("   pip failed. Run: python -m pip install " + " ".join(PACKAGES))


def collect():
    step(2, "Your Supabase project and phone page")
    say("   Create a free project at https://supabase.com (any name, any region).")
    say("   You'll find the values below in Project Settings -> API Keys, and the URL in Project Settings -> Data API.")
    env_path = os.path.join(HOME, "secrets.env")
    cur = read_env(env_path)
    d = {}
    d["SUPABASE_URL"] = ask("   Project URL (https://xxxx.supabase.co)", cur.get("SUPABASE_URL", ""),
                            check=lambda v: v.startswith("https://") and ".supabase." in v).rstrip("/")
    d["SUPABASE_ANON_KEY"] = ask("   Publishable key (sb_publishable_...)", cur.get("SUPABASE_ANON_KEY", ""),
                                 check=lambda v: v.startswith(("sb_publishable_", "eyJ")))
    d["SUPABASE_SERVICE_KEY"] = ask("   Secret key (sb_secret_..., typing is hidden)", cur.get("SUPABASE_SERVICE_KEY", ""), secret=True,
                                    check=lambda v: v.startswith(("sb_secret_", "eyJ")))
    d["AIM_EMAIL"] = ask("   The email you'll sign in with on the phone", cur.get("AIM_EMAIL", ""), check=lambda v: "@" in v and "." in v)
    say("   Your phone page is your fork on GitHub Pages: https://<your-github-name>.github.io/<repo-name>/")
    d["AIM_PAGE_URL"] = ask("   Phone page URL", cur.get("AIM_PAGE_URL", ""), check=lambda v: v.startswith("https://"))
    if not d["AIM_PAGE_URL"].endswith("/"):
        d["AIM_PAGE_URL"] += "/"
    d["GEMINI_API_KEY"] = ask("   Gemini API key for Gemini mode (free: https://aistudio.google.com/apikey, hidden)",
                              cur.get("GEMINI_API_KEY", ""), secret=True, optional=True)
    os.makedirs(HOME, exist_ok=True)
    write_env(env_path, d)
    say("   Saved to ~/.aim/secrets.env")
    return dict(cur, **d)


def install_files():
    step(3, "Installing the computer scripts in ~/.aim")
    os.makedirs(HOME, exist_ok=True)
    for name in sorted(os.listdir(os.path.join(REPO, "pc"))):
        src, dst = os.path.join(REPO, "pc", name), os.path.join(HOME, name)
        if os.path.isfile(src):
            backup(dst)
            shutil.copy2(src, dst)
    say("   %d scripts installed (replaced files are in ~/.aim/backup-%s)" % (len(os.listdir(os.path.join(REPO, "pc"))), STAMP))
    for kind, base in (("claude", CLAUDE), ("codex", CODEX)):
        src_root = os.path.join(REPO, "skills", kind)
        if kind == "codex" and not os.path.isdir(CODEX):
            continue
        for skill in os.listdir(src_root):
            dst = os.path.join(base, "skills", skill)
            backup(dst)
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(os.path.join(src_root, skill), dst)
    say("   /phone, /phone-off and /phone-new installed for Claude Code" + (" and Codex" if os.path.isdir(CODEX) else ""))


def install_hooks():
    step(4, "Adding the AIM hooks to Claude Code (step cards, permissions from the phone)")
    path = os.path.join(CLAUDE, "settings.json")
    os.makedirs(CLAUDE, exist_ok=True)
    s = {}
    if os.path.exists(path):
        try:
            s = json.load(open(path, encoding="utf-8"))
        except ValueError:
            sys.exit("   ~/.claude/settings.json is not valid JSON. Fix it and run the installer again.")
        backup(path)
    cmd = 'python "%s"' % os.path.join(HOME, "aim_tool.py").replace("\\", "/")
    hooks = s.setdefault("hooks", {})
    added = 0
    for ev, matcher in HOOK_EVENTS.items():
        lst = hooks.setdefault(ev, [])
        lst[:] = [h for h in lst if not any("aim_tool.py" in (x.get("command") or "") for x in h.get("hooks", []))]
        entry = {"hooks": [{"type": "command", "command": cmd}]}
        if matcher:
            entry["matcher"] = matcher
        lst.append(entry); added += 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)
    say("   %d hooks set (your other settings are untouched; a backup was made)" % added)


def database(env):
    step(5, "Setting up the database")
    sql = open(os.path.join(REPO, "sql", "setup.sql"), encoding="utf-8").read().replace("__OWNER_EMAIL__", env["AIM_EMAIL"])
    token_path = os.path.join(HOME, "voice.token")
    token = open(token_path).read().strip() if os.path.exists(token_path) else secrets.token_hex(12)
    with open(token_path, "w") as f:
        f.write(token)
    voice = open(os.path.join(REPO, "sql", "voice-template.sql"), encoding="utf-8").read().replace("__VOICE_TOKEN__", token)
    full = sql + "\n\n-- Siri / voice shortcut (optional feature)\n" + voice
    out = os.path.join(HOME, "setup-filled.sql")
    with open(out, "w", encoding="utf-8") as f:
        f.write(full)
    try:
        subprocess.run("clip", input=full.encode("utf-16-le"), check=True, shell=True)
        copied = True
    except Exception:
        copied = False
    ref = env["SUPABASE_URL"].split("//")[1].split(".")[0]
    url = "https://supabase.com/dashboard/project/%s/sql/new" % ref
    say("   The database script is ready" + (" and copied to the clipboard." if copied else ": " + out))
    say("   1) The Supabase SQL Editor opens now: " + url)
    say("   2) Paste (Ctrl+V) and press Run. It is safe to run more than once.")
    webbrowser.open(url)
    while True:
        input("   Press Enter here after it says Success... ")
        try:
            req = urllib.request.Request(env["SUPABASE_URL"] + "/rest/v1/conversations?select=id&limit=1",
                                         headers={"apikey": env["SUPABASE_SERVICE_KEY"], "Authorization": "Bearer " + env["SUPABASE_SERVICE_KEY"]})
            urllib.request.urlopen(req, timeout=15).read()
            say("   Database ready.")
            break
        except Exception as e:
            say("   Not ready yet (%s). Check that the script ran without errors, then press Enter again." % str(e)[:80])
    r = subprocess.run([sys.executable, os.path.join(HOME, "push.py"), "publish-key"], capture_output=True, text=True)
    say("   Push notifications: " + ("key published" if r.returncode == 0 else "failed: " + (r.stderr or r.stdout)[-200:]))


def page_config(env):
    step(6, "Connecting the phone page")
    cfg = os.path.join(REPO, "config.js")
    s = open(cfg, encoding="utf-8").read()
    s = s.replace('supabaseUrl: ""', 'supabaseUrl: "%s"' % env["SUPABASE_URL"]).replace('supabaseKey: ""', 'supabaseKey: "%s"' % env["SUPABASE_ANON_KEY"])
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(s)
    say("   config.js filled in. Commit and push it to your fork if you want the page set up for any phone,")
    say("   or just scan the QR code below on each phone.")
    blob = base64.urlsafe_b64encode(json.dumps({"url": env["SUPABASE_URL"], "key": env["SUPABASE_ANON_KEY"]}).encode()).decode().rstrip("=")
    link = env["AIM_PAGE_URL"] + "?setup=" + blob
    try:
        import qrcode
        qr = qrcode.QRCode(border=2)
        qr.add_data(link)
        qr.make()
        png = os.path.join(HOME, "setup-qr.png")
        qr.make_image().save(png)
        say("\n   Scan this with your phone's camera (also saved as ~/.aim/setup-qr.png):\n")
        qr.print_ascii(invert=True)
        os.startfile(png)
    except Exception:
        pass
    say("\n   Setup link: " + link)
    ref = env["SUPABASE_URL"].split("//")[1].split(".")[0]
    say("\n   In Supabase -> Authentication -> URL Configuration, set Site URL to %s and Save," % env["AIM_PAGE_URL"])
    say("   so the confirmation email opens your page: https://supabase.com/dashboard/project/%s/auth/url-configuration" % ref)
    say("   On the phone: open the link, tap 'First time here', make an account with %s," % env["AIM_EMAIL"])
    say("   confirm the email, sign in, then Add to Home Screen. After that, turn OFF new sign-ups in Supabase:")
    say("   Authentication -> Sign In / Providers -> Allow new users to sign up: off.")


def main():
    say("AIM: AI Manager. Installer\n" + "=" * 30)
    check_tools()
    env = collect()
    install_files()
    install_hooks()
    database(env)
    page_config(env)
    step(7, "Final check")
    subprocess.run([sys.executable, os.path.join(HOME, "doctor.py")])
    say("\nDone. In Claude Code, type /phone to turn the line on.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        say("\nStopped. Nothing is half-installed that a second run won't fix.")
