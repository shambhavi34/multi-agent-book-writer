"""Give it a brief on ANY topic; it writes the book.

  python main.py "A short book on how coffee farming is affected by climate change"
  python main.py --file examples/upi_brief.txt
  python main.py                      (prompts you to type or paste a brief)
Pipeline: Brief parser -> Planner -> per chapter [Researcher -> (Writer -> Editor + Fact-checker) x N] -> book.md
"""
import re, json, os, argparse
import agents

LOG, REPORT, WARNINGS = [], [], []


def log(agent, msg):
    print(f"[{agent:<12}] {msg}")
    LOG.append({"agent": agent, "message": msg})


def drop_sentences(draft, bad):
    """Last resort: delete sentences the fact-checker could not verify."""
    for b in bad:
        draft = draft.replace(b, "")
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", draft))


def finalize(chapter, draft, pack):
    body, take = agents.split_takeaway(draft)
    order = []
    for m in agents.CITE.finditer(body):
        if int(m.group(1)) not in order:
            order.append(int(m.group(1)))
    num = {old: new for new, old in enumerate(order, 1)}
    body = agents.CITE.sub(lambda m: f"[{num[int(m.group(1))]}]", body)
    by_id = {s["id"]: s for s in pack["sources"]}
    used = [by_id[i] for i in order if i in by_id]
    refs = "\n".join(f"[{num[s['id']]}] {s['publisher']}, \"{s['title']}\", {s['url']}" for s in used)
    for s in used:
        REPORT.append({"chapter": chapter["number"], "ref": num[s["id"]], "publisher": s["publisher"],
                       "title": s["title"], "url": s["url"], "official_source": s["official"],
                       "link_check": s["status"]})
        if s["status"] == "blocked":
            WARNINGS.append(f"Ch{chapter['number']} [{num[s['id']]}] {s['url']}: site blocks bots; open it manually.")
    t = take[0] if take else "Takeaway: (missing)"
    return f"## Chapter {chapter['number']}: {chapter['title']}\n\n{body}\n\n{t}\n\n**References**\n\n{refs}\n"


def get_brief(args):
    if args.file:
        raw = open(args.file, encoding="utf-8").read()
    elif args.brief:
        raw = " ".join(args.brief)
    else:
        raw = input("Describe the book you want (topic, audience, tone, chapters, length): ").strip()
    if not raw:
        raise SystemExit("No brief given.")
    b = agents.parse_brief(raw)
    # command-line options override anything parsed from the text
    if args.chapters: b.chapters = args.chapters
    if args.min_words: b.min_words = args.min_words
    if args.max_words: b.max_words = args.max_words
    if args.rounds: b.max_rounds = args.rounds
    return b.clamp()


def main():
    ap = argparse.ArgumentParser(description="Generate a cited book from any brief.")
    ap.add_argument("brief", nargs="*", help="the brief, or just a topic")
    ap.add_argument("--file", help="read the brief from a text file")
    ap.add_argument("--chapters", type=int)
    ap.add_argument("--min-words", type=int)
    ap.add_argument("--max-words", type=int)
    ap.add_argument("--rounds", type=int, help="max revision rounds per chapter")
    b = get_brief(ap.parse_args())
    log("Brief", f"'{b.title}' | audience: {b.audience} | {b.chapters} chapters, {b.min_words}-{b.max_words} words")

    outline = agents.planner(b)
    log("Planner", "Book outline: " + " | ".join(c["title"] for c in outline["chapters"]))
    chapters_out, anchor, earlier = [], "", ""
    for ch in outline["chapters"]:
        log("Researcher", f"Chapter {ch['number']}: searching the web...")
        pack = agents.researcher(ch, b)
        log("Researcher", f"{len(pack['sources'])} sources, {sum(s['dead'] for s in pack['sources'])} dead")
        draft, feedback = None, []
        for rnd in range(1, b.max_rounds + 1):
            draft = agents.writer(b, outline, ch, pack, anchor, earlier, draft, feedback)
            ed, fc = agents.editor(draft, b), agents.fact_checker(draft, pack)
            log("Writer", f"Ch{ch['number']} round {rnd}: {len(draft.split())} words")
            log("Editor", "approved" if ed["ok"] else f"{len(ed['issues'])} issues")
            log("Fact-checker", "all citations verified" if fc["ok"] else f"{len(fc['issues'])} issues")
            if ed["ok"] and fc["ok"]:
                break
            feedback = ed["issues"] + fc["issues"]
        else:
            if not fc["ok"]:
                log("Orchestrator", "Out of rounds: removing unverified sentences, then re-checking")
                draft = drop_sentences(draft, fc["bad_sentences"])
                ed, fc = agents.editor(draft, b), agents.fact_checker(draft, pack)
            if not (ed["ok"] and fc["ok"]):
                WARNINGS.append(f"Ch{ch['number']} shipped with open issues: {(ed['issues'] + fc['issues'])[:3]}")
                log("Orchestrator", "WARNING: shipped with open issues (see warnings)")
        body = agents.split_takeaway(draft)[0]
        if not anchor:
            anchor = "\n".join(body.split("\n")[:2])
        earlier += agents.summarise(ch["number"], ch["title"], body) + "\n"
        chapters_out.append(finalize(ch, draft, pack))

    out = os.path.join("output", b.slug())
    os.makedirs(out, exist_ok=True)
    open(f"{out}/book.md", "w", encoding="utf-8").write(f"# {b.title}\n\n" + "\n\n".join(chapters_out))
    json.dump({"brief": b.__dict__, "outline": outline, "log": LOG, "warnings": WARNINGS},
              open(f"{out}/run_log.json", "w"), indent=2)
    json.dump(REPORT, open(f"{out}/citation_report.json", "w"), indent=2)
    log("Orchestrator", f"Done -> {out}/book.md ({len(WARNINGS)} warnings)")


if __name__ == "__main__":
    main()
