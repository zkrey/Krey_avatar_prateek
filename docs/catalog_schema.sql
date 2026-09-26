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

-- Read-only public access for the anon key (browse the catalog). Writes are service-role only.
alter table garments enable row level security;
create policy "public read garments" on garments for select using (true);
