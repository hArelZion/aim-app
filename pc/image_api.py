"""Free image generation for the team chat: Pollinations (no key). The picture is stored in AIM's photo bucket and
returned as "IMG::<storage path>", which team.post turns into an image message.

  from image_api import generate; generate(prompt) -> "IMG::claude/..."
"""
import os
import re
import time
import urllib.parse
import urllib.request

import aim

GEN = os.path.join(aim.HOME, "gen")


def generate(prompt, model="flux", size=1024):
    prompt = re.sub(r"\s+", " ", prompt).strip()[:600]
    url = "https://image.pollinations.ai/prompt/%s?model=%s&width=%d&height=%d&nologo=true&seed=%d" % (
        urllib.parse.quote(prompt), model, size, size, int(time.time()) % 100000)
    req = urllib.request.Request(url, headers={"User-Agent": "AIM-team/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
        if not (r.headers.get("Content-Type") or "").startswith("image"):
            raise RuntimeError("image service returned no image")
    os.makedirs(GEN, exist_ok=True)
    path = os.path.join(GEN, "img-%d.jpg" % int(time.time() * 1000))
    with open(path, "wb") as f:
        f.write(data)
    stored = "claude/%d-%s" % (int(time.time() * 1000), os.path.basename(path))
    aim.call("POST", "/storage/v1/object/%s/%s" % (aim.BUCKET, urllib.parse.quote(stored)), data,
             {"Content-Type": "image/jpeg", "x-upsert": "true"})
    return "IMG::" + stored
