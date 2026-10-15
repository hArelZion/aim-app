"""OpenAI-compatible chat providers: one small client for OpenRouter, Groq, Cerebras, NVIDIA NIM, Mistral and a local
Ollama. Keys live in ~/.aim/secrets.env (never printed); see PROVIDERS in models.py.

  from compat_api import ask; ask(provider, model, prompt) -> text
"""
import json
import os
import urllib.error
import urllib.request

HOME = os.path.join(os.path.expanduser("~"), ".aim")
SYSTEM = ("You are a model taking part in AIM, a team chat where Claude leads. Answer the request directly and "
          "concisely; reply in the language the request asks for. You have no tools or network access.")


def env_value(name):
    try:
        with open(os.path.join(HOME, "secrets.env"), encoding="utf-8") as f:
            for line in f:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return os.environ.get(name) or ""


def get(base, key, path, timeout=30):
    req = urllib.request.Request(base + path, headers=dict({"User-Agent": "AIM-team/1.0"}, **({"Authorization": "Bearer " + key} if key else {})))
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ask(provider, model, prompt, timeout=180):
    import models
    p = models.PROVIDERS[provider]
    key = env_value(p["env"]) if p["env"] else ""
    if p["env"] and not key:
        raise RuntimeError("%s is missing from ~/.aim/secrets.env" % p["env"])
    body = {"model": model, "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    headers = {"Content-Type": "application/json", "User-Agent": "AIM-team/1.0"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(p["base"] + "/chat/completions", data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError("%s %s: %s" % (provider, e.code, e.read().decode("utf-8", "replace")[:300]))
    try:
        text = (out["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        text = ""
    if "</think>" in text:   # reasoning models that inline their thinking
        text = text.split("</think>")[-1].strip()
    if not text:
        raise RuntimeError("%s returned no text: %s" % (provider, json.dumps(out)[:300]))
    return text
