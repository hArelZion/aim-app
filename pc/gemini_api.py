"""Gemini over the plain REST API (the Gemini CLI no longer serves personal Google accounts).

Needs one line in ~/.aim/secrets.env (never printed, never committed):
    GEMINI_API_KEY=...          # free key from https://aistudio.google.com/apikey
Optional:
    GEMINI_MODEL=gemini-...     # default: the newest "pro" model the key can use

  from gemini_api import ask
  ask(prompt, images=[paths], history=[("user"|"model", text), ...]) -> answer text
"""
import base64
import json
import mimetypes
import os
import re
import urllib.error
import urllib.request

HOME = os.path.join(os.path.expanduser("~"), ".aim")
BASE = "https://generativelanguage.googleapis.com/v1beta"
SYSTEM = (
    "You are Gemini, answering inside AIM, the user's private phone chat. Reply in the language of the user's "
    "message (Hebrew by default), concisely, in light Markdown: **bold**, `code`, lists, headings. No tables. "
    "You have no tools and no network access here; if something needs them, say so."
)


def _env():
    env = {}
    with open(os.path.join(HOME, "secrets.env"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


USAGE = os.path.join(os.path.expanduser("~"), ".aim", "gemini-usage.json")


def _track(path, ok):
    """Count generateContent calls per Pacific day (the free tier's daily quota resets at midnight Pacific) for the
    phone's usage panel; a 429 is remembered as 'limit reached'."""
    if ":generateContent" not in path:
        return
    try:
        from datetime import datetime, timedelta, timezone
        day = (datetime.now(timezone.utc) - timedelta(hours=7)).strftime("%Y-%m-%d")
        try:
            with open(USAGE, encoding="utf-8") as f:
                u = json.load(f)
        except (OSError, ValueError):
            u = {}
        if u.get("day") != day:
            u = {"day": day, "count": 0, "models": {}, "limited": {}}
        model = path.split("/models/")[-1].split(":")[0]
        if ok:
            u["count"] += 1
            u["models"][model] = u["models"].get(model, 0) + 1
        else:
            u["limited"][model] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(USAGE, "w", encoding="utf-8") as f:
            json.dump(u, f)
    except Exception:
        pass


def _call(method, path, key, body=None, timeout=300):
    req = urllib.request.Request(BASE + path, method=method, headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                                 data=json.dumps(body).encode("utf-8") if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())
        _track(path, True)
        return out
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail)["error"]["message"]
        except (ValueError, KeyError, TypeError):
            pass
        if e.code == 429:
            _track(path, False)
        raise RuntimeError("Gemini API %s: %s" % (e.code, detail[:400]))


def candidates(key):
    """Models the key can call, best first: newest pro, then newest flash, then flash-lite."""
    found = {"pro": [], "flash": [], "lite": []}
    for m in _call("GET", "/models?pageSize=200", key).get("models", []):
        name = m["name"].split("/")[-1]
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        mt = re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-(pro|flash|flash-lite)(?:-preview)?(?:-\d+)?", name)
        if mt:
            kind = "lite" if mt.group(2) == "flash-lite" else mt.group(2)
            found[kind].append((float(mt.group(1)), -len(name), name))
    out = []
    for kind in ("flash", "lite", "pro"):
        out += [n for _, _, n in sorted(found[kind], reverse=True)[:2]]
    return out or ["gemini-2.5-flash"]


_LAST = {}


def ask(prompt, images=(), history=(), only=None, system=None, timeout=45):
    env = _env()
    key = env.get("GEMINI_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing from ~/.aim/secrets.env (free key: https://aistudio.google.com/apikey)")
    contents = [{"role": r, "parts": [{"text": t}]} for r, t in history]
    parts = [{"text": prompt}]
    for path in images:
        with open(path, "rb") as f:
            parts.append({"inline_data": {"mime_type": mimetypes.guess_type(path)[0] or "image/jpeg",
                                          "data": base64.b64encode(f.read()).decode()}})
    contents.append({"role": "user", "parts": parts})
    body = {"system_instruction": {"parts": [{"text": system or SYSTEM}]}, "contents": contents}
    models = [only] if only else [env["GEMINI_MODEL"]] if env.get("GEMINI_MODEL") else candidates(key)
    if not only and _LAST.get("model") in models:   # remember what worked; the free tier gives some models no quota at all
        models.remove(_LAST["model"]); models.insert(0, _LAST["model"])
    err = None
    for model in models:
        try:
            out = _call("POST", "/models/%s:generateContent" % model, key,
                        dict(body, generationConfig={"thinkingConfig": {"thinkingLevel": "low"}})  # chat: answer fast
                        if model.startswith("gemini-3") else body, timeout=timeout)
            if not only:
                _LAST["model"] = model
            break
        except (RuntimeError, OSError) as e:   # includes timeouts
            err = RuntimeError(str(e)) if not isinstance(e, RuntimeError) else e
            if not any(c in str(e) for c in (" 429", " 404", " 500", " 503", " 400", "timed out")):   # a slow model: try the next one
                raise
    else:
        raise err
    try:
        text = "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"] if not p.get("thought")).strip()
    except (KeyError, IndexError):
        text = ""
    if not text:
        raise RuntimeError("Gemini returned no text: " + json.dumps(out)[:300])
    return text
