-- Krey garment catalog — Supabase schema (run once in Supabase → SQL Editor).
-- Storage: also create a PUBLIC bucket named `garments` (Supabase → Storage → New bucket,
-- "Public bucket" ON) so image_url is directly viewable by the /closet page.
--
-- Service A reads this table via PostgREST with KREY_SUPABASE_URL + KREY_SUPABASE_KEY
-- (the anon key is enough for read; the INGESTION script needs the SERVICE ROLE key to write).

create table if not exists garments (
    garment_id  text primary key,           -- stable id (e.g. dataset id or a uuid)
    name        text not null,              -- display name ("Blue Oxford Shirt")
    cloth_type  text not null check (cloth_type in ('upper','lower','overall')),  -- the render needs this
    segment     text,                       -- ANALYTICS bucket: intimate/wedding/ethnic/formal/party/athleisure/casual
    subsegment  text,                       -- GRANULAR drilldown under segment (e.g. lingerie, bridal-festive, kurta)
    category    text,                       -- tee / shirt / jeans / dress …  (display + filter)
    color       text,                       -- hex or name (display + filter; tile fallback)
    image_url   text,                       -- public URL of the garment image (Storage bucket)
    source      text,                       -- provenance ("fashion-product-images", …)
    fit_notes   text,                       -- "oversized" etc. — DISPLAY ONLY (2D render can't enforce fit)
    size_range  text,                       -- display only
    licence     text,                       -- provenance/licence note (research/non-commercial for the test)
    created_at  timestamptz default now()
);

create index if not exists garments_cloth_type_idx on garments (cloth_type);
create index if not exists garments_segment_idx    on garments (segment);
create index if not exists garments_subsegment_idx on garments (subsegment);

-- Read-only public access for the anon key (browse the catalog). Writes are service-role only.
alter table garments enable row level security;
create policy "public read garments" on garments for select using (true);

-- If you already created `garments` before these columns existed, add them in place:
alter table garments add column if not exists segment text;
alter table garments add column if not exists subsegment text;

-- ---------------------------------------------------------------------------
-- garment_events — the "what gets shared most" thesis. Durable so counts survive
-- Railway redeploys (in-memory would reset). Service A (anon key) INSERTS here;
-- you read/aggregate from the Supabase dashboard with the service key.
-- No PII: only an anonymous session hint the client makes up, never a name/email.
create table if not exists garment_events (
    id          bigint generated always as identity primary key,
    garment_id  text not null,
    event_type  text not null check (event_type in ('view','try','share')),
    segment     text,                       -- denormalised for fast slicing
    cloth_type  text,
    session_hint text,                      -- opaque per-browser id (analytics only, no PII)
    created_at  timestamptz default now()
);

create index if not exists garment_events_garment_idx on garment_events (garment_id);
create index if not exists garment_events_type_idx    on garment_events (event_type);
create index if not exists garment_events_segment_idx on garment_events (segment);

-- Anon may INSERT events (the app logs shares/tries) but NOT read them back —
-- keeps the funnel counts private to you (service key in the dashboard).
alter table garment_events enable row level security;
create policy "anon insert events" on garment_events for insert with check (true);

-- Handy rollups to run in the SQL Editor later:
--   what gets shared most:
--     select garment_id, count(*) shares from garment_events
--       where event_type='share' group by garment_id order by shares desc limit 25;
--   which SEGMENT gets shared most (the thesis):
--     select segment, count(*) shares from garment_events
--       where event_type='share' group by segment order by shares desc;
--   drilldown — SUBSEGMENT shares (JOIN to garments for the granular cut):
--     select g.segment, g.subsegment, count(*) shares
--       from garment_events e join garments g using (garment_id)
--       where e.event_type='share' group by g.segment, g.subsegment
--       order by shares desc;
--   share-through rate by segment (shares / views):
--     select segment,
--            count(*) filter (where event_type='share')::float
--              / nullif(count(*) filter (where event_type='view'),0) as share_rate
--       from garment_events group by segment order by share_rate desc nulls last;
