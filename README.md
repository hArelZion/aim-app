# AIM: AI Manager

**Your AI coding agents, in your pocket.** AIM is a private phone app for the AI agents that work on your computer: Claude Code, ChatGPT (Codex) and Gemini. Start a task, leave, and follow it from your phone: see every step live, answer questions, approve permissions, send photos and files, and get a notification when it's done.

[עברית](README.he.md)

## What you get
- **Claude, ChatGPT and Gemini** in one app, plus a **team chat** where Claude leads and hands work to the others.
- **Live steps**, like the official apps: commands, file edits with real diffs, the step running now with a timer.
- **Permissions from the phone:** approve or deny what Claude Code asks, without walking back to the computer.
- **Model, effort and work mode** pickers; ChatGPT's model, reasoning level and permissions too.
- **Push notifications** when a task finishes or needs you, even with the phone locked.
- **Photos and files** both ways, voice input, read-aloud, quick replies, search, light/dark.
- **Siri shortcut** for quick voice questions (optional).
- **37 languages**, chosen automatically from your phone (English by default).

## How it works
```
 phone (your AIM page)  <-->  your Supabase project  <-->  your computer (~/.aim scripts)
                                                             -> Claude Code, Codex, Gemini
```
Everything is yours: your fork of this repo hosts the page on GitHub Pages, your free Supabase project stores the chat, and your computer runs the agents with **your own** Claude / ChatGPT / Gemini accounts. No password or API key ever passes through the page or through anyone else. Every table is locked to your email by row-level security.

## Requirements
- **Windows 10 or 11** (Mac and Linux are planned).
- [Python 3.10+](https://www.python.org/downloads/), [Git for Windows](https://git-scm.com/download/win), [Claude Code](https://claude.com/claude-code).
- Optional: [Codex CLI](https://github.com/openai/codex) (`npm i -g @openai/codex`, then `codex login`) for ChatGPT, and a free [Gemini API key](https://aistudio.google.com/apikey) for Gemini.
- A free [Supabase](https://supabase.com) account and a GitHub account.

## Setup (about 15 minutes)
1. **Fork** this repo, then in your fork: Settings -> Pages -> Deploy from a branch -> `main` / root. Your page will be `https://<you>.github.io/<repo>/`.
2. **Create a Supabase project** (free; the free plan allows 2 active projects per account, so if it asks you to pay, pause an old project or sign up with another email). Keep its Project Settings -> API Keys page open. Then in Authentication -> URL Configuration, set **Site URL** to your page address from step 1 and Save (otherwise the confirmation email links to `localhost`).
3. **Clone your fork** and run the installer:
   ```
   git clone https://github.com/<you>/<repo>.git
   cd <repo>
   python install.py
   ```
   It checks your computer, asks for the Supabase details (for the project URL you can paste the dashboard address from your browser; copy the keys with their copy buttons; the secret key is typed hidden), copies the database script to your clipboard and opens the Supabase SQL editor (paste, Run), installs everything, and shows a **QR code**.
4. **On the phone:** scan the QR code, tap *First time here*, create your account with the same email, confirm it, sign in, and *Add to Home Screen*.
5. **Lock it down:** Supabase -> Authentication -> Sign In / Providers -> turn off *Allow new users to sign up*.
6. In Claude Code, type **`/phone`**. The line is on.

Something not working? Run **`python ~/.aim/aim.py doctor`**. It checks every piece and tells you how to fix what's missing.

## Make it yours
It's your copy: change anything. The page is one file (`index.html`); the computer side is plain Python in `pc/`. To preview the page with sample data and no account: `python preview/preview.py` and open http://localhost:8791. To add a language, copy `lang/de.json`, translate the values, and add the code to `LANGS` in `index.html`.

## Security
- The **secret key** stays in `~/.aim/secrets.env` on your computer. Never commit it, never paste it into a chat.
- While the line is on, messages from your phone are treated like messages typed in Claude Code, so **your Supabase sign-in protects your computer**. Use a strong password and turn off new sign-ups.
- **Screen control** (seeing and using the computer's screen from the phone) works only while the line is on, shows a red banner with a Stop button on the computer, ends after 10 minutes, and can require a PIN: set one with `python ~/.aim/screen.py setpin`.
- Messages are stored in your own Supabase project (encrypted at rest by Supabase, readable only with your account).

## Limits
- Windows only for now. Model / effort / session switching works by pressing buttons in the Claude desktop app, so it is **experimental** and can break when the app updates.
- A free Supabase project pauses after a week without activity; open it in the Supabase dashboard to wake it.
- You are responsible for using your own Claude, ChatGPT and Gemini accounts within their terms of service.

## Uninstall
Delete `~/.aim`, the `phone`, `phone-off`, `phone-new` folders in `~/.claude/skills` (and `~/.codex/skills`), and the four `aim_tool.py` hooks in `~/.claude/settings.json`. Then delete your Supabase project if you like.

## License
[MIT](LICENSE). AIM is an independent project and is **not affiliated with or endorsed by Anthropic, OpenAI or Google**. Claude, ChatGPT and Gemini are trademarks of their owners and are used here only to name the models.
