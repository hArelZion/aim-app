---
name: phone-new
description: Move the AIM phone line to a fresh Claude Code session on this computer — open a new session, start /phone there, and disconnect this one from the line. Use when the user says /phone-new (often from the phone) or asks for a new session for the phone line.
---

# Move the phone line to a new session

A long session costs more per message (every turn re-reads it). This opens a clean session and hands the line over.

1. Tell the phone what is about to happen: `python ~/.aim/aim.py say` with
   `פותח שיחה חדשה במחשב ומעביר אליה את הקו. התשובה הבאה תגיע מהשיחה החדשה.`
   (English when `aim.py settings` shows `lang` "en").
2. Run `python ~/.aim/aim_handoff.py [folder]` (default folder `.aim`, the sidebar's name for the current folder). It presses the Claude app's "New session in <folder>", types `/phone` there and sends it. It prints `ok <title>` or `error <why>`.
3. On `ok`: stop this session's watcher with TaskStop and **do not restart it**. Do not post anything more to the phone from this session: the new session's `/phone` takes over (its `aim.py mode on` makes the step-card hooks follow it, and `newconv` opens a new chat on the phone). Tell the user in the terminal, in one Hebrew line, that the line moved.
4. On `error`: post the reason to the phone (`--kind question`), keep the line here, restart the watcher.

The line is not switched off at any point (no `aim.py mode off`), so the phone stays connected.
