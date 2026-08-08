# Stories

The evidence bank. Facts say what is true; stories are what get told when a prompt asks
for an example. Every generated application pulls from here rather than inventing.

**Format.** Each story is an `##` heading, a `Tags:` line, and four labelled beats.
The tags are what the matcher scores against a job posting — tag generously and
concretely (`postgres`, not `databases`). The build script parses this file by that
structure, so keep the shape even when the prose changes.

**Rule.** A story goes in here only after it happened. An empty story bank produces
honest, thin applications; an invented one produces confident, disqualifying lies.

---

## Shipping and operating eight web properties

Tags: web, fullstack, frontend, next.js, react, node, deployment, dns, operations, ownership, maintenance, solo

- **Situation.** Eight live web properties plus a portfolio at marcsawaya.info, run
  concurrently alongside a double major.
- **Task.** Keep them all up and maintainable by one person — not just built, but
  operated: domains, deploys, breakages, updates.
- **Action.** TODO — what the stack actually is, what got standardized across
  properties so eight of them stay tractable, what got automated.
- **Result.** TODO — uptime, traffic, what stayed maintainable that otherwise wouldn't
  have. Any number that is real.

## Animating a contribution calendar under a proxy that strips JavaScript

Tags: python, svg, css, github-actions, automation, constraints, debugging, scraping, tooling

- **Situation.** I wanted the contribution grid on my profile to load in the way
  GitHub's own calendar does, rather than sit there as a static image.
- **Task.** Animate it inside a GitHub README, where images are served through a proxy
  that strips JavaScript.
- **Action.** Rendered the calendar as an SVG and gave each cell a CSS
  `animation-delay` derived from its column, so the squares sweep in left to right with
  no script at all. Data comes from the public contributions fragment — no token, no API
  scope — which meant the generator had to run in GitHub Actions rather than locally,
  because the sandbox's egress proxy only allows the API host.
- **Result.** The grid animates on every cold load and refreshes on a schedule.
  `scripts/contrib_svg.py` in this repository.

## TODO — an algorithms story

Tags: algorithms, icpc, competitive-programming, data-structures, problem-solving, pressure

- **Situation.** ICPC or a contest — which one, when.
- **Task.** The problem, and what made it hard.
- **Action.** The approach, the complexity, what got ruled out first.
- **Result.** Solved or not. Not solving it is a fine story if what I learned is real.

## TODO — a story where something broke

Tags: debugging, incident, recovery, ownership, judgment

- **Situation.** Interviewers ask for failure more than for success, and this is the
  slot that is always empty.
- **Task.** What was at stake.
- **Action.** How it got diagnosed, not just fixed.
- **Result.** What changed afterward so it couldn't recur.

## TODO — a story with other people in it

Tags: teamwork, collaboration, communication, disagreement, code-review

- **Situation.** A team project, a hackathon, a code review, a disagreement about an
  approach.
- **Task.** My role in it specifically.
- **Action.** What I did — including where I was wrong and changed my mind.
- **Result.** How it landed.
