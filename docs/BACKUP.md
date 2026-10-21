# Krey — Backup & continuity doctrine ("D-day" readiness)

_Doctrine + runbook, captured 2026-10-21. The rule: **the knowledge of Krey must live in
more than one place at all times, and never depend on a single account, session, or chat
transcript.** This is a standing practice, not a one-off. Treat it like `BRANCHING_SOP.md`:
something we *do*, not just wrote down._

---

## The one rule

> **No single point of failure for the knowledge.** Every durable decision lives in the git
> repo (human-readable, no secrets); the repo lives in at least two independent places; and
> no secret ever lives in the repo at all.

A chat account, a session, or a transcript can be lost, locked, or expire. The repo — being
distributed git — cannot be lost as long as **one** clone or remote survives. So we make the
repo the source of truth and keep more than one copy of it.

## Why the repo, not the chat

- **Git is distributed by design.** Every clone and every remote is a complete, independent
  copy with full history. "Many backups" is the default state of git, not an extra feature.
- **The `docs/` folder is the institutional memory.** `DECISIONS.md` is the plain-language
  record of what we built and why; the other docs hold the thesis, doctrine, schema and ops.
  Anyone — a future us, a new collaborator — can rebuild context from `docs/` alone.
- **A chat transcript is not a backup.** It's unstructured, tied to one account, and (fatal)
  **full of live secrets** (tokens, keys, PATs). It must never be the thing we rely on.

## The three layers (keep all three live)

| Layer | What | How often |
|---|---|---|
| **A · Decision log** | `docs/DECISIONS.md` kept current — the no-secrets memory | update whenever a decision changes |
| **B · A second remote** | the repo mirrored to a **second, independent GitHub account/org** | one `git push` keeps it in sync |
| **C · A local clone** | a full copy on a laptop / drive, offline | `git clone` / `git pull` anytime |

A is the *content*. B and C are *independent copies* of it. D-day readiness = all three exist.

## Runbook

### A — keep the decision log current
When a real decision is made or changed, edit `docs/DECISIONS.md` (and the relevant thesis
doc) in the same change as the code. The log is only a backup if it's not stale.

### B — add / sync the second remote (off-site copy)
Once a backup repo exists on a **different** GitHub account you control (so losing the primary
account doesn't lose both):

```sh
# one-time: point a 'backup' remote at the second repo
git remote add backup https://github.com/<other-owner>/<repo>.git

# every time you want to sync everything (all branches + tags):
git push backup --all
git push backup --tags
```

Keeping the second repo under a **different owner/email** is the whole point — it's what
survives if the primary account is lost.

### C — pull a local clone (offline copy)
```sh
git clone https://github.com/zkrey/Krey_avatar_prateek.git
# refresh it periodically:
cd Krey_avatar_prateek && git pull --all
```
Keep at least one clone somewhere that isn't a cloud session (a laptop, an external drive).

## The secrets rule (non-negotiable)

**No secret ever enters the repo** — not in code, commit messages, PR bodies, comments, or
any backed-up file. Secrets (the admin token, Gemini key, GitHub PAT, Supabase keys) live
**only in Railway env** and are referenced by *variable name* in docs, never by value.

Consequence for backups: because the repo has no secrets, it is **safe to mirror and clone
anywhere**. The chat transcript, by contrast, **does** contain live secrets, so:
- Never commit a raw transcript into the repo or push it to any backup.
- Treat any credential that has appeared in chat as **exposed** and **rotate it**:
  - GitHub PAT → GitHub → Settings → Developer settings → revoke + reissue; update it on
    Railway (service `krey-labs`).
  - `KREY_ADMIN_TOKEN`, `GEMINI_API_KEY`, Supabase keys → rotate at the provider, update the
    Railway env var, redeploy.
- Rotation is an operational task, done when convenient; the repo backup does not wait on it.

## Account-level note (what backups can and can't do)

- There is **no way to mirror a Claude/Anthropic account to a second email.** Account
  recovery info protects *access*; it is not a second copy. Multi-person ownership is a
  **Team/Org plan** (separate seats), not a backup email.
- This is exactly why the doctrine puts the knowledge in **git**, not in the account: the
  thing we must not lose is portable and already multi-location by design.

## Checklist — are we D-day ready?

- [ ] `docs/DECISIONS.md` reflects the latest decisions (not stale).
- [ ] A `backup` remote exists on a **different** GitHub account; `git push backup --all` is current.
- [ ] At least one local clone exists off-session, pulled recently.
- [ ] No secret anywhere in the repo; any credential seen in chat has been rotated.

---

_See also: `DECISIONS.md` (the knowledge it protects), `BRANCHING_SOP.md` (branch ops),
`DEPLOY.md` (deploy + env), `DOCTRINE.md` (monetization doctrine)._
