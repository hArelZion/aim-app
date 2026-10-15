---
name: phone-off
description: Disconnect ChatGPT/Codex from the user's AIM phone chat. Use when the user types /phone-off or $phone-off, or asks to turn the AIM phone line off.
---

# AIM — ChatGPT phone line (off)

Run `python "$HOME/.aim/aim_gpt.py" off` (PowerShell: `python "$env:USERPROFILE\.aim\aim_gpt.py" off`). It needs network access and stops a background process, so run it outside the sandbox (request escalated permissions). Then tell the user in Hebrew, briefly, that the ChatGPT line is off.
