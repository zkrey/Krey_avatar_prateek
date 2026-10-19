# Social connect — importing a user's own data to strengthen their profile (planned)

> Status: **planning** (2026-10). Not built. This extends "Krey remembers you"
> (`face_profiles`: consented per-user face + Monk tone + measurements) by letting a
> user **connect their own social accounts** and import *the data they authorize* —
> more selfies, their posted outfits, their taste — to make recognition, complexion
> and styling more faithful, and to seed the wardrobe. Compliance-gated; ship only
> behind OAuth + a privacy policy + app review.

## The one rule that defines scope

We collect **only what the user explicitly authorizes through the platform's own OAuth
consent screen** — never scraped, bought, or third-party "data about the user." OAuth
gives a scoped, revocable token; that *is* the consent record. Anything outside that is
off the table (platform ToS + DPDP/GDPR + ethics).

So the honest framing is **"connect & import your own look,"** not "collect info about you."

## What's realistically gettable (2026 API reality — verify at build time)

| Platform | Via | What you get with consent | Krey use |
|---|---|---|---|
| **Google** | Sign-In (OIDC) + Photos **Picker** | name, email, avatar; user-*picked* photos (no full-library since 2025) | more selfies → stronger face/tone profile; frictionless login |
| **Instagram** | Instagram Login + Graph API (app review) | username, account type, **their own posted media** | selfies + outfits → profile + wardrobe seeding |
| **Pinterest** | OAuth | their boards / pins | **style taste** signal for the stylist |
| **Facebook** | Login | profile basics | login only; little else useful |
| **TikTok / Snapchat** | Login | profile basics, limited media | low priority |

### Two things NOT to promise
- **Friend graphs are closed.** Meta/IG return only friends who *also use our app*; you
  cannot import someone's social circle. The close-circle vision (see `SOCIAL_FLOW.md`,
  M2) is served by **in-app invites**, not social-graph import.
- **No third-party data.** No scraping, no data brokers, no inferring "info about the
  user" they didn't hand us. User-authorized data only.

## How it plugs into what exists

- **Profile (`face_profiles`)** — imported selfies fold into the running face embedding +
  good-light tone baseline, exactly like an in-app selfie (reuse `update_face_profile` /
  `update_tone_profile`). More photos → more faithful, faster.
- **Wardrobe** — their posted outfit photos → auto cut-out + auto-tag (reuse the
  `/wardrobe/add` pipeline) to seed a closet without manual snapping. (Lazy doctrine.)
- **Stylist** — Pinterest/IG taste → a "your vibe" prior for `compose_fit`.
- **Onboarding** — "Connect to import your look" is the one-tap on-ramp; pairs with the
  first-run coach.
- **Delete** — `/me/face/delete` must also **revoke the OAuth token** and drop imported
  media, so the delete-anytime promise still holds.

## Phasing

1. **Phase 1 — Google/Instagram "import a few photos"** → strengthen the profile + seed the
   wardrobe. Minimal scopes (profile + user-picked/own media). Highest value, lowest risk.
2. **Phase 2 — Pinterest/IG taste** → feed the stylist a taste prior.
3. **Friends** — in-app invites + accounts (M2), *not* social import.

## Compliance gate (the real cost — do before any build)

This handles photos (**biometric**) + personal data, so:
- **DPDP Act (India)** + GDPR/BIPA-style: explicit, **purpose-limited** consent; data
  minimization; consent + retention records; easy withdrawal/deletion; a named purpose
  (cannot silently repurpose imported photos to train a general model — that needs its
  own disclosure; see the consented-dataset path, not this doc).
- **Published privacy policy** (prerequisite for app review).
- **Platform app review** — Meta/Google reviews for sensitive scopes take **weeks** and
  require data-use justification. Budget for it.
- **Token security** — encrypted at rest, scoped, refresh handled; revoke-on-delete.
- A review by someone accountable for privacy (DPO/legal) before go-live.

## Minimum build checklist (when accounts + policy are ready)

- [ ] Privacy policy published; purposes + retention stated.
- [ ] App registrations + OAuth client secrets per platform (stored as Railway env, never in repo).
- [ ] OAuth connect + callback endpoints; encrypted token store (new `social_tokens` table, service-role only — NOT anon-readable like the current tables).
- [ ] Import flow → reuse `update_face_profile`/`update_tone_profile` + `/wardrobe/add`.
- [ ] Consent UI stating exactly what's imported and why (extends the one-tap `face_learn` banner).
- [ ] Delete/disconnect → revoke token + drop imported media + `delete_face_profile`.
- [ ] App review submitted + approved per platform.

## Note on the current test

Nothing here is needed for the alpha. The in-app selfie already builds the profile; social
connect is a growth/onboarding accelerator for a later, policy-ready stage.
