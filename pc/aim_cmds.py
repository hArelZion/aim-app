"""AIM slash commands: publish the skills Claude can run to control row "commands" ({list: [{name, desc}]}), so
typing "/" in the phone's composer offers them. A phone message "/name args" is run like typing it here
(see the phone skill). python aim_cmds.py [--print]"""
import json
import os
import re
import sys

HOME = os.path.join(os.path.expanduser("~"), ".aim")
SKILLS = os.path.join(os.path.expanduser("~"), ".claude", "skills")
SKIP = {"phone"}   # already on when the phone can send anything
BUILTIN = [
    ("code-review", "Review the current changes for bugs"),
    ("simplify", "Clean up the changed code"),
    ("security-review", "Security review of the pending changes"),
    ("init", "Write a CLAUDE.md for this project"),
    ("loop", "Run a prompt again and again on an interval"),
    ("schedule", "Schedule a task to run later or on a timer"),
]


def front(path):
    try:
        with open(path, encoding="utf-8") as f:
            s = f.read(4000)
    except OSError:
        return {}
    m = re.match(r"---\s*\n(.*?)\n---", s, re.S)
    out = {}
    for line in (m.group(1) if m else "").split("\n"):
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def collect():
    out = []
    if os.path.isdir(SKILLS):
        for d in sorted(os.listdir(SKILLS)):
            fm = front(os.path.join(SKILLS, d, "SKILL.md"))
            name = fm.get("name") or d
            if name in SKIP or not fm:
                continue
            desc = re.split(r"(?<=[.!?])\s", fm.get("description", ""), maxsplit=1)[0].split(" — ")[0]
            out.append({"name": name, "desc": desc[:110]})
    have = {c["name"] for c in out}
    out += [{"name": n, "desc": d} for n, d in BUILTIN if n not in have]
    return out


if __name__ == "__main__":
    lst = collect()
    if "--print" in sys.argv:
        print(json.dumps(lst, ensure_ascii=False, indent=1))
    else:
        sys.path.insert(0, HOME)
        import aim
        aim.put_row("commands", {"list": lst})
        print("commands: %d" % len(lst))
