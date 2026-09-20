# Service B — the render (Modal serverless GPU)

Hosts the CatVTON try-on behind a scale-to-zero GPU endpoint, so `/render` on Service A pays
**only per render** (Modal free credits first). This is the "if it passes → the path" step from
`docs/render_benchmark_plan.md`, scaffolded ahead of time. **Not live yet** — `app/main.py` is
untouched until the benchmark's clean-input identity score clears the bar.

## Files
- `modal_app.py` — the Modal app: bakes CatVTON + weights into the image, loads the pipeline once
  per warm container, exposes an authed `POST /render` (multipart person+garment → PNG).
- `client.py` — Service A's stdlib client (`render_configured()`, `render_tryon(...)`); no new deps.

## Deploy (once the benchmark passes)
```bash
pip install modal
modal token new                                              # one-time, your Modal account
modal secret create krey-render KREY_RENDER_SECRET=$(openssl rand -hex 24)
modal deploy render/modal_app.py                             # prints the web URL
```
Then on **Service A (Railway)** set env vars:
```
KREY_MODAL_RENDER_URL = https://<your-modal-app>.modal.run
KREY_RENDER_SECRET    = <the same value you gave the modal secret>
```
Smoke-test the endpoint directly:
```bash
curl -s -X POST "$KREY_MODAL_RENDER_URL/render" \
  -H "X-Krey-Secret: $KREY_RENDER_SECRET" \
  -F person=@me.jpg -F garment=@tee.jpg -F cloth_type=upper -o out.png
```

## Wire `/render` on Service A (ready to paste into `app/main.py`)
Keep the doctrine: **eligibility (canRender) + token hold on Service A**, GPU on Modal. The
endpoint below reserves tokens, renders, commits on success / releases on failure. `token_balance`
and `used_today` come from the store/DB the same way the rest of Service A reads them.

```python
from render import client as render_client

@app.post("/render")
async def render_ep(
    person: UploadFile = File(...),
    garment: UploadFile = File(...),
    cloth_type: str = Form("upper"),
    plan: Optional[str] = Form(None),
    used_today: int = Form(0),
    token_balance: int = Form(0),
    account_present: bool = Form(False),
    dob_verified: bool = Form(False),
    birthdate: Optional[str] = Form(None),
    jurisdiction: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    user_id: Optional[str] = Form(None),
    guest_id: Optional[str] = Form(None),
    surface: Optional[str] = Form(None),
    region: Optional[str] = Form(None),
    app_version: Optional[str] = Form(None),
    device_os: Optional[str] = Form(None),
):
    if not render_client.render_configured():
        raise HTTPException(503, "render backend not configured")

    spine = _spine(session_id, user_id, guest_id, surface, region, app_version, device_os, None)

    # 1) daily quota + lane (pure policy) — same call /render/authorize already uses.
    authz = entitlements.authorize(plan, used_today)
    if not authz["allowed"]:
        analytics.render(spine, phase="requested", entry_point="render",
                         fail_reason="daily_quota_reached", source=authz.get("lane"))
        raise HTTPException(429, {"reason": "daily_quota_reached", "upsell": authz.get("upsell")})

    # 2) the single canRender wall (account + DOB + jurisdiction + funds).
    bd = date.fromisoformat(birthdate) if birthdate else None
    cost = entitlements.token_map()["OWNCOST"]   # barrier-1 cost; token_map() is env-overridable
    verdict = eligibility.can_render(
        account_present=account_present, dob_verified=dob_verified, birthdate=bd,
        today=date.today(), token_balance=token_balance, render_cost=cost,
        jurisdiction=jurisdiction or eligibility.M1_JURISDICTION,
        input_eligibility_passed=True,
    )
    if not verdict.allowed:
        analytics.render(spine, phase="requested", entry_point="render", fail_reason=verdict.reason)
        raise HTTPException(403, {"reason": verdict.reason, "is_minor": verdict.is_minor})

    # 3) reserve tokens, render on Modal, commit/release. (Persist the balance via the store.)
    remaining, hold = eligibility.place_hold(token_balance, cost)
    try:
        png = render_client.render_tryon(await person.read(), await garment.read(), cloth_type)
        eligibility.commit_hold(hold)
    except Exception as e:
        eligibility.release_hold(remaining, hold)
        analytics.render(spine, phase="failed", entry_point="render", fail_reason="render_error")
        raise HTTPException(502, f"render failed: {e}")

    analytics.render(spine, phase="produced", entry_point="render", source=authz.get("lane"))
    return Response(content=png, media_type="image/png")   # derive-and-discard: nothing stored
```
Notes:
- Token costs come from `entitlements.token_map()` (a dict; `"OWNCOST"` etc.), env-overridable so
  ops retune the economy without a code change. Pick the key matching the barrier the render is on.
- Persisting the debited balance is the store's job (same pattern as `twin_store.save`); the hold
  helpers are pure — wire them to however Service A reads/writes the wallet.
- Raw images in, PNG out, nothing persisted — same derive-and-discard rule as capture.

## Cost / latency
The benchmark's **seconds/render** picks the GPU: T4 (cheapest) vs L4/A10G (~2–3x faster, better
UX). Feed measured per-render seconds × Modal's per-second GPU price into the unit-econ model
before any always-on GPU. Set `KREY_RENDER_GPU` on the Modal deploy to switch.
