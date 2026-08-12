# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Digital signage for the USMA (West Point) Library — a set of self-contained HTML pages meant to be
opened full-screen on lobby/kiosk displays (TVs, portrait monitors) and left running. There is no
build step, no bundler, no package.json, and no test suite. Each `.html` file is a complete
standalone page: inline `<style>` and inline `<script>`, no shared JS/CSS files, no framework.

## Architecture: two-branch split

- **`main`** — the HTML pages themselves, served via GitHub Pages at
  `https://usmalibrary.github.io/signage/`. This is the branch you'll normally be editing.
- **`data`** — *only* JSON data files (mirrors the `data/` folder), updated exclusively by GitHub
  Actions bots on a schedule. Pages fetch their data from this branch via
  `https://raw.githubusercontent.com/USMALibrary/signage/data/data/<file>.json`, so a display never
  needs a redeploy to pick up fresh data — it just polls raw.githubusercontent.com.

Do not hand-edit files under `data/` on `main` expecting them to reach production — that folder on
`main` is effectively a local snapshot/fixture; the live data lives on the `data` branch and is
overwritten by the workflows below. If you need to inspect current live data, check out or fetch the
`data` branch.

## Data pipeline (`.github/workflows/*.yml` + root `*.py` scripts)

Four scheduled workflows check out the `data` branch, run a Python script (stdlib only — `urllib`,
no `requests`), and commit+push the resulting JSON back to `data`:

| Workflow | Script | Output | Source | Schedule |
|---|---|---|---|---|
| `fetch-hours.yml` | (inline `curl`, no script) | `hours-today.json`, `hours-weekly.json` | LibCal Hours API | every 15 min |
| `libcal-spaces.yml` | `space_bookings.py` | `room-reservations.json` | LibCal Space Bookings API (OAuth) | every 15 min, business hours |
| `instruction.yml` | `instruction_events.py` | `instruction-stats.json` | LibCal Events API (OAuth) | every 15 min, business hours |
| `alma-usage.yml` | `alma_usage.py` | `circulation-usage.json` | Alma Analytics API (XML) | daily |

Each script follows the same shape: read creds from env vars, hit the API with `urllib`, write a
JSON summary to `data/<name>.json`, and print a short log line. The workflow then does
`git add`, commit, `pull --rebase`, `push` (with a retry-after-rebase fallback) against `origin data`
— because multiple workflows write to the same branch concurrently, always keep that
rebase-then-push-with-retry pattern if you touch the commit step.

Some data files (`visitor-count.json`, `papercut-status.json`, `on-call.json`,
`help-needed.json`, `help-needed-frontdesk.json`) are **not** produced by any workflow in this repo —
they're pushed to the `data` branch by an external system. Don't assume every file in `data/` has a
corresponding fetcher here.

`elevator-notices.json` is different again: nothing — no workflow, no external system — writes it.
It has to be edited by hand directly on the `data` branch (editing `data/elevator-notices.json` on
`main` has no effect on `elevator.html`, which only reads from `data`). This was a real gap: the file
existed only on `main` until 2026-08-12 and the notices panel was silently always showing its
hardcoded default. Whether this stays a hand-edited JSON file is an open question — the library may
instead manage elevator (and other) sign content through Rise Vision's built-in content playlists,
depending on how comfortable the staff doing the day-to-day updates are with editing JSON on a git
branch vs. using Rise Vision's UI. Check with the maintainer before building more tooling around
hand-edited `data/*.json` content files.

`alma_usage.py` writes a debug dump of the raw first-page API response to
`data/.alma-debug-response.xml` on every run — useful for diagnosing Alma schema changes (the report
has no column-name headers, so columns are identified by XSD type, not name).

## Front-end page conventions

Every signage page follows the same unwritten template — match it when adding or editing pages:

- Fixed pixel canvas sized for the target screen: `1920x1080` for landscape TVs, `1080` width
  (portrait, height varies) for vertical displays. Body has explicit `width`/`height` and
  `overflow: hidden`.
- An IIFE at the end of `<script>` rescales `document.body` with `transform: scale(...)` to fit
  whatever the browser viewport actually is (`AUTO-SCALE TO FIT BROWSER WINDOW` comment block) —
  copy this block verbatim into new pages rather than reinventing it.
- A `loadJSON(url, callback, errCallback)` XHR helper (cache-busted with `?v=' + Date.now()`),
  polling on `setInterval(loadAll, 60000)` or similar. On fetch failure, panels show a
  "Feed unavailable" / "NO DATA" state rather than crashing — preserve that fallback when adding a
  new panel.
- Newer pages (`admin-office*.html`, `elevator.html`, `hours-v2.html`, `hours-sign.html`) fetch
  straight from the `data` branch's raw.githubusercontent.com JSON. Older pages (`hours.html`,
  `research-lab.html`) instead fetch third-party APIs directly client-side through a public CORS
  proxy (`corsproxy.io`) — this is the pattern being migrated away from, so prefer the data-branch
  approach for new work. `-v2` filenames mark that migration in progress; check whether the `-v2`
  or non-`-v2` file is the one actually linked from signage players before editing either.
- Where "open/closed" needs to be derived from LibCal hours, it's computed client-side from the raw
  hour ranges (`isLocationOpen` / `parseTimeToMinutes`) rather than trusting the feed's own
  open/closed flag — LibCal's flag has been unreliable historically, so keep computing it locally.
- Dark theme, gold accent (`--gold: rgb(200,170,100)` or similar) is the house style; the
  `Oswald` (headings/numbers) + `Open Sans` (body) Google Fonts pairing is standard across pages.
- Color-coded status conventions to reuse: green = OK/clear/open, red/`--alert` = help needed/error
  (usually with a `pulse` animation), amber = stale data warning, gold = brand/neutral emphasis.
- "STALE" badges: most panels compare `data.updated` against `Date.now()` and flag data older than
  ~15–30 minutes rather than silently showing outdated numbers.

## Working on a page

There's no local dev server needed — open the `.html` file directly in a browser. Since pages pull
live data from `raw.githubusercontent.com/USMALibrary/signage/data/...`, testing locally still hits
real production data feeds; there's no mock/staging data source.

Because there's no shared JS between pages, a fix to e.g. the clock or auto-scale logic needs to be
applied to every page that has its own copy, not just one file — `grep` across `*.html` before
assuming a change is complete.
