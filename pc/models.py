"""AIM model registry: every extra model that can join the team chat.

  python models.py sync [--check]   rebuild ~/.aim/models.json and publish it to the phone (control row "models");
                                    --check also sends each model a tiny request and drops the ones that do not answer
  python models.py list     print the registry

Providers: "gemini" (Gemini API, free-tier models only), "codex" (ChatGPT models through the Codex CLI, included
in the ChatGPT plan), PROVIDERS (OpenRouter free models, Groq, Cerebras, NVIDIA, Mistral, local Ollama; each appears when its key is in secrets.env).
Each entry: key (a-z0-9 only, used in message ids "-x<key>" and in "@key"), name, provider, model, color.
"""
import json
import os
import re
import sys
import aim

HOME = aim.HOME
FILE = os.path.join(HOME, "models.json")

# Tested working on 2026-10-05 (free quota / plan access).
GEMINI = [
    ("gem38f", "Gemini 3.8 Flash", "gemini-3.8-flash"), ("gem37f", "Gemini 3.7 Flash", "gemini-3.7-flash"),
    ("gem36f", "Gemini 3.6 Flash", "gemini-3.6-flash"), ("gem35f", "Gemini 3.5 Flash", "gemini-3.5-flash"),
    ("gem35l", "Gemini 3.5 Flash-Lite", "gemini-3.5-flash-lite"), ("gem31l", "Gemini 3.1 Flash-Lite", "gemini-3.1-flash-lite"),
    ("gemma26", "Gemma 4 26B", "gemma-4-26b-a4b-it"), ("gemma31", "Gemma 4 31B", "gemma-4-31b-it"),
]
CODEX = [
    ("gpt61sol", "GPT-6.1 Sol", "gpt-6.1-sol"), ("gpt6astra", "GPT-6 Astra", "gpt-6-astra"), ("gpt6sol", "GPT-6 Sol", "gpt-6-sol"),
    ("gpt6luna", "GPT-6 Luna", "gpt-6-luna"), ("gpt56sol", "GPT-5.6 Sol", "gpt-5.6-sol"), ("gpt56terra", "GPT-5.6 Terra", "gpt-5.6-terra"),
    ("gpt56luna", "GPT-5.6 Luna", "gpt-5.6-luna"), ("gpt55", "GPT-5.5", "gpt-5.5"),
]
COLORS = {"gemini": "#9aa8f8", "codex": "#5b9bf5"}
PALETTE = ["#e5707e", "#e8a24a", "#7bc47f", "#4db6ac", "#7aa2f7", "#b18cf0", "#e58bc2", "#c0a16b"]


# OpenAI-compatible providers. A provider is used when its key is in secrets.env (Ollama: when it is running).
PROVIDERS = {
    "openrouter": {"base": "https://openrouter.ai/api/v1", "env": "OPENROUTER_API_KEY", "label": "OpenRouter", "free_only": True},
    "groq": {"base": "https://api.groq.com/openai/v1", "env": "GROQ_API_KEY", "label": "Groq"},
    "cerebras": {"base": "https://api.cerebras.ai/v1", "env": "CEREBRAS_API_KEY", "label": "Cerebras"},
    "nvidia": {"base": "https://integrate.api.nvidia.com/v1", "env": "NVIDIA_API_KEY", "label": "NVIDIA"},
    "mistral": {"base": "https://api.mistral.ai/v1", "env": "MISTRAL_API_KEY", "label": "Mistral"},
    "ollama": {"base": "http://localhost:11434/v1", "env": "", "label": "Local"},
}
SKIP = re.compile(r"embed|whisper|tts|guard|moderation|safety|rerank|image|vision-only|transcribe|audio|speech|"
                  r"diffusion|flux|clip|parse|ocr|retriev|reward|classif|lyria|orpheus|playai", re.I)
CAP = 60   # per provider


def provider_models(name):
    import compat_api
    p = PROVIDERS[name]
    key = compat_api.env_value(p["env"]) if p["env"] else ""
    if p["env"] and len(key) < 8:
        return []
    try:
        data = compat_api.get(p["base"], key, "/models", timeout=8)["data"]
    except Exception:
        return []
    out = []
    for m in data:
        mid = m.get("id") or ""
        if not mid or SKIP.search(mid):
            continue
        if p.get("free_only"):
            pr = m.get("pricing", {})
            outs = (m.get("architecture") or {}).get("output_modalities") or ["text"]
            if str(pr.get("prompt")) != "0" or str(pr.get("completion")) != "0" or outs != ["text"]:
                continue
        out.append((mid, m.get("name") or mid))
    return out[:CAP]


def pretty(mid):
    tail = mid.split("/")[-1].split(":")[0]
    return re.sub(r"[-_]+", " ", tail).strip().title()[:28]


def build():
    reg = []
    for key, name, model in GEMINI:
        reg.append({"key": key, "name": name, "provider": "gemini", "model": model, "color": COLORS["gemini"]})
    for key, name, model in CODEX:
        reg.append({"key": key, "name": name, "provider": "codex", "model": model, "color": COLORS["codex"]})
    reg.append({"key": "imgflux", "name": "Flux (תמונות)", "provider": "image", "model": "flux", "color": "#e58bc2"})
    seen = {e["key"] for e in reg}
    for pi, pname in enumerate(PROVIDERS):
        for i, (mid, nm) in enumerate(provider_models(pname)):
            key = (pname[:2] + re.sub(r"[^a-z0-9]", "", mid.lower().split(":")[0]))[:20]
            n = 2
            while key in seen:
                key = key[:18] + str(n); n += 1
            seen.add(key)
            reg.append({"key": key, "name": (PROVIDERS[pname]["label"] + " " + pretty(mid))[:34], "provider": pname,
                        "model": mid, "color": PALETTE[(pi + i) % len(PALETTE)]})
    return reg


STRONG = re.compile(r"ultra|super|large|opus|kimi|pro|sol|astra|max|magistral|medium|deepseek-v|r1|405b|253b|550b|120b|gpt-oss-120|devstral", re.I)
SMALL = re.compile(r"mini|nano|tiny|small|lite|lightning|instant|ministral|ling|apodex", re.I)


def tier(e):
    """My rough estimate of strength: strong / medium / small (by provider, parameter count and name)."""
    n = (e["name"] + " " + e["model"]).lower()
    if e["provider"] == "codex":
        return "medium" if re.search(r"luna|terra", n) else "strong"
    if e["provider"] == "gemini":
        if "gemma" in n or "lite" in n:
            return "medium"
        return "strong" if re.search(r"3\.(7|8)", n) else "medium"
    sizes = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)b(?![a-z])", n)]
    if STRONG.search(n) and "small" not in n:
        return "strong"
    if sizes:
        big = max(sizes)
        return "strong" if big >= 70 else "medium" if big >= 20 else "small"
    if SMALL.search(n) or "small" in n:
        return "small"
    return "medium"


def check(reg, workers=10):
    """Keep only OpenAI-compatible models that really answer a tiny request (a rate limit counts as alive)."""
    import compat_api
    from concurrent.futures import ThreadPoolExecutor

    def ok(e):
        if e["provider"] not in PROVIDERS:
            return True
        try:
            compat_api.ask(e["provider"], e["model"], "Reply with: OK", timeout=100)
            return True
        except RuntimeError as ex:
            return " 429" in str(ex) or " 503" in str(ex)   # alive, just busy
        except Exception:
            return False

    with ThreadPoolExecutor(workers) as ex:
        keep = list(ex.map(ok, reg))
    return [e for e, k in zip(reg, keep) if k]


def load():
    try:
        with open(FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def sync(verify=False):
    reg = build()
    if verify:
        n = len(reg)
        reg = check(reg)
        print("checked: %d of %d answered" % (len(reg), n))
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    aim.put_row("models", {"list": [dict({k: e[k] for k in ("key", "name", "color")}, tier=tier(e)) for e in reg]})
    print("%d models published (%s)" % (len(reg), ", ".join(sorted({e["provider"] for e in reg}))))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "sync":
        sync(verify="--check" in sys.argv)
    elif cmd == "list":
        for e in load():
            print("%-12s %-26s %-10s %s" % (e["key"], e["name"], e["provider"], e["model"]))
    else:
        sys.exit(__doc__)
