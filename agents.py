"""The agents. Each is a plain function: structured input -> structured output. Nothing is topic-specific."""
import re, datetime
import requests
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from llm import ask, ask_json, web_search
from brief import Brief

CITE = re.compile(r"\[(\d+)\]")
PUBLISHERS = {"npci.org.in": "NPCI", "rbi.org.in": "Reserve Bank of India",
              "pib.gov.in": "Press Information Bureau", "reuters.com": "Reuters",
              "livemint.com": "Mint", "economictimes.indiatimes.com": "The Economic Times",
              "thehindu.com": "The Hindu", "indianexpress.com": "The Indian Express",
              "business-standard.com": "Business Standard", "worldbank.org": "World Bank",
              "who.int": "World Health Organization", "bbc.com": "BBC", "nytimes.com": "The New York Times"}
OFFICIAL = ("gov", "gov.in", "nic.in", "gov.uk", "edu", "ac.in", "ac.uk", "europa.eu", "who.int",
            "worldbank.org", "imf.org", "un.org", "oecd.org", "rbi.org.in", "npci.org.in")


def host(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def publisher(url):
    h = host(url)
    for d, name in PUBLISHERS.items():
        if h == d or h.endswith("." + d):
            return name
    return h


def is_official(url):
    h = host(url)
    return any(h == d or h.endswith("." + d) for d in OFFICIAL)


def sentences(text):
    return [s.strip() for p in text.split("\n") for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()]


def split_takeaway(draft):
    lines = draft.strip().split("\n")
    return ("\n".join(l for l in lines if not l.startswith("Takeaway:")).strip(),
            [l for l in lines if l.startswith("Takeaway:")])


def outline_text(outline):
    return "\n".join(f"Chapter {c['number']}: {c['title']}: {c['goal']}" for c in outline["chapters"])


def voice(b):
    return (f"You are writing a book for: {b.audience}. Tone: {b.tone}. Use plain English and explain any "
            "technical term the first time it appears. Write flowing paragraphs only: no bullets, no lists, "
            "no sub-headings. Keep one consistent voice throughout the whole book.")


# ------------------------------------------------------ Brief parser
def parse_brief(raw):
    """Turn any free-text brief (a full paragraph or just a topic) into a structured Brief."""
    d = ask_json(
        "Extract a book brief from the user's text. If a field is missing, use the default shown. "
        "If no title is given, write a good one.",
        f"TEXT:\n{raw}\n\nReturn JSON: "
        '{"title":"","audience":"general readers","tone":"friendly, clear and encouraging",'
        '"chapters":3,"min_words":600,"max_words":900,"notes":"any extra instructions, '
        'regional focus or source preferences, else empty"}')
    return Brief(title=d.get("title") or raw[:80], audience=d.get("audience") or "general readers",
                 tone=d.get("tone") or "friendly, clear and encouraging",
                 chapters=d.get("chapters") or 3, min_words=d.get("min_words") or 600,
                 max_words=d.get("max_words") or 900, notes=d.get("notes") or "").clamp()


# ---------------------------------------------------------------- Planner
def planner(b):
    n = b.chapters
    return ask_json(
        f"You are a book planner. Plan the COMPLETE {n}-chapter book as one arc for the audience: a logical "
        "progression (foundations -> core ideas -> practical application, adapted to the topic). Chapters must "
        "not overlap. Every key point must be something a public source could back up with facts.",
        f"BRIEF:\n{b.text()}\n\nReturn JSON: "
        '{"chapters":[{"number":1,"title":"","goal":"","key_points":[""],"research_questions":[""]}]} '
        f"with exactly {n} chapters, 4-6 key points and 4-6 research questions each.")


# ------------------------------------------------------------- Researcher
def researcher(chapter, b):
    qs = "\n".join(f"- {q}" for q in chapter["research_questions"])
    notes, found = web_search(
        f"Research for chapter '{chapter['title']}' of a book titled '{b.title}' for {b.audience}. "
        f"Today is {datetime.date.today():%B %Y}, so prefer the latest figures and state the date or period "
        f"each figure refers to. Extra instructions: {b.notes or 'none'}.\n"
        f"Answer these questions with short factual notes, citing sources:\n{qs}\n"
        "Prefer official or primary sources (government, regulators, international bodies, universities, "
        "company filings) and reputable news outlets. No blogs, forums or marketing pages.")
    srcs = []
    for i, s in enumerate(found.values(), 1):
        page = fetch(s["url"])  # check the link works right now
        srcs.append({"id": i, "url": s["url"], "title": s["title"], "publisher": publisher(s["url"]),
                     "official": is_official(s["url"]), "snippets": s["snippets"][:4],
                     "status": page["status"], "dead": page["status"] == "dead"})
    return {"notes": notes, "sources": srcs}


# --------------------------------------------------------------- Writer
def writer(b, outline, chapter, pack, anchor, earlier, previous, feedback):
    live = [s for s in pack["sources"] if not s["dead"]]
    src_txt = "\n\n".join(
        f"[{s['id']}] {s['publisher']}: {s['title']}\n" + "\n".join(f'  - "{x[:400]}"' for x in s["snippets"])
        for s in live)
    total = len(outline["chapters"])
    prompt = f"""You are writing chapter {chapter['number']} of a {total}-chapter book titled "{b.title}".
Extra instructions from the brief: {b.notes or 'none'}
THE WHOLE BOOK:
{outline_text(outline)}

ALREADY COVERED IN EARLIER CHAPTERS (build on it; do not repeat it):
{earlier or '(nothing yet: this is the opening chapter)'}

NOW WRITE chapter {chapter['number']}: "{chapter['title']}"
Goal: {chapter['goal']}
Cover: {'; '.join(chapter['key_points'])}
Stay inside this chapter's scope; other chapters cover their own topics. Open and close so the chapter
flows naturally within the book.

RULES
- Aim for about {(b.min_words + b.max_words) // 2} words of prose; never go above {b.max_words} or below {b.min_words}
  (the Takeaway line does not count). When fixing problems, keep the length inside this range.
- Every fact, figure and date carries a numbered citation like [2], using ONLY the source numbers
  below, and only for claims those sources support. Never invent a number; leave out unsupported facts.
- No heading, no reference list. End with exactly one line starting "Takeaway:". The Takeaway is a
  plain lesson with no figures or dates.

SOURCES
{src_txt}

RESEARCH NOTES (context only; cite via the numbers above)
{pack['notes'][:3000]}
"""
    if anchor:
        prompt += f"\nVOICE ANCHOR: match the voice of this opening from chapter 1:\n{anchor}\n"
    if previous and feedback:
        prompt += (f"\nYOUR PREVIOUS DRAFT:\n{previous}\n\nFIX THESE PROBLEMS (keep everything else):\n"
                   + "\n".join(f"- {f}" for f in feedback))
    return ask(voice(b), prompt, max_tokens=3000)


def summarise(chapter_no, title, body):
    return f"Chapter {chapter_no} ({title}): " + ask(
        "Summarise in 2-3 plain sentences the topics and key facts this chapter covered.", body, 300)


# ----------------------------------------------------------------- Editor
def editor(draft, b):
    body, take = split_takeaway(draft)
    issues = []
    words = len(body.split())
    if not b.min_words <= words <= b.max_words:
        if words > b.max_words:
            issues.append(f"Too long: {words} words. Cut at least {words - b.max_words + 50} words "
                          f"(limit {b.max_words}) by removing the least important detail.")
        else:
            issues.append(f"Too short: {words} words. Add about {b.min_words - words + 50} words (minimum {b.min_words}).")
    if re.search(r"^\s*([-*\u2022]|\d+[.)])\s", draft, flags=re.M):
        issues.append("Remove bullet points or numbered lists; use flowing prose.")
    if len(take) != 1 or not draft.strip().split("\n")[-1].startswith("Takeaway:"):
        issues.append("End with exactly one line starting 'Takeaway:' as the last line.")
    elif re.search(r"\d", take[0]):
        issues.append("The Takeaway must not contain figures or dates; make it a plain lesson.")
    verdict = ask_json(
        f"You are a strict but kind copy editor for a book aimed at: {b.audience}. Required tone: {b.tone}. "
        "Check grammar, spelling, punctuation, tone, jargon (every technical term explained on first use) "
        "and readability. Do NOT touch facts or [n] citations. "
        "Only list problems that MUST be fixed (errors, not style preferences), at most 5, most important first, "
        "each as a concrete instruction. If the chapter is acceptable, return an empty list.",
        f"CHAPTER:\n{draft}\n\nReturn JSON: " '{"approved": true|false, "issues": ["..."]}')
    issues += verdict.get("issues", [])[:5]
    return {"ok": not issues, "issues": issues}


# ----------------------------------------------------------- Fact-checker
_cache = {}


def fetch(url):
    """status: ok | blocked (bot protection; fall back to excerpts) | dead (broken link)."""
    if url in _cache:
        return _cache[url]
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (book-factchecker)"})
        ctype = r.headers.get("content-type", "")
        if r.status_code in (401, 403, 429):
            res = {"status": "blocked", "text": ""}
        elif r.status_code >= 400:
            res = {"status": "dead", "text": f"HTTP {r.status_code}"}
        elif "text" in ctype or "html" in ctype:
            soup = BeautifulSoup(r.text, "html.parser")
            for t in soup(["script", "style", "nav", "footer"]):
                t.decompose()
            res = {"status": "ok", "text": re.sub(r"\s+", " ", soup.get_text(" "))[:15000]}
        else:  # e.g. PDF: link works, rely on excerpts
            res = {"status": "ok", "text": ""}
    except requests.RequestException as e:
        res = {"status": "dead", "text": str(e)[:100]}
    _cache[url] = res
    return res


def fact_checker(draft, pack):
    body, _ = split_takeaway(draft)
    by_id = {s["id"]: s for s in pack["sources"]}
    claims, issues, bad, uncited = {}, [], [], []
    for sent in sentences(body):
        ids = [int(x) for x in CITE.findall(sent)]
        if not ids:
            if re.search(r"\d", sent):  # any number or year without a citation is rejected outright
                issues.append(f'Uncited figure/date; add a supported citation or remove: "{sent}"')
                bad.append(sent)
            else:
                uncited.append(sent)  # judged below: is it a factual claim?
            continue
        for i in ids:
            if i not in by_id or by_id[i]["dead"]:
                issues.append(f'Citation [{i}] is not a valid source. Fix or remove: "{sent}"')
                bad.append(sent)
            else:
                claims.setdefault(i, []).append(sent)
    if uncited:  # catch facts that have no digits, e.g. "Brazil is the largest producer"
        listing = "\n".join(f"{n}. {c}" for n, c in enumerate(uncited))
        res = ask_json(
            "You are a strict fact-checker. From the numbered sentences, return those that state a verifiable "
            "fact about the real world (events, names, places, organisations, trends, causes, comparisons, "
            "statistics) and therefore need a citation. Do NOT return pure advice, encouragement, "
            "transitions, rhetorical questions or plain explanations of a word's everyday meaning.",
            f"SENTENCES:\n{listing}\n\nReturn JSON: " '{"needs_citation":[0]}')
        for n in res.get("needs_citation", []):
            if isinstance(n, int) and 0 <= n < len(uncited):
                issues.append(f'Factual claim without a citation; cite a source or remove: "{uncited[n]}"')
                bad.append(uncited[n])
    for i, sents in claims.items():
        s = by_id[i]
        page = fetch(s["url"])
        s["status"] = page["status"]
        if page["status"] == "dead":
            s["dead"] = True
            issues.append(f"Source [{i}] link is broken ({page['text']}). Do not use it; "
                          "rewrite or remove its claims.")
            bad += sents
            continue
        evidence = (page["text"] + "\n\nEXCERPTS:\n" + "\n".join(s["snippets"]))[:16000]
        listing = "\n".join(f"{n}. {c}" for n, c in enumerate(sents))
        res = ask_json(
            "You are a fact-checker. For each claim decide whether the SOURCE TEXT supports it. "
            "Be strict on numbers, dates and names; reasonable paraphrase is fine. A claim that goes "
            "beyond the source is 'unsupported'.",
            f"SOURCE TEXT:\n{evidence}\n\nCLAIMS (each cites this source):\n{listing}\n\n"
            'Return JSON: [{"i":0,"verdict":"supported|unsupported","reason":"short"}]')
        for v in res:
            if v.get("verdict") != "supported":
                c = sents[v["i"]]
                issues.append(f'Not supported by [{i}] ({v.get("reason", "")}). Fix or remove: "{c}"')
                bad.append(c)
    return {"ok": not issues, "issues": issues, "bad_sentences": list(dict.fromkeys(bad))}
