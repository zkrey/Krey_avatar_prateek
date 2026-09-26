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
    channel     text,                       -- share channel: whatsapp/native/copy/... (share events)
    referrer_hint text,                     -- who sent the link that led here (network-effect attribution)
    created_at  timestamptz default now()
);

create index if not exists garment_events_garment_idx on garment_events (garment_id);
create index if not exists garment_events_type_idx    on garment_events (event_type);
create index if not exists garment_events_segment_idx on garment_events (segment);
-- backfill if the table predates these columns:
alter table garment_events add column if not exists channel text;
alter table garment_events add column if not exists referrer_hint text;

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

-- ===========================================================================
-- The share -> rank -> confidence -> referral loop (the social-testing experiment).
-- All ids are opaque per-browser "hints", never a name/email. Populated once the render
-- (Service B) is live; the landing pages read these via the anon key.
-- ===========================================================================

-- looks — a rendered "you in the garment" (the shareable unit). is_baseline = the plain/original
-- photo used as the lift reference. confidence_self = the wearer's pre-share confidence tap.
create table if not exists looks (
    look_id       text primary key,          -- short slug used in /look/<id>
    owner_hint    text,                       -- who created it (opaque)
    garment_id    text,
    name          text,
    segment       text,
    subsegment    text,
    image_url     text,                       -- public URL of the rendered look (Storage)
    is_baseline   boolean default false,
    confidence_self smallint,                 -- 0..10 pre-share self-rating (fit-confidence)
    created_at    timestamptz default now()
);
create index if not exists looks_owner_idx on looks (owner_hint);

-- rank_sets — a ballot: 2-3 of my looks bundled to be ranked. `ref` = the owner (so a vote
-- and the "try your own fit" CTA both attribute back to them for K-factor).
create table if not exists rank_sets (
    set_id     text primary key,              -- short slug used in /rank/<id>
    owner_hint text,
    look_ids   jsonb not null,                -- ["look_a","look_b",...]
    ref        text,                          -- referrer hint (usually = owner_hint)
    created_at timestamptz default now()
);

-- rank_votes — one pairwise vote (2-alternative forced choice). Feeds Glicko-2 later.
create table if not exists rank_votes (
    id            bigint generated always as identity primary key,
    set_id        text,
    winner_look_id text not null,
    loser_look_id  text,
    voter_hint    text,                       -- opaque; anonymous voting (no signup)
    referrer_hint text,                       -- who invited the voter
    created_at    timestamptz default now()
);
create index if not exists rank_votes_set_idx on rank_votes (set_id);

-- referrals — the network-effect edge: a visitor who landed via someone's share link, and
-- whether they activated (made their own fit). K-factor = activations / inviters.
create table if not exists referrals (
    id            bigint generated always as identity primary key,
    referrer_hint text,                       -- who sent the link
    visitor_hint  text,                       -- who arrived (opaque)
    source        text,                       -- 'look' | 'rank' | 'closet'
    activated     boolean default false,      -- flipped true when they build their own fit
    created_at    timestamptz default now()
);
create index if not exists referrals_referrer_idx on referrals (referrer_hint);

-- Landing pages need to READ looks + rank_sets with the anon key; votes/referrals are insert-only.
alter table looks      enable row level security;
alter table rank_sets  enable row level security;
alter table rank_votes enable row level security;
alter table referrals  enable row level security;
create policy "public read looks"     on looks     for select using (true);
create policy "public read rank_sets" on rank_sets for select using (true);
create policy "anon insert looks"     on looks     for insert with check (true);
create policy "anon insert rank_sets" on rank_sets for insert with check (true);
create policy "anon insert votes"     on rank_votes for insert with check (true);
create policy "anon insert referrals" on referrals for insert with check (true);
-- the ballot owner reads their own results (win tallies). Votes are anonymous hints, so this is
-- fine for the closed friends-test; tighten before any public launch.
create policy "public read votes"     on rank_votes for select using (true);

-- ---------------------------------------------------------------------------
-- STORAGE for self-serve uploads (/studio): a PUBLIC bucket named `looks` that anon may write to.
-- Create the bucket first (Supabase → Storage → New bucket → name `looks`, Public ON), then:
create policy "anon upload looks" on storage.objects
    for insert to anon with check (bucket_id = 'looks');
create policy "public read looks bucket" on storage.objects
    for select to anon using (bucket_id = 'looks');

-- Loop rollups:
--   fit-confidence lift by segment (needs rendered looks + baselines):
--     -- (computed app-side from rank_votes -> Glicko-2; see docs measurement plan)
--   K-factor (activations per inviter):
--     select count(*) filter (where activated)::float
--            / nullif(count(distinct referrer_hint),0) as k_factor from referrals;
--   which channel drives shares:
--     select channel, count(*) from garment_events where event_type='share'
--       group by channel order by 2 desc;
