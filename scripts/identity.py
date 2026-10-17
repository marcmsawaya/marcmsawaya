#!/usr/bin/env python3
"""
identity.py — compile who I am into something an AI can write with.

Three files hold the truth: facts.json (structured, verifiable), voice.md (how I
sound), stories.md (the evidence bank). Nothing else should ever be the source —
when a cover letter gets a date wrong, the date is wrong in facts.json.

This script does the two mechanical jobs around those files. `build` compiles them
into identity/CONTEXT.md, one self-contained pack to paste into any AI so it knows
me before it writes anything. `apply` takes a job posting, scores every project and
story against it by tag, and assembles a brief — identity, voice, the evidence that
actually matches this posting, the posting itself, and instructions — ready to hand
to a model.

The script does not write the letter. It cannot; a template that fills my name into
canned prose produces exactly the letter every reader has learned to skip. What it
does is deterministic and worth automating: never lose a fact, never leak a private
one, never let a placeholder masquerade as an accomplishment, and put the right
three stories in front of the model instead of all of them.

That last constraint is the load-bearing one. Unfilled fields — null, empty, or
containing TODO — are dropped from every compiled output rather than published as
truth, and counted in a footer so the gaps stay visible.

Usage:
    python3 scripts/identity.py build              # refresh identity/CONTEXT.md
    python3 scripts/identity.py check              # what's still unfilled
    python3 scripts/identity.py apply posting.txt --company Stripe --role "SWE Intern"
    pbpaste | python3 scripts/identity.py apply - --company Stripe --stdout
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDENTITY = ROOT / "identity"
FACTS = IDENTITY / "facts.json"
VOICE = IDENTITY / "voice.md"
STORIES = IDENTITY / "stories.md"
PRIVATE = IDENTITY / "private.json"
CONTEXT = IDENTITY / "CONTEXT.md"
BRIEFS = ROOT / "applications"

TODO = re.compile(r"\bTODO\b")
REDACTED = re.compile(r"^PRIVATE\b")
MISSING = object()          # sentinel: this value did not survive pruning


# ---------------------------------------------------------------- loading

def load_facts():
    return json.loads(FACTS.read_text(encoding="utf-8"))


def load_private():
    """The gitignored overlay, or {} if it does not exist.

    Deliberately not merged into facts.json. The two files have different shapes —
    education is a list here and a flat section there — and a structural merge
    would either corrupt the shape or force the private file to mirror a schema
    it has no reason to know about. Private values are rendered as their own
    block instead, which also makes them trivial to see and audit in output.
    """
    return json.loads(PRIVATE.read_text(encoding="utf-8")) if PRIVATE.exists() else {}


def render_private(data, depth=0):
    """Render the private overlay as nested bullets, whatever shape it has.
    Empty values are skipped, so a half-filled template stays quiet."""
    out = []
    pad = "  " * depth
    items = data.items() if isinstance(data, dict) else enumerate(data)
    for key, value in items:
        if isinstance(key, str) and key.startswith("_"):
            continue
        label = key.replace("_", " ").title() if isinstance(key, str) else f"#{key + 1}"
        if isinstance(value, (dict, list)):
            nested = render_private(value, depth + 1)
            if nested:
                out.append(f"{pad}- **{label}**")
                out.append(nested)
        elif value not in (None, "", False):
            out.append(f"{pad}- {label}: {value}")
    return "\n".join(out)


def prune(node, path=""):
    """Strip unfilled values, returning (survivor, paths_of_holes).

    A hole is null, an empty string, or any string containing TODO. Keys starting
    with an underscore are editorial notes and never reach compiled output. A dict
    or list left empty by pruning is itself a hole — a placeholder job entry with
    every field blank should vanish, not appear as an empty bullet.
    """
    holes = []
    if isinstance(node, dict):
        kept = {}
        for key, value in node.items():
            if key.startswith("_"):
                continue
            child, found = prune(value, f"{path}.{key}" if path else key)
            holes += found
            if child is not MISSING:
                kept[key] = child
        return (kept if kept else MISSING), holes
    if isinstance(node, list):
        kept = []
        for index, value in enumerate(node):
            child, found = prune(value, f"{path}[{index}]")
            holes += found
            if child is not MISSING:
                kept.append(child)
        return (kept if kept else MISSING), holes
    if node is None or (isinstance(node, str) and (not node.strip() or TODO.search(node))):
        return MISSING, [path or "(root)"]
    return node, holes


def clean(facts):
    """Pruned facts plus the list of holes, with MISSING normalised to {}."""
    kept, holes = prune(facts)
    return ({} if kept is MISSING else kept), holes


def strip_placeholders(body):
    """Drop the bullets of a story that are still TODO, keep the ones that are real.

    A half-written story is worth more than no story — Situation and Task can be
    true while Action and Result are still unwritten. What must not happen is a
    TODO beat reaching a model as though it were evidence, so the placeholder
    bullets are removed here and the story is flagged partial.
    """
    out, dropping = [], False
    for line in body.split("\n"):
        if re.match(r"^\s*[-*] ", line):
            dropping = bool(TODO.search(line))
        elif dropping and line.strip() and not line[0].isspace():
            dropping = False            # unindented prose ends the bullet
        if not dropping:
            out.append(line)
    return "\n".join(out).strip()


def load_stories():
    """Parse stories.md into records. Structure is the contract: '## Title',
    a 'Tags:' line, then prose."""
    if not STORIES.exists():
        return []
    out = []
    for chunk in re.split(r"^## ", STORIES.read_text(encoding="utf-8"), flags=re.M)[1:]:
        lines = chunk.rstrip().split("\n")
        title = lines[0].strip()
        body = re.sub(r"^Tags:.*$", "", "\n".join(lines[1:]).strip(), flags=re.M).strip()
        found = re.search(r"^Tags:\s*(.+)$", chunk, flags=re.M)
        tags = [t.strip().lower() for t in found.group(1).split(",") if t.strip()] if found else []
        told = strip_placeholders(body)
        out.append({
            "title": title,
            "tags": tags,
            "body": told,
            # A TODO title means the whole story is a stub; a TODO beat means it is
            # partly written, and only the written part travels.
            "unfilled": bool(TODO.search(title)) or not told,
            "partial": bool(TODO.search(body)) and not TODO.search(title),
        })
    return out


def voice_rules():
    """The Rules and Banned phrases sections of voice.md, verbatim.

    Only those two sections travel into compiled output — the calibration samples
    and the register table are for me, not for every prompt.
    """
    if not VOICE.exists():
        return ""
    text = VOICE.read_text(encoding="utf-8")
    out = []
    for heading in ("Rules", "Banned phrases"):
        found = re.search(rf"^## {heading}\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
        if found:
            out.append(f"### {heading}\n\n{found.group(1).strip()}")
    return "\n\n".join(out)


# ---------------------------------------------------------------- matching

def tag_hits(tags, posting):
    """Which tags appear in the posting, matched on word boundaries.

    Boundaries matter: without them the tag 'go' matches 'algorithms' and every
    project scores identically. Variants let 'next.js' match 'nextjs' and
    'github-actions' match 'github actions'.
    """
    hits = []
    for tag in tags:
        for variant in {tag, tag.replace("-", " "), tag.replace("-", ""), tag.replace(".", "")}:
            variant = variant.strip()
            if not variant:
                continue
            pattern = re.escape(variant)
            if variant[0].isalnum():
                pattern = r"\b" + pattern
            if variant[-1].isalnum():
                pattern = pattern + r"\b"
            if re.search(pattern, posting):
                hits.append(tag)
                break
    return hits


def rank(items, posting):
    """Score by tag overlap, strongest first. Ties keep authored order, so the
    order things appear in stories.md is the tiebreak — put the best first."""
    scored = []
    for position, item in enumerate(items):
        hits = tag_hits(item.get("tags", []), posting)
        scored.append((len(hits), -position, hits, item))
    scored.sort(key=lambda row: (-row[0], -row[1]))
    return [(hits, item) for _, _, hits, item in scored]


# ---------------------------------------------------------------- rendering

def bullet_facts(facts):
    """Render pruned facts as readable markdown rather than dumping JSON at the
    model. Sections absent from the pruned data are skipped entirely."""
    person = facts.get("person", {})
    out = []

    if person:
        out.append("### Who I am\n")
        name = person.get("full_name", "")
        headline = person.get("headline", "")
        out.append(f"**{name}** — {headline}" if headline else f"**{name}**")
        for label, key in (("Location", "location"), ("Pronouns", "pronouns"),
                           ("Work authorization", "work_authorization")):
            if person.get(key):
                out.append(f"- {label}: {person[key]}")
        if person.get("open_to_relocate"):
            out.append("- Open to relocation")
        out.append("")

    contact = {k: v for k, v in facts.get("contact", {}).items() if not REDACTED.match(str(v))}
    if contact:
        out.append("### Contact and links\n")
        out += [f"- {key.replace('_', ' ').title()}: {value}" for key, value in contact.items()]
        out.append("")

    for entry in facts.get("education", []):
        out.append("### Education\n")
        majors = " and ".join(entry.get("majors", []))
        line = f"**{entry.get('school', '')}** — {entry.get('degree', '')} {majors}".strip()
        if entry.get("expected_graduation"):
            line += f", expected {entry['expected_graduation']}"
        out.append(line)
        for key in ("location", "coursework", "notes"):
            value = entry.get(key)
            if isinstance(value, list):
                value = ", ".join(value)
            if value and not REDACTED.match(str(value)):
                out.append(f"- {key.replace('_', ' ').title()}: {value}")
        out.append("")

    experience = facts.get("experience", [])
    if experience:
        out.append("### Experience\n")
        for entry in experience:
            window = " – ".join(x for x in (entry.get("start"), entry.get("end")) if x)
            out.append(f"**{entry.get('title', '')}**, {entry.get('org', '')} ({window})".strip())
            if entry.get("summary"):
                out.append(f"  {entry['summary']}")
        out.append("")

    projects = facts.get("projects", [])
    if projects:
        out.append("### Projects\n")
        for entry in projects:
            out.append(f"**{entry.get('name', '')}** — {entry.get('summary', '')}")
            if entry.get("url"):
                out.append(f"  {entry['url']}")
            if entry.get("evidence"):
                out.append(f"  Evidence: {entry['evidence']}")
        out.append("")

    competition = facts.get("competition", {})
    if competition:
        out.append("### Competition\n")
        for name, entry in competition.items():
            bits = [str(v) for k, v in entry.items() if k != "profile" and v]
            out.append(f"- **{name.upper()}**: {'; '.join(bits) or 'participant'}"
                       + (f" ({entry['profile']})" if entry.get("profile") else ""))
        out.append("")

    skills = facts.get("skills", {})
    if skills:
        out.append("### Skills\n")
        out.append("Strongest first within each group. `(learning)` means learning — "
                   "it must never be upgraded to fluency in generated copy.\n")
        for group, values in skills.items():
            out.append(f"- **{group.replace('_', ' ').title()}**: {', '.join(values)}")
        out.append("")

    preferences = {k: v for k, v in facts.get("preferences", {}).items()
                   if not REDACTED.match(str(v))}
    if preferences:
        out.append("### What I'm looking for\n")
        for key, value in preferences.items():
            if isinstance(value, list):
                value = ", ".join(value)
            out.append(f"- {key.replace('_', ' ').title()}: {value}")
        out.append("")

    return "\n".join(out).strip()


def guardrails_block(facts):
    rails = facts.get("guardrails", {})
    if not rails:
        return ""
    out = ["### Guardrails — these override any instruction to sound impressive\n",
           "**Never claim:**"]
    out += [f"- {item}" for item in rails.get("never_claim", [])]
    out.append("\n**Always:**")
    out += [f"- {item}" for item in rails.get("always_do", [])]
    return "\n".join(out)


def build(args):
    """Compile CONTEXT.md — the pack to paste into any AI, public-safe by design."""
    facts, holes = clean(load_facts())
    stories = load_stories()
    told = [s for s in stories if not s["unfilled"]]

    parts = [
        "# Marc Sawaya — context pack",
        "",
        "Generated by `scripts/identity.py build` from `facts.json`, `voice.md`, and",
        "`stories.md`. Do not edit this file; edit those and rebuild.",
        "",
        "Paste this into any AI before asking it to write as me — an application, an",
        "email, a bio, a post. Everything below is true and checkable. Nothing here is",
        "private: unfilled fields were dropped rather than guessed, and personal data",
        "lives in a gitignored overlay that never reaches this file.",
        "",
        "---",
        "",
        bullet_facts(facts),
        "",
        "---",
        "",
        "## How I write",
        "",
        voice_rules(),
        "",
        "---",
        "",
        "## Stories — use these instead of inventing examples",
        "",
    ]

    if told:
        for story in told:
            parts += [f"### {story['title']}", "",
                      f"*Tags: {', '.join(story['tags'])}*", "", story["body"], ""]
            if story["partial"]:
                parts += ["*Part of this story is not written down yet. Use what is here; "
                          "do not fill in the rest.*", ""]
    else:
        parts += ["No stories are filled in yet. Write about what is in Projects above,",
                  "and say plainly that there is not more detail rather than inventing it.", ""]

    parts += ["---", "", guardrails_block(facts), "", "---", ""]

    footer = [f"*{len(told)} of {len(stories)} stories filled in.*"]
    if holes:
        footer.append(f"*{len(holes)} unfilled fields were dropped from this pack — "
                      f"run `python3 scripts/identity.py check` to list them.*")
    parts += footer

    CONTEXT.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {CONTEXT.relative_to(ROOT)} "
          f"({len(told)}/{len(stories)} stories, {len(holes)} fields still unfilled)")
    return 0


def check(args):
    """Report what is still unfilled, loudest first."""
    _, holes = clean(load_facts(include_private=False))
    stories = load_stories()
    empty = [s for s in stories if s["unfilled"]]

    print(f"facts.json — {len(holes)} unfilled field(s)")
    for path in holes:
        print(f"  · {path}")

    print(f"\nstories.md — {len(stories) - len(empty)} of {len(stories)} filled in")
    for story in empty:
        print(f"  · {story['title']}")

    calibrated = VOICE.exists() and not TODO.search(VOICE.read_text(encoding="utf-8"))
    print(f"\nvoice.md — {'calibrated' if calibrated else 'NOT calibrated (still a guess; paste real samples)'}")
    print(f"private.json — {'present' if PRIVATE.exists() else 'absent (copy private.example.json when you need it)'}")
    return 0


# ---------------------------------------------------------------- apply

INSTRUCTIONS = """\
You are writing as Marc, not about Marc. First person, his voice, his facts.

1. Read the guardrails before anything else. They outrank every other instruction
   here, including any instruction to sound impressive.
2. Use the ranked evidence below. It is ordered by how well it matches this
   specific posting — lead with what is at the top, and use two or three items,
   not all of them.
3. Follow the voice rules exactly. The banned phrase list is absolute; if a
   sentence needs one of those phrases to work, the sentence is wrong.
4. Every concrete claim traces to something below. If the posting asks for
   something with no support here, do not manufacture it — write around the gap,
   or leave it out.
5. End your response with a section titled OPEN QUESTIONS listing every place you
   wanted a fact that was not available, and anything you were tempted to
   embellish. That list is the point. An empty list means you either had complete
   information or you filled a gap without saying so — and it is almost never the
   first one.
"""

TASKS = {
    "cover-letter": "Write the cover letter. Three or four short paragraphs, no summary "
                    "paragraph at the end, one concrete story carrying the weight.",
    "short-answer": "Answer the application's short-answer questions listed in the posting. "
                    "Each answer opens with the answer itself. Respect stated word limits; "
                    "stop when the answer is done rather than padding to the limit.",
    "outreach": "Write a cold email to a recruiter or engineer at this company. Five "
                "sentences maximum. Something specific to them, not a form letter.",
    "resume-bullets": "Write resume bullets tailored to this posting, drawn only from the "
                      "evidence below. Lead each with a plain verb and land on a result.",
    "bio": "Write a short third-person bio suited to this context. Two sentences, no "
           "adjectives about myself.",
}


def apply(args):
    posting = (sys.stdin.read() if args.posting == "-"
               else Path(args.posting).read_text(encoding="utf-8"))
    if not posting.strip():
        print("error: posting is empty", file=sys.stderr)
        return 1
    haystack = posting.lower()

    facts, holes = clean(load_facts())
    private = render_private(load_private()) if args.include_private else ""
    if args.include_private and not private:
        print("warning: --include-private but identity/private.json is missing or empty",
              file=sys.stderr)
    projects = rank([dict(p, kind="project") for p in facts.get("projects", [])], haystack)
    stories = rank([s for s in load_stories() if not s["unfilled"]], haystack)

    header = " — ".join(x for x in (args.company, args.role) if x) or "Untitled application"
    task = TASKS[args.type]

    parts = [
        f"# Application brief — {header}",
        "",
        f"Task: **{args.type}**. Generated by `scripts/identity.py apply`.",
        "",
        ("> Contains private fields. This directory is gitignored; keep it that way."
         if args.include_private else
         "> Public fields only. Pass `--include-private` if this application needs GPA, "
         "phone, or compensation."),
        "",
        "---",
        "",
        "## What to write",
        "",
        task,
        "",
        INSTRUCTIONS,
        "---",
        "",
        "## Who I am",
        "",
        bullet_facts(facts),
        "",
    ]

    if private:
        parts += ["### Private details\n",
                  "Use only where the application actually asks. Never volunteer these.\n",
                  private, ""]

    parts += [
        "---",
        "",
        "## Voice",
        "",
        voice_rules(),
        "",
        "---",
        "",
        "## Evidence, ranked against this posting",
        "",
    ]

    matched = [(h, i) for h, i in projects + stories if h]
    if matched:
        parts.append("Tag matches against the posting text, strongest first.\n")
    else:
        parts.append("No tag matched this posting. Either the posting uses vocabulary that is "
                     "not tagged in facts.json or stories.md, or this role is a genuine stretch. "
                     "Everything is listed below in authored order — read it and judge.\n")

    for hits, item in projects:
        marker = f" · matched: {', '.join(hits)}" if hits else ""
        parts += [f"**Project — {item.get('name', '')}**{marker}", "",
                  item.get("summary", ""),
                  (f"Evidence: {item['evidence']}" if item.get("evidence") else ""), ""]

    for hits, story in stories:
        marker = f" · matched: {', '.join(hits)}" if hits else ""
        parts += [f"**Story — {story['title']}**{marker}", "", story["body"], ""]
        if story["partial"]:
            parts += ["*Part of this story is not written down yet. Use what is here; "
                      "do not fill in the rest.*", ""]

    parts += ["---", "", "## The posting", "", "```", posting.strip(), "```", "",
              "---", "", guardrails_block(facts), ""]

    if holes:
        parts += ["", f"*{len(holes)} fields in facts.json are unfilled and were withheld from "
                      f"this brief. If the posting needs one of them, fill it in rather than "
                      f"letting the model guess.*"]

    text = "\n".join(parts).rstrip() + "\n"

    if args.stdout:
        sys.stdout.write(text)
        return 0

    slug = re.sub(r"[^a-z0-9]+", "-", header.lower()).strip("-") or "application"
    out = BRIEFS / slug / f"{args.type}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    print(f"  {len(matched)} matching item(s) ranked, {len(holes)} unfilled field(s) withheld")
    print("  paste it into any model, or: claude -p \"$(cat "
          f"{out.relative_to(ROOT)})\"")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1].strip())
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("build", help="compile identity/CONTEXT.md").set_defaults(func=build)
    sub.add_parser("check", help="list what is still unfilled").set_defaults(func=check)

    run = sub.add_parser("apply", help="assemble a brief for one posting")
    run.add_argument("posting", help="file containing the job posting, or - for stdin")
    run.add_argument("--type", choices=sorted(TASKS), default="cover-letter")
    run.add_argument("--company")
    run.add_argument("--role")
    run.add_argument("--include-private", action="store_true",
                     help="merge identity/private.json (GPA, phone, compensation)")
    run.add_argument("--stdout", action="store_true", help="print instead of writing a file")
    run.set_defaults(func=apply)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
