# The feedback loop — live → sandbox → production

How a bug found on the live app becomes a reviewed, tested fix in production, with a
sandbox doing the debugging and **a human expert approving every deploy**. This is the
"full cycle" backbone: a broken feature or a button that's misplaced on one phone gets
reported (by a user or by the app itself), a sandbox works the fix, and it ships — but
only through a human gate.

```
                 ┌─────────────────────── LIVE (production app) ───────────────────────┐
                 │  user taps "report"  ·  a crash is caught  ·  an auto-check fails     │
                 └───────────────────────────────┬─────────────────────────────────────┘
                                                 │  POST /feedback   (this repo, ungated)
                                                 ▼
                                   normalize → dedup → severity → route
                                                 │
                        ┌────────────────────────┴───────────────────────┐
                        ▼                                                 ▼
                 GitHub Issue (labels)                          (device-specific visual bug)
                 from-live · sandbox-debug · sev-*              + device-farm label
                        │
                        │  `sandbox-debug` label fires a trigger
                        ▼
             Claude Code Remote — SANDBOX session
             reproduce · root-cause · fix · add a regression test
                        │  opens a PR
                        ▼
             ┌───────── CI (this repo, .github/workflows/ci.yml) ─────────┐
             │  full pytest suite  ·  (device-farm repro for visual bugs) │
             └───────────────────────────┬───────────────────────────────┘
                                         ▼
                        ★ HUMAN EXPERT REVIEW & APPROVE ★   ← never bypassed
                                         │
                                         ▼
                                 merge → auto-deploy
```

## The stages

### 1. Capture on live — `POST /feedback`
Two sources feed the same door:
- **User-reported.** A "something's wrong" button in the app posts a structured report:
  `screen`, `note`, `device`, `os`, `os_version`, `app_version`, `severity`,
  `screenshot_ref`, and `recent_event_ids`.
- **Auto-assessed.** Sentry (crashes) and the analytics spine (a funnel step that
  suddenly drops, a render failure spike) post the same shape with
  `reported_by: "auto"`.

`app/feedback.py` normalizes the report into a **ticket** (pure, deterministic, tested in
`tests/test_feedback.py`):
- **severity** — `blocker | high | normal | low`; a crash is auto-escalated to at least
  `high`.
- **kind** — `crash | visual | functional`, classified from the text.
- **route** — `standard` or `device_farm` (below).
- **dedup_key** — a stable hash of the *stable* surface (screen + app_version + os + kind,
  plus device only for device-specific bugs). 500 users reporting the same off-screen
  button collapse to **one** ticket, not 500.
- **issue_labels** — `from-live`, `sev-*`, the kind, always `sandbox-debug`, plus
  `device-farm` / `priority` when they apply.

The endpoint is **ungated on purpose**: a feedback report is not biometric (no photo, no
measurement — just device/screen/note + event IDs), so reporting a broken button must
never require an account or a verified DOB. This is the one ingestion path that skips the
`canRender` chokepoint, and `tests/test_feedback.py` pins that.

### 2. Ticket → GitHub Issue
A thin off-repo webhook (a Supabase Edge Function or a small worker — see "Wiring" below)
takes the ticket and creates a GitHub issue with the ticket's `issue_labels`, deduping on
`dedup_key` (comment-and-bump an existing open issue instead of opening a new one). Users
filing by hand use `.github/ISSUE_TEMPLATE/bug_report.yml`, which produces the same labels.

### 3. Issue → sandbox debug session
The `sandbox-debug` label fires a **Claude Code Remote** trigger that opens a fresh
sandbox session on this repo (see "Wiring"). The session:
1. reads the issue (screen, device, note, `recent_event_ids`, screenshot),
2. reproduces the bug — a unit/integration test for logic bugs; a **device-farm run** for
   device-specific visual bugs (stage 5),
3. writes the smallest fix + a regression test that fails before and passes after,
4. opens a PR that references the issue.

The sandbox is isolated: it has the repo and CI, **not** production, secrets, or user
data. It proposes; it never ships.

### 4. CI — the automated gate
`.github/workflows/ci.yml` runs the full `pytest` suite on the PR. Red CI never reaches a
human's approve button. For device-tagged bugs, the device-farm reproduction (stage 5)
runs here too and attaches a visual diff.

### 5. Device farm — the hard edge for device-specific visual bugs
Some bugs don't exist in code you can unit-test — they only appear when a real screen is
rendered on a real device: a CTA pushed off-screen by a tall notch, text clipped at a font
scale, a layout that only breaks at one aspect ratio. A sandbox can't "see" these. So:

- **Routing.** `app/feedback.py` marks a report `route: device_farm` when it's a *visual*
  bug **and** names a device. `is_device_specific()` is the gate — no device named, no farm
  run (you can't book a device you can't name); a crash or a logic bug never routes here.
- **Reproduction.** The `device-farm` label / PR triggers a run on a device farm against
  the reported device (or the closest match in the matrix):
  - **Firebase Test Lab** — real + virtual Android/iOS, best price/coverage for an
    India-first Android-heavy matrix; **recommended start.**
  - **BrowserStack App Live / App Automate** — widest real-device catalogue, good for
    "reproduce on exactly this Redmi model".
  - **AWS Device Farm** — if the rest of the stack lands on AWS Mumbai.
- **Visual regression.** The run screenshots the reported screen across a **device matrix**
  (a pinned set: a couple of iPhones, a Pixel, a low-end Redmi/Samsung, a tablet) and diffs
  each against a stored baseline. Tooling: Playwright's `toHaveScreenshot` for web/PWA
  screens; a native snapshot harness (e.g. Maestro flows + screenshot compare, or
  Detox/iOSSnapshotTestCase) for native screens. A pixel-diff over threshold **fails the
  check** and attaches the before/after images to the PR — that's the reproduction the
  human reviews, and the baseline the fix has to restore.
- **Matrix in CI.** The same visual-regression job runs on a small matrix for **every** PR
  touching UI, so device-specific regressions are caught before they ship, not only after a
  user reports one. The device matrix is pinned in the frontend repo's CI config (the
  frontend is a separate repo — see the stack recommendation); this backend repo's CI runs
  the API suite.

> **Accounts to provision (founder):** the device farm (Firebase Test Lab / BrowserStack /
> AWS Device Farm), Sentry (crash + auto-assessment source), and the Claude Code Remote
> trigger all need accounts/keys. None exist yet — flagged here, not silently assumed. Each
> costs money; set them up when the app and CI are live.

### 6. ★ The human-expert gate — never bypassed
**Every fix is reviewed and approved by a human expert before it merges and deploys.** The
sandbox and CI make the fix *ready*; they never make it *live*. Branch protection on the
default branch enforces this: required review + required green CI, no direct pushes, no
auto-merge on labels. The loop is "propose automatically, ship deliberately."

### 7. Merge → deploy
On approval + green CI, merge triggers the deploy (Railway/Render auto-deploys the branch;
see `docs/DEPLOY.md`). The originating issue is closed by the PR. The `feedback` analytics
event emitted at stage 1 lets you measure the loop itself: report → fix → deploy time,
dedup rate, device-farm hit rate.

## The guardrail rule — extra scrutiny for sensitive fixes
A fix that touches any of these gets **extra human scrutiny** and may **never** be
auto-approved, however green CI is:
- the eligibility / `canRender` chokepoint (`app/eligibility.py`, `_biometric_gate`),
- consent, account, or verified-DOB checks (minors must stay blocked),
- derive-and-discard (raw photos deleted after processing; `_save_uploads`/`_discard`,
  `store.py` `_SLOTS` whitelist),
- owner-only retention (only the dominant identity is profiled).

These are the promises the product is built on. A PR whose diff touches these paths must
be labelled `guardrail` (a CODEOWNERS rule on those files can force it) and reviewed by
someone who owns that invariant — not merged because the tests are green. The sandbox is
instructed to flag such a diff in the PR body rather than present it as routine.

## Wiring (the off-repo glue — build when accounts exist)
Three small integrations turn this from a diagram into a running loop:
1. **`/feedback` → issue.** A webhook/worker that calls the GitHub API to create/dedupe the
   issue from the ticket. (Kept off-repo so no GitHub token lives in the API service.)
2. **`sandbox-debug` label → Claude Code Remote trigger.** A trigger firing a sandbox
   session on the labelled issue. Configure it to read the issue and open a PR; scope its
   token to this repo, not production.
3. **Sentry + analytics → `/feedback`.** Alert rules that POST the ticket shape with
   `reported_by: "auto"`, so crashes and funnel anomalies enter the same loop as user
   reports.

Until those accounts exist, the repo-side backbone is complete and tested: the endpoint,
the ticket core, the issue form, CI, and this runbook. The glue is configuration, not code
in this service.
