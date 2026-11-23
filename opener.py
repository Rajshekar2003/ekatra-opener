#!/usr/bin/env python3
"""
opener.py - give it a company website, get a 3-line cold-email opener for the founder.

Code does: URL safety, fetching, text cleanup, caching, retries, and checking the output.
Model does: only one job - pick one real detail from the page and write 3 short lines.

Usage:
  export GEMINI_API_KEY=your_free_key        # https://aistudio.google.com/apikey
  python opener.py https://example.com
  python opener.py --file urls.txt --workers 4 --out results.json
"""
import argparse, hashlib, ipaddress, json, os, re, socket, sys, time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

MODEL = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")   # change via env if the name changes
CACHE_FILE = os.getenv("CACHE_FILE", ".opener_cache.json")
CACHE_TTL = 7 * 24 * 3600
MAX_PAGE_CHARS = 6000          # about 1.5k tokens sent to the model
MAX_BYTES = 1_500_000
UA = "Mozilla/5.0 (compatible; OpenerBot/1.0)"
BANNED = ["i came across", "i hope this finds", "i noticed that you", "impressive", "game-changer",
          "revolutioniz", "cutting-edge", "synergy", "\u2014", "\u2013"]

SYSTEM = """You write the first 3 lines of a cold email to a startup founder.
You are given text scraped from the company's website. Rules:
1. Use ONLY facts present in the text. Never invent customers, numbers, funding or news.
2. Pick ONE specific detail (a product, a claim, a customer type, a recent change).
   Copy a short exact phrase of it (max 12 words) into "hook_quote". It must appear word for word in the text.
3. Write exactly 3 lines, each under 25 words:
   Line 1: mention that specific detail, plainly, no flattery.
   Line 2: one honest guess at a problem that detail creates, worded as a guess ("I'd guess...").
   Line 3: one easy, low-pressure question.
4. Plain words. No hype, no em dashes, no "I came across", no "I hope this finds you well".
5. If the text is too thin or generic to find a real detail, set "insufficient": true and leave lines empty.
Return JSON only: {"hook_quote": str, "lines": [str,str,str], "insufficient": bool}"""

# ---------------------------------------------------------------- safety + fetching
def normalize_url(u: str) -> str:
    u = u.strip()
    if not re.match(r"^https?://", u, re.I):
        u = "https://" + u
    return u

def is_public_host(host: str) -> bool:
    if os.getenv("ALLOW_PRIVATE") == "1":      # only for local tests
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True

def fetch(url: str, hops: int = 3) -> str:
    """Fetch HTML safely: public hosts only, re-checked on every redirect, size and time capped."""
    for _ in range(hops + 1):
        p = urlparse(url)
        if p.scheme not in ("http", "https") or not p.hostname or not is_public_host(p.hostname):
            raise ValueError("blocked or invalid URL")
        r = requests.get(url, headers={"User-Agent": UA}, timeout=8, stream=True, allow_redirects=False)
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
            url = urljoin(url, r.headers["Location"]); continue
        if r.status_code >= 400:
            raise ValueError(f"site returned HTTP {r.status_code}")
        if "html" not in r.headers.get("Content-Type", "").lower():
            raise ValueError("not an HTML page")
        body = b""
        for chunk in r.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES: break
        return body.decode(r.encoding or "utf-8", errors="ignore")
    raise ValueError("too many redirects")

def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    parts = []
    if soup.title and soup.title.string: parts.append("TITLE: " + soup.title.string.strip())
    for m in soup.find_all("meta"):
        if m.get("name") in ("description",) or m.get("property") in ("og:description", "og:title"):
            if m.get("content"): parts.append("META: " + m["content"].strip())
    for t in soup(["script", "style", "nav", "footer", "form", "noscript", "svg", "iframe"]):
        t.decompose()
    for h in soup.find_all(["h1", "h2", "h3"]):
        s = h.get_text(" ", strip=True)
        if 3 < len(s) < 160: parts.append("HEADING: " + s)
    for el in soup.find_all(["p", "li"]):
        s = el.get_text(" ", strip=True)
        if len(s) > 40: parts.append(s)
    seen, out = set(), []
    for s in parts:
        if s not in seen: seen.add(s); out.append(s)
    return "\n".join(out)[:MAX_PAGE_CHARS]

def get_site_text(url: str) -> str:
    text = extract_text(fetch(url))
    if len(text) < 500:                          # thin homepage (often JS sites): try /about once
        try: text += "\n" + extract_text(fetch(urljoin(url, "/about")))
        except Exception: pass
    return text[:MAX_PAGE_CHARS]

# ---------------------------------------------------------------- model call
def call_llm(page_text: str, feedback: str = "") -> dict:
    key = os.getenv("GEMINI_API_KEY")
    if not key: raise RuntimeError("Set GEMINI_API_KEY")
    api = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    user = f"WEBSITE TEXT:\n{page_text}" + (f"\n\nYour last answer was rejected: {feedback}. Fix it." if feedback else "")
    body = {"systemInstruction": {"parts": [{"text": SYSTEM}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.4, "maxOutputTokens": 400,
                                 "responseMimeType": "application/json"}}
    for attempt in range(4):                     # backoff on rate limit / server errors
        r = requests.post(api, headers={"x-goog-api-key": key}, json=body, timeout=30)
        if r.status_code in (429, 500, 503):
            time.sleep(2 ** attempt); continue
        r.raise_for_status()
        return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    raise RuntimeError("model busy, try later")

# ---------------------------------------------------------------- checking the model's work
def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", s.lower())).strip()

def validate(out: dict, page_text: str):
    """Return an error string, or None if the output is acceptable."""
    if out.get("insufficient"): return None
    lines = out.get("lines")
    if not isinstance(lines, list) or len(lines) != 3 or not all(isinstance(x, str) and x.strip() for x in lines):
        return "need exactly 3 non-empty lines"
    if any(len(x.split()) > 30 for x in lines): return "a line is longer than 30 words"
    joined = " ".join(lines).lower()
    for b in BANNED:
        if b in joined: return f"contains banned phrase '{b}'"
    q = norm(out.get("hook_quote", ""))
    if len(q.split()) < 3 or q not in norm(page_text): return "hook_quote is not word for word on the page"
    return None

# ---------------------------------------------------------------- cache
_cache_lock = __import__("threading").Lock()
def cache_get(k):
    try:
        with open(CACHE_FILE) as f: d = json.load(f).get(k)
        if d and time.time() - d["t"] < CACHE_TTL: return d["v"]
    except Exception: pass
def cache_put(k, v):
    with _cache_lock:
        try:
            with open(CACHE_FILE) as f: d = json.load(f)
        except Exception: d = {}
        d[k] = {"t": time.time(), "v": v}
        with open(CACHE_FILE, "w") as f: json.dump(d, f)

# ---------------------------------------------------------------- main flow
def make_opener(url: str, llm=call_llm) -> dict:
    url = normalize_url(url)
    key = hashlib.sha1(urlparse(url).netloc.lower().encode()).hexdigest()
    if (hit := cache_get(key)): return {**hit, "cached": True}
    try:
        text = get_site_text(url)
    except Exception as e:
        return {"url": url, "status": "fetch_failed", "reason": str(e)}
    if len(text) < 200:
        return {"url": url, "status": "needs_human", "reason": "page has too little text (maybe JS-only or blocked)"}
    feedback, out = "", {}
    for _ in range(2):                           # one retry, with the exact reason for rejection
        try: out = llm(text, feedback)
        except Exception as e: return {"url": url, "status": "model_failed", "reason": str(e)}
        feedback = validate(out, text) or ""
        if not feedback: break
    if feedback or out.get("insufficient"):
        return {"url": url, "status": "needs_human", "reason": feedback or "no real detail found on the site"}
    res = {"url": url, "status": "ok", "hook_quote": out["hook_quote"], "opener": "\n".join(out["lines"])}
    cache_put(key, res)
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?"); ap.add_argument("--file"); ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out")
    a = ap.parse_args()
    urls = [a.url] if a.url else [l.strip() for l in open(a.file) if l.strip()] if a.file else []
    if not urls: ap.error("give a URL or --file")
    with ThreadPoolExecutor(a.workers) as ex: results = list(ex.map(make_opener, urls))
    for r in results:
        print(f"\n{r['url']}  [{r['status']}]")
        print(r.get("opener") or r.get("reason"))
    if a.out: json.dump(results, open(a.out, "w"), indent=2)

if __name__ == "__main__":
    main()
