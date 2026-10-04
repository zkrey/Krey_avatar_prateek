# Krey — Social Flow & the Trust On-Ramp (design note, for launch)

_Captured 2026-10-04. Why ranking lags in the tester, the psychology behind it, and the
launch flow that fixes it. The friend layer below is **launch scope, not the tester** — the
tester only approximates it with warm "close circle" copy._

---

## The core insight: asymmetry of vulnerability

Two social actions feel completely different, even though both involve another person:

| Action | How it feels | Vulnerability |
|---|---|---|
| **Add / invite a friend** | agentive, generous, status-safe — "I want you in my circle" | ~zero — flattering to both sides (why Facebook invites feel *joyful*) |
| **Ask to be validated** | exposing, submissive — inviting a verdict on yourself | high — fear of judgment |

Softening the validation ask alone is a band-aid. The real fix is to **sequence the safe
action first**: adding/accepting into a circle is the low-vulnerability on-ramp. Once that
trust container exists and is mutual, asking for a take *inside it* feels like asking a
friend — not broadcasting to a crowd. **The circle converts a vulnerable act into a safe one.**

This is why the tester's ranking lags: there's no circle yet, so every "which looks best on
me?" is a **cold broadcast to a loose network** → embarrassment → people render but don't ask.

---

## Two graphs: follow (inspiration) vs friend (validation)

There are **two different relationship edges**, with different jobs and different vulnerability
levels. Keeping them separate is the architecture:

| Edge | Why you form it | Direction | Intimacy | What it powers |
|---|---|---|---|---|
| **Follow** | inspiration — "their taste inspires me" | one-way | low / none | discovery & inspiration feed; viral reach |
| **Friend** | closeness — "I trust them with the real me" | mutual (consented) | high | the validation / OOTD circle |

**The rule that falls out: validation is friends-only; inspiration is follow-based — never
cross them.** A follower voting on your OOTD re-introduces the "judged by distant people"
embarrassment we're solving. You can follow someone with great taste with zero vulnerability;
you only hand the vulnerable ask to friends who opted into closeness.

**Two loops, by design:**
- **Follow loop** → reach & inspiration (aspirational, public-ish, low-stakes). Discovery, the
  trend gallery, "looks worth stealing." Grows the top of funnel.
- **Friend loop** → validation & confidence (intimate, private, high-trust). The OOTD vote,
  the confidence lift, retention. This is the moat.

Design implication: the **add-friend** action (mutual, deliberate) is the gate for validation;
**follow** (one-tap, one-way) is the gate for the inspiration feed. Don't let follow stand in
for friend when deciding who may validate.

---

## Target flow (launch)

```
upload photo → fit check (render) → SELF-validation (your own gut)
  → [circle exists?] → ask your circle → they rate/rank → find your OOTD → repeat
        ↑ if no circle yet: ADD FRIENDS first (the safe, joyful on-ramp)
```

- **Self-validation before any social step.** You commit to your own read first; the crowd
  either confirms or gently challenges it. (This is also the pre half of the confidence-lift
  metric.)
- **Add-friends is the gate, and it's a feature, not a chore.** Frame it as building your
  style circle — joyful, like growing a network — *before* any validation is asked. By the
  time someone rates your fit, they're already a consented member of your circle.
- **Validation happens inside the circle**, in-app, via a warm notification — never a public
  post. The validator sees "a friend trusts your eye," not "stranger wants to be judged."

## What makes it feel safe (comms principles)

- **Warm, 1:1, close-circle voice.** "Ask your people", "send to 2–3 you trust, not the whole
  feed, it stays between you." Never "share"/"broadcast"/"rate me."
- **Frame the validator as a caring friend giving an honest take** — "X trusts your eye, which
  is more them?" — not a judge scoring a stranger.
- **Payoff, not verdict.** The result is "Your OOTD, picked by your people 👑" — a gift from
  the circle, not a grade.
- **Reciprocity.** After you validate someone, you're nudged to try your own + ask your circle
  — the loop is mutual, which keeps it safe (everyone is both validatee and validator).

---

## Tester vs. launch (scope line)

| | Tester (now) | Launch |
|---|---|---|
| Circle / friend graph | ❌ none — approximated by warm "close circle" copy + external send (user picks who) | ✅ add-friends is the on-ramp; accounts + a real graph |
| Notification | external share (WhatsApp etc.) | in-app warm notify to circle members |
| Validation ask | framed intimate, but still a cold-ish broadcast | happens inside an established, consented circle |

**What the tester can tell us anyway:** even without the friend layer, does the *warm,
close-circle framing* lift ranking vs. the old broadcast framing? If yes, it confirms the
vulnerability thesis and justifies building add-friends-first at launch. If ranking still
lags, the friend graph is likely the hard dependency — i.e., ranking simply won't work until
the circle exists, which is itself a decisive finding.

---

_See also: `ATTRIBUTION.md` (crediting creators once accounts exist),
`UNIT_ECONOMICS.md` (what the loop costs to run)._
