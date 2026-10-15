---
name: phone
description: Connect ChatGPT/Codex to the user's private AIM phone chat so they can talk to it from their phone. Use when the user types /phone or $phone, or asks to turn the AIM phone line on.
---

# AIM — ChatGPT phone line (on)

AIM is the user's private chat app on their phone (your own copy of the page: `AIM_PAGE_URL` in `~/.aim/secrets.env`). The ChatGPT side has its own conversations, status and pause switch. A background loop on this computer answers phone messages with Codex; this session does not need to stay open.

Steps:
1. Run `python "$HOME/.aim/aim_gpt.py" on <current folder name>` (PowerShell: `python "$env:USERPROFILE\.aim\aim_gpt.py" on <current folder name>`). It needs network access and starts a background process, so run it outside the sandbox (request escalated permissions) and tell the user an approval prompt may appear.
2. Tell the user in Hebrew, briefly, that the ChatGPT line is on. Do nothing else: replies to the phone come from the background loop, not from this session.

Never print or read `~/.aim/secrets.env`.
