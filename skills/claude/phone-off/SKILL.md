---
name: phone-off
description: Turn the AIM phone line off — stop the background watcher, mark the line off in AIM, and stop mirroring this session to the phone. The counterpart of `/phone`.
---

# Turn the AIM phone line off

Works in any session, including one that did not start the line.

0. `python ~/.aim/aim_gpt.py off` — stops the ChatGPT and Gemini lines too (their loops and the keep-awake).
1. `python ~/.aim/aim.py mode off` — pauses the line for both models and **returns the computer to its normal sleep behaviour** (stops `awake.py`). If the user asked for the computer to stay awake some other way, honour that instead: run `aim.py mode off` anyway but start `python ~/.aim/awake.py on` again. Any running watcher (in this session or another) sees it within 30 seconds, prints `AIM stop` and exits.
2. If this session started a watcher (`bash ~/.aim/watch.sh` in the background), stop it now with TaskStop on that task instead of waiting.
3. `python ~/.aim/aim.py status state=off activity=-`
4. Post a system line to the phone: `python ~/.aim/aim.py say --kind system <<'EOF'` with `הקו כובה. כדי להפעיל שוב: /phone במחשב.` (English when `aim.py settings` shows `lang` "en": `Line turned off. To turn it back on: /phone on the computer.`).
5. From now on in this session, do not mirror replies to the phone and do not restart the watcher, until the user runs `/phone` again.
6. Confirm in the terminal in one Hebrew line.

When a watcher exits with `AIM stop` because of this, do nothing more (the steps above already ran).
To turn the line back on: `/phone` (it sets `mode` back to "on" with `aim.py mode on`).
