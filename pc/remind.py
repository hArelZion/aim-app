"""Send a reminder to the phone (chat message + push with vibration). Run by Windows Task Scheduler at the chosen time,
so it works even when the AIM line is off and without a Claude session.

  python remind.py "text" [--title "⏰ תזכורת"]
"""
import os
import subprocess
import sys

HOME = os.path.join(os.path.expanduser("~"), ".aim")


def main():
    args = sys.argv[1:]
    title = "⏰ תזכורת"
    if "--title" in args:
        i = args.index("--title"); title = args[i + 1]; del args[i:i + 2]
    text = " ".join(args).strip() or "תזכורת"
    subprocess.run([sys.executable, os.path.join(HOME, "aim.py"), "say", "--style", "general", "--title", title],
                   input=("**" + title + "**\n\n" + text).encode("utf-8"), cwd=HOME, creationflags=0x08000000)


if __name__ == "__main__":
    main()
