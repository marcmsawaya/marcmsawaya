# Identity system

One place that knows who I am, so anything writing in my name works from the same
facts, the same voice, and the same evidence — instead of me re-explaining myself to a
blank chat box every time.

## The layers

| File | Holds | Edited by |
| --- | --- | --- |
| `facts.json` | Structured, verifiable facts. Education, experience, projects, skills, guardrails. | Me |
| `voice.md` | How I write. Rules, banned phrases, register per context. | Me |
| `stories.md` | The evidence bank — tagged Situation/Task/Action/Result stories. | Me |
| `private.json` | GPA, phone, compensation, references. **Gitignored.** | Me |
| `CONTEXT.md` | Compiled pack, public-safe. | Generated — don't edit |

The split matters. Facts are checkable and belong in one place, so a wrong graduation
date is wrong once rather than in nine applications. Voice is stable across every
context. Stories are the part models otherwise invent, which is the failure mode worth
engineering against.

## Using it

```bash
python3 scripts/identity.py build      # compile CONTEXT.md after editing any layer
python3 scripts/identity.py check      # what's still unfilled
```

**To have any AI write as me**, paste `CONTEXT.md` into it, then ask for what I need.
It works in Claude, ChatGPT, Cursor, anything.

**To apply to a specific posting**, hand the script the posting and get a brief —
identity, voice, and the two or three pieces of evidence that actually match this role,
ranked by tag overlap, with the posting and the instructions attached:

```bash
python3 scripts/identity.py apply posting.txt --company Stripe --role "SWE Co-op"
pbpaste | python3 scripts/identity.py apply - --company Stripe --type outreach --stdout
```

`--type` is one of `cover-letter`, `short-answer`, `outreach`, `resume-bullets`, `bio`.
Add `--include-private` when the application actually asks for GPA or phone. Briefs land
in `applications/`, which is gitignored.

Then paste the brief into a model, or:

```bash
claude -p "$(cat applications/stripe-swe-co-op/cover-letter.md)"
```

## What it will not do

**It doesn't write the letter.** A script that fills my name into canned prose produces
exactly the letter every reader has learned to skip. The script does the part that is
mechanical and worth automating — never lose a fact, never leak a private one, put the
right evidence in front of the model — and leaves the writing to a model that can
actually write.

**It won't publish a placeholder as an accomplishment.** Any field that is null, empty,
or contains TODO is dropped from every compiled output and counted in a footer. A story
with real Situation and Task but unwritten Action and Result travels with the written
half only, flagged as partial. That is why `check` matters more than it looks: the system
is only as good as the layers, and it will stay quiet rather than lie about the gaps.

**It won't leak private data into the public repo.** This repository is my GitHub
profile. `CONTEXT.md` is compiled from public fields only; private values are rendered
into briefs, and briefs are gitignored.

## Start here

The system is wired and runs, but it is seeded from what my profile README already says.
In rough order of payoff:

1. `python3 scripts/identity.py check`, and fill the fields it lists — graduation date
   and work authorization gate almost every application.
2. Add real `experience` entries to `facts.json`. The placeholder is empty and is
   currently dropped.
3. Finish the three empty stories in `stories.md`, especially the one where something
   broke. Interviewers ask for failure more than for success.
4. Calibrate `voice.md`. Right now it is inferred from how the profile README reads —
   a decent guess, not a model of my voice. Paste in three real samples and have an AI
   rewrite the rules against them.
5. Rebuild, and check that `CONTEXT.md` reads like me.
