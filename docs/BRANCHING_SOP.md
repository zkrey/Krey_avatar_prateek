# Branching SOP — one source of truth

**Read this before creating a branch or starting new work.** It exists because the repo
once had four overlapping branches (`feat/*`, `claude/*`) with work split and duplicated
across them. That is now consolidated. Do not recreate it.

## The rule

**`main` is the single source of truth.** It holds the complete app: the Service A
backend, the render/bench work, and the full `/tester` QA console. Deploy from `main`,
branch from `main`, merge back into `main`.

There are **no** long-lived parallel branches. No `feat/*` vs `claude/*` "canonical"
copies of the same thing. One line of history.

## Taxonomy — the naming scheme (exact)

Every branch name is **`type/scope-detail`**, all lowercase, words hyphenated.

```
      feat / wardrobe-tab
      ────   ────────────
      type    scope-detail
```

**`type`** — one of these, and only these:

| Type | Use for | Example |
|---|---|---|
| `feat/` | a new capability or surface | `feat/wardrobe-tab` |
| `fix/` | a bug fix | `fix/fit-score-rounding` |
| `docs/` | docs only, no code | `docs/doctrine-update` |
| `chore/` | deps, config, tooling, cleanup | `chore/bump-fastapi` |
| `bench/` | benchmark / measurement work | `bench/catvton-gpu-seconds` |

**`scope-detail`** — what's inside, specific enough to know before opening: the surface,
module, or subject touched (`frontend-identity-tab`, `capture-session`, `railway-deploy`).
Not vague (`update`, `changes`, `wip`), not a bare type (`feat/feat`).

**Rules for the name:**
- Lowercase, hyphen-separated; no spaces, no `/` beyond the single `type/` separator.
- The name alone must say what the branch contains. If it doesn't, rename it.
- One concern per branch — if you need "and" in the name, split it.

**Reserved / special:**
- `main` — the one canonical branch. Never a `type/` prefix; never deleted.
- `claude/<name>-<id>` — **auto-generated** by Claude Code sessions (`claude/` = the
  session, `<name>` = topic, `<id>` = uniqueness). Temporary only: land its work in
  `main` via PR, then delete it. Never a second home for canonical code.

Do **not** invent new top-level prefixes, and do **not** create a readable "alias" of an
existing branch — rename through a PR into `main` instead.

## Starting new work

```bash
git checkout main
git pull origin main
git checkout -b type/scope-detail      # e.g. feat/wardrobe-tab
```

- **Name it per the Taxonomy above** — `type/scope-detail`, and the name must say
  what's inside before anyone opens it.
- **One concern per branch.** Don't bundle unrelated changes.
- **Branch from `main`,** never from another feature branch (that's how work splits).

## Finishing work

1. Rebase or merge latest `main` in, resolve conflicts.
2. Validate (see below).
3. Open a PR into `main`. Merge it.
4. **Delete the feature branch** after merge — no stale copies left behind.

## Automated (Claude Code) sessions

Sessions may auto-generate a `claude/<name>-<id>` working branch. That is fine as a
*temporary* work branch, but its output must land in `main` via PR and the `claude/*`
branch must be **deleted after merge**. Never treat a `claude/*` branch as a second
canonical home for code.

## Never

- Never keep two branches holding the same work under different names ("aliases").
- Never push the same commits to a second branch for "better naming" — rename via PR
  into `main` instead.
- Never start a feature from a branch other than `main`.
- Never let `main` fall behind a feature branch as the "real" code — `main` is the real code.

## Validate before every push / PR

```bash
python -m pytest tests/ -q                 # backend (pure-math tests need no models)
# if you touched app/webtest.html, syntax-check the embedded JS:
python - <<'PY'
import re; s=open("app/webtest.html").read()
open("/tmp/tester.js","w").write(re.search(r"<script>(.*)</script>",s,re.S).group(1))
PY
node --check /tmp/tester.js
```

Heavy deps (cv2/mediapipe/insightface) are lazy-imported; the pure-math suite runs
without them. Endpoint tests that import `cv2` need the full stack.

## Deploy

Railway (and any host) deploys **`main`**. The `Dockerfile` builds the whole engine
(deps + MediaPipe models baked in + InsightFace `buffalo_l` pre-warmed for the identity
algo). Point the service's branch at `main`.
