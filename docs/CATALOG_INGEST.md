# Krey — Catalogue Ingestion & Product Crawler (plan)

_Captured 2026-10-05. How real product inventory (clothes) gets from seller websites into Krey —
images, metadata, textures — parsed into structured, renderable, shoppable garments. Two phases:
(1) scripted acquisition to build a parseable dataset now (Soham); (2) a real-time crawler that
curates a seller's live inventory once they have a seller account. Feeds `WARDROBE.md` (shoppable
fits), `ATTRIBUTION.md` (purchase attribution), and the render engine (textures → fidelity)._

---

## Why this exists

The render + fits engine is only as good as the catalogue behind it. To make fits **shoppable**
(the `create → broadcast → earn` thesis in `WARDROBE.md`), Krey needs real products with: a clean
image, structured attributes, **fabric/texture**, a price, and a **buy link** — kept in sync with
the seller's live inventory. That's a catalogue-ingestion pipeline, ending in a crawler.

## Phase 1 — Scripted acquisition (now · Soham)

**Goal:** find reliable ways to pull available clothes from websites — product images + their
information + textures — into a parseable dataset.

Per product, capture:
- **Images** — all angles; pick/make a clean front shot (cut-out on white for try-on).
- **Metadata** — title, brand, price, currency, category, size/colour options, description, URL.
- **Texture / fabric** — close-up swatch or fabric field from the product photos (critical: it's
  what makes a rendered garment look *real*, and it's the hard part of fidelity).
- **Buy link + SKU/ID** — the shoppable handle (ties to creator-commerce payouts later).

**Acquisition routes, cleanest → grayest (prefer the top):**
1. **Structured product feeds** — Shopify `/products.json`, Google Merchant / product XML feeds,
   sitemaps with schema.org `Product` / Open Graph tags. Clean, legal, parseable. Start here.
2. **Official APIs / affiliate catalogues** — brand or affiliate-network product APIs (also give
   buy links + commission, which the commerce loop needs anyway).
3. **HTML scraping of product pages** — parse `<meta>`/JSON-LD/`Product` schema + images. Works
   broadly but fragile and ToS-sensitive.

**Output of Phase 1:** a structured dataset (image set + attributes + texture + buy link per
item) that parses straight into the `garments` schema → immediately usable for try-on/fits.

## Phase 2 — Real-time inventory crawler ("Google for product inventory")

Once a **seller account** is set up (= consent + authenticated access), a crawler indexes that
seller's inventory off their website and **curates it onto Krey in real time**, keeping it synced.

Components:
- **Fetcher** — polls feed/API/sitemap; respects robots.txt + rate limits; seller-authorized.
- **Parser** — extracts the Phase-1 fields; normalises to Krey's taxonomy (cloth_type / segment).
- **Image pipeline** — cut-out on white (Nano), texture capture, store to Supabase Storage.
- **Attribute tagging** — Gemini vision fills gaps (type/colour/pattern/fabric/formality/season).
- **Dedupe + sync** — product IDs as keys; detect new/changed/removed; update **stock status** so
  sold-out items don't get styled into fits.
- **Store** — `garments` rows tagged with `seller_id` + buy link; seller dashboard to manage.

**Seller-account model is the unlock:** it turns gray-area scraping into *authorized, incentivised*
ingestion — the seller *wants* their inventory on Krey (it drives sales), so they grant access,
and Krey curates + keeps it live. That's the clean, scalable version.

## Legal / ops guardrails

- Prefer **authorized** sources (feeds, APIs, seller accounts) over unsanctioned scraping; respect
  robots.txt and each site's ToS. The seller-account path sidesteps the gray area entirely.
- Don't republish full product descriptions/branding beyond fair catalogue use; store buy links
  so the sale (and attribution) returns to the seller.
- Rate-limit + identify the crawler; cache; never hammer a site.

## How it connects

- **Render fidelity** — textures/fabric from ingestion are exactly what make multi-garment
  renders look real (see test result below).
- **`WARDROBE.md`** — ingested products are the shoppable SKUs that make a broadcast fit earn.
- **`ATTRIBUTION.md`** — buy links + SKUs are what a purchase attributes back through.

---

## De-risk result: multi-garment render works (2026-10-05)

Tested whether Nano can composite a **full outfit** (not just one garment) on a person in one
call — the riskiest piece of the fits engine. Generated a person + a navy blazer + beige chinos,
then composited: **both garments applied faithfully, identity preserved, and it sensibly added a
shirt + shoes to complete the look.** → Full-outfit compositing is viable.

**Next fidelity test (with Soham's ingested data):** repeat with **real product shots that have
patterns / logos / distinct textures** (a plain blazer is the easy case). Pattern/texture
faithfulness on real SKUs is the true bar — and it's exactly why Phase-1 texture capture matters.

---

_See also: `WARDROBE.md`, `ATTRIBUTION.md`, `UNIT_ECONOMICS.md`, `STACK.md`._
