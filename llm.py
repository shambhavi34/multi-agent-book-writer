"""Provider layer. Set LLM_PROVIDER=openai (default) or anthropic. Agents never import an SDK directly."""
import os, re, json
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

PROVIDER = os.getenv("LLM_PROVIDER", "openai").lower()
MODEL = os.getenv("MODEL") or ("gpt-4.1" if PROVIDER == "openai" else "claude-sonnet-5-5")

if PROVIDER == "openai":
    from openai import OpenAI
    client = OpenAI()
else:
    from anthropic import Anthropic
    client = Anthropic()


def clean_url(url):
    """OpenAI appends tracking params like ?utm_source=openai; strip them."""
    p = urlparse(url)
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_")]
    return urlunparse(p._replace(query=urlencode(q)))


def ask(system, user, max_tokens=4000):
    if PROVIDER == "openai":
        r = client.chat.completions.create(model=MODEL, messages=[
            {"role": "system", "content": system}, {"role": "user", "content": user}])
        return (r.choices[0].message.content or "").strip()
    r = client.messages.create(model=MODEL, max_tokens=max_tokens, system=system,
                               messages=[{"role": "user", "content": user}])
    return "".join(b.text for b in r.content if b.type == "text").strip()


def ask_json(system, user, max_tokens=4000):
    system += "\nReply with valid JSON only. No markdown fences, no commentary."
    for _ in range(2):
        text = re.sub(r"^```(?:json)?|```$", "", ask(system, user, max_tokens), flags=re.M).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            user += "\n\nYour last reply was not valid JSON. Return only the JSON."
    raise ValueError("Model did not return valid JSON")


def web_search(prompt):
    """Returns (notes_text, {url: {url, title, snippets}}).
    Sources come ONLY from the provider's structured search citations, never from model-typed URLs."""
    sources = {}

    def add(url, title, snippet=""):
        url = clean_url(url)
        s = sources.setdefault(url, {"url": url, "title": title or url, "snippets": []})
        snippet = (snippet or "").strip()
        if snippet and snippet not in s["snippets"]:
            s["snippets"].append(snippet)

    if PROVIDER == "openai":
        r = client.responses.create(model=MODEL, tools=[{"type": "web_search"}], input=prompt)
        for item in r.output:
            if item.type != "message":
                continue
            for c in item.content:
                text = getattr(c, "text", "") or ""
                for a in getattr(c, "annotations", None) or []:
                    if a.type == "url_citation":
                        add(a.url, a.title, text[a.start_index:a.end_index])
        return r.output_text, sources

    r = client.messages.create(
        model=MODEL, max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
        messages=[{"role": "user", "content": prompt}])
    notes = []
    for b in r.content:
        if b.type == "text":
            notes.append(b.text)
            for c in getattr(b, "citations", None) or []:
                if getattr(c, "type", "") == "web_search_result_location":
                    add(c.url, c.title, c.cited_text)
    return "\n".join(notes), sources
