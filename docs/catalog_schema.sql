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
drop policy if exists "public read garments" on garments;
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
drop policy if exists "anon insert events" on garment_events;
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
drop policy if exists "public read looks"     on looks;
drop policy if exists "public read rank_sets" on rank_sets;
drop policy if exists "anon insert looks"     on looks;
drop policy if exists "anon insert rank_sets" on rank_sets;
drop policy if exists "anon insert votes"     on rank_votes;
drop policy if exists "anon insert referrals" on referrals;
drop policy if exists "public read votes"     on rank_votes;
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
drop policy if exists "anon upload looks" on storage.objects;
drop policy if exists "public read looks bucket" on storage.objects;
create policy "anon upload looks" on storage.objects
    for insert to anon with check (bucket_id = 'looks');
create policy "public read looks bucket" on storage.objects
    for select to anon using (bucket_id = 'looks');

-- ---------------------------------------------------------------------------
-- confidence_marks — the fit-confidence signal. phase 'pre' = before sharing (also mirrored on
-- looks.confidence_self), 'post' = after seeing the ranking. Δ(post-pre) is the dose-response.
create table if not exists confidence_marks (
    id          bigint generated always as identity primary key,
    set_id      text,
    look_id     text,
    owner_hint  text,
    phase       text check (phase in ('pre','post')),
    value       smallint,                    -- 0..10
    created_at  timestamptz default now()
);
create index if not exists confidence_marks_set_idx on confidence_marks (set_id);
alter table confidence_marks enable row level security;
drop policy if exists "anon insert confidence" on confidence_marks;
drop policy if exists "public read confidence" on confidence_marks;
create policy "anon insert confidence" on confidence_marks for insert with check (true);
create policy "public read confidence" on confidence_marks for select using (true);

-- ---------------------------------------------------------------------------
-- wardrobe — a user's OWN garments (digital closet). Uploaded via /wardrobe → cut out on white
-- (Nano) + auto-tagged (Gemini vision) → the base for custom fits. Keyed by owner_hint; reuses
-- the public `looks` Storage bucket for images. Anon insert + read (own items filtered app-side).
create table if not exists wardrobe (
    item_id    text primary key,                -- short slug
    owner_hint text,                            -- whose wardrobe (opaque per-browser id)
    name       text,                            -- auto label, e.g. "Navy blazer"
    image_url  text,                            -- clean cut-out (Storage)
    cloth_type text,                            -- upper | lower | overall
    color      text,
    pattern    text,
    formality  text,                            -- casual | smart | formal
    season     text,                            -- summer | winter | all-season
    created_at timestamptz default now()
);
create index if not exists wardrobe_owner_idx on wardrobe (owner_hint);
alter table wardrobe enable row level security;
drop policy if exists "anon insert wardrobe" on wardrobe;
drop policy if exists "public read wardrobe" on wardrobe;
create policy "anon insert wardrobe" on wardrobe for insert with check (true);
create policy "public read wardrobe" on wardrobe for select using (true);

-- ---------------------------------------------------------------------------
-- /admin analytics reads these with the anon key. Funnel counts are anonymous hints; fine for the
-- closed test. Tighten (service-role only, or drop these) before any public launch.
drop policy if exists "public read events"    on garment_events;
drop policy if exists "public read referrals" on referrals;
create policy "public read events"    on garment_events for select using (true);
create policy "public read referrals" on referrals      for select using (true);

-- ---------------------------------------------------------------------------
-- render_feedback — the "does this render look like you?" judgement. Pairs the human YES/NO with
-- the ArcFace identity_score the render scored (bench/render_eval metric), so /admin can map the
-- cosine at which testers stop recognising themselves and recalibrate KREY_ID_MIN_COSINE (the
-- render floor; doctrine: docs/render_benchmark_plan.md + recognition_thresholds.md). Anonymous.
create table if not exists render_feedback (
    id             bigint generated always as identity primary key,
    look_id        text,
    owner_hint     text,
    looks_like     boolean,                    -- true = "that's me", false = "doesn't look like me"
    identity_score numeric,                     -- ArcFace cosine (input face vs render face), 0..1
    route          text,                        -- closet-tryon | trend | wardrobe-tryon | wardrobe-fit
    created_at     timestamptz default now()
);
create index if not exists render_feedback_look_idx on render_feedback (look_id);
alter table render_feedback enable row level security;
drop policy if exists "anon insert render_feedback" on render_feedback;
drop policy if exists "public read render_feedback" on render_feedback;
create policy "anon insert render_feedback" on render_feedback for insert with check (true);
create policy "public read render_feedback" on render_feedback for select using (true);
--   recognition mapping (where testers reject their render):
--     select looks_like, count(*), round(avg(identity_score),3) avg_score,
--            min(identity_score) lo, max(identity_score) hi
--       from render_feedback group by looks_like;

-- ---------------------------------------------------------------------------
-- render_scores — PASSIVE per-render identity log: EVERY render's ArcFace score (input face vs
-- render face), not just the ones a tester taps on. Gives the full face-distortion distribution
-- and per-route quality on volume, so the render floor can be judged without waiting for taps.
-- `retried` = the identity gate fired its one auto-retry on this render. Anonymous.
create table if not exists render_scores (
    id             bigint generated always as identity primary key,
    look_id        text,
    owner_hint     text,
    identity_score numeric,                     -- ArcFace cosine, 0..1 (higher = more faithful)
    route          text,                        -- banana | banana80s | trend | wardrobe
    retried        boolean default false,
    created_at     timestamptz default now()
);
create index if not exists render_scores_route_idx on render_scores (route);
alter table render_scores enable row level security;
drop policy if exists "anon insert render_scores" on render_scores;
drop policy if exists "public read render_scores" on render_scores;
create policy "anon insert render_scores" on render_scores for insert with check (true);
create policy "public read render_scores" on render_scores for select using (true);
--   distortion distribution by route:
--     select route, count(*), round(avg(identity_score),3) avg,
--            round(avg((identity_score < 0.65)::int),3) frac_below_065
--       from render_scores group by route order by avg;

-- ---------------------------------------------------------------------------
-- face_profiles — a per-user face reference that improves recognition the more selfies they add
-- (running-mean ArcFace embedding = the doctrine's "5-photo aggregation 65% -> 84%"). BIOMETRIC-
-- DERIVED: written ONLY with the user's explicit consent (face_learn), keyed by the opaque
-- owner_hint, and deletable on request (/me/face/delete). Stores the embedding vector, not photos.
-- Access is server-mediated (Service A's key only; the browser never queries Supabase directly).
create table if not exists face_profiles (
    owner_hint   text primary key,              -- opaque per-user id (no name/email)
    embedding    jsonb,                         -- L2-normalised mean ArcFace embedding (512 floats)
    samples      int default 0,                 -- how many selfies folded into the face embedding
    monk         numeric,                       -- trusted Monk skin-tone value from good earlier selfies
    rgb          jsonb,                          -- trusted average skin RGB [r,g,b]
    tone_samples int default 0,                 -- how many good-light selfies set the tone
    measurements jsonb,                          -- body measurements when available (from the capture flow)
    updated_at   timestamptz default now()
);
alter table face_profiles enable row level security;
drop policy if exists "anon rw face_profiles" on face_profiles;
drop policy if exists "anon read face_profiles" on face_profiles;
drop policy if exists "anon del face_profiles" on face_profiles;
create policy "anon rw face_profiles"   on face_profiles for insert with check (true);
create policy "anon read face_profiles" on face_profiles for select using (true);
create policy "anon upd face_profiles"  on face_profiles for update using (true) with check (true);
create policy "anon del face_profiles"  on face_profiles for delete using (true);

-- Loop rollups:
--   fit-confidence lift by segment (needs rendered looks + baselines):
--     -- (computed app-side from rank_votes -> Glicko-2; see docs measurement plan)
--   K-factor (activations per inviter):
--     select count(*) filter (where activated)::float
--            / nullif(count(distinct referrer_hint),0) as k_factor from referrals;
--   which channel drives shares:
--     select channel, count(*) from garment_events where event_type='share'
--       group by channel order by 2 desc;
