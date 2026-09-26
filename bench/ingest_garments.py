# Krey garment-catalog ingestion — build the try-on "supply" from a fashion dataset.
# ---------------------------------------------------------------------------
# Populates the Supabase `garments` table + Storage bucket (docs/catalog_schema.sql) from the
# public "Fashion Product Images (Small)" dataset — clean product shots with rich metadata
# (articleType, baseColour), directly usable as CatVTON condition images. Research/non-commercial
# use for the validation test; swap for licensed/own-shot garments before commercial launch.
#
# EASIEST: run in a KAGGLE notebook (dataset mounts with no auth).
#   1. New Kaggle notebook → Add Input → search "Fashion Product Images (Small)"
#      (paramaggarwal/fashion-product-images-small) → Add. It mounts at
#      /kaggle/input/fashion-product-images-small/
#   2. Paste these cells, set the CONFIG, Run all.
# (Colab alternative: `pip install kagglehub` + Kaggle token, then
#  kagglehub.dataset_download("paramaggarwal/fashion-product-images-small"); adjust ROOT.)
# ===========================================================================

# %% [markdown]
# ## 1. Config — your Supabase project (needs the SERVICE ROLE key to write)

# %%
SUPABASE_URL = "https://YOURPROJECT.supabase.co"          # Supabase → Project Settings → API
SUPABASE_SERVICE_KEY = "eyJ...SERVICE_ROLE..."            # the service_role key (NOT the anon key)
BUCKET = "garments"                                        # create as a PUBLIC bucket first
N_PER_TYPE = 60                                            # ~60 each of upper/lower/overall → ~180
ROOT = "/kaggle/input/fashion-product-images-small/myntradataset"   # dataset root (has styles.csv + images/)

# %% [markdown]
# ## 2. Load the dataset metadata + map articleType → cloth_type + segment
#
# TWO dimensions come out of this:
#  - cloth_type (upper/lower/overall) — the RENDER needs it (CatVTON).
#  - segment (intimate/wedding/ethnic/formal/party/athleisure/casual) — the ANALYTICS bucket
#    for the "what gets shared most?" thesis. Derived from subCategory + usage + articleType.

# %%
import os, io, json, time, urllib.request, urllib.error
import pandas as pd

styles = pd.read_csv(os.path.join(ROOT, "styles.csv"), on_bad_lines="skip")

# --- cloth_type (render dimension) — broadened to cover intimate + ethnic types too ---
UPPER = {"Tshirts","Shirts","Tops","Kurtas","Kurtis","Sweatshirts","Sweaters","Jackets","Blazers",
         "Tunics","Waistcoat","Blouse","Nehru Jackets","Bra","Camisoles","Innerwear Vests"}
LOWER = {"Jeans","Trousers","Track Pants","Shorts","Skirts","Leggings","Capris","Churidar",
         "Salwar","Briefs","Boxers","Trunk","Shapewear","Petticoat"}
OVERALL = {"Dresses","Jumpsuit","Sarees","Lehenga Choli","Clothing Set","Nightdress","Sherwani",
           "Salwar and Dupatta","Kurta Sets"}
def cloth_type(a):
    return "upper" if a in UPPER else "lower" if a in LOWER else "overall" if a in OVERALL else None

# --- segment (analytics dimension) — priority order matters ---
INTIMATE_TYPES = {"Bra","Briefs","Boxers","Trunk","Camisoles","Innerwear Vests","Shapewear",
                  "Nightdress","Baby Dolls","Robe","Lounge Pants","Lounge Shorts"}
WEDDING_TYPES  = {"Sarees","Lehenga Choli","Sherwani","Salwar and Dupatta","Kurta Sets"}   # bridal/heavy
ETHNIC_TYPES   = {"Kurtas","Kurtis","Churidar","Salwar","Dupatta","Nehru Jackets","Tunics"}  # daily ethnic
def segment(row):
    a = row["articleType"]; sub = str(row.get("subCategory","")); use = str(row.get("usage",""))
    if sub == "Innerwear" or a in INTIMATE_TYPES:      return "intimate"
    if a in WEDDING_TYPES:                             return "wedding"
    if use == "Ethnic" or a in ETHNIC_TYPES:           return "ethnic"
    if use == "Formal":                                return "formal"
    if use == "Party":                                 return "party"
    if use == "Sports":                                return "athleisure"
    return "casual"

styles["cloth_type"] = styles["articleType"].map(cloth_type)
styles["segment"]    = styles.apply(segment, axis=1)
g = styles.dropna(subset=["cloth_type"])

# balance the pull across SEGMENTS (the thesis buckets), not just cloth_type — so intimate /
# wedding / ethnic aren't drowned out by the huge casual pile. N per segment, in-stock only.
SEGMENTS = ("intimate","wedding","ethnic","formal","party","athleisure","casual")
picks = pd.concat([g[g.segment==s].head(N_PER_TYPE) for s in SEGMENTS]).drop_duplicates("id")
print("selected:", len(picks))
print("  by segment   :", picks.segment.value_counts().to_dict())
print("  by cloth_type:", picks.cloth_type.value_counts().to_dict())

# %% [markdown]
# ## 3. Upload each image to Storage + insert its catalog row

# %%
def _req(url, data=None, method="GET", headers=None, timeout=30):
    r = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

H_KEY = {"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"}
ok = 0; fail = 0
for _, row in picks.iterrows():
    gid = str(int(row["id"]))
    img_path = os.path.join(ROOT, "images", gid + ".jpg")
    if not os.path.exists(img_path):
        fail += 1; continue
    with open(img_path, "rb") as f:
        img = f.read()

    # 3a) upload image to Storage (upsert)
    up_url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{gid}.jpg"
    st, _ = _req(up_url, data=img, method="POST",
                 headers={**H_KEY, "Content-Type": "image/jpeg", "x-upsert": "true"})
    if st not in (200, 201):
        fail += 1; continue
    image_url = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{gid}.jpg"

    # 3b) insert/upsert the catalog row
    name = f"{row.get('baseColour','')} {row['articleType']}".strip()
    payload = json.dumps([{
        "garment_id": gid, "name": name, "cloth_type": row["cloth_type"],
        "segment": row["segment"],
        "category": str(row["articleType"]), "color": str(row.get("baseColour","")),
        "image_url": image_url, "source": "fashion-product-images-small",
        "licence": "research/non-commercial (validation test)",
    }]).encode()
    st, body = _req(f"{SUPABASE_URL}/rest/v1/garments", data=payload, method="POST",
                    headers={**H_KEY, "Content-Type": "application/json",
                             "Prefer": "resolution=merge-duplicates"})
    if st in (200, 201, 204):
        ok += 1
    else:
        fail += 1
        if fail <= 3:
            print("row insert failed:", st, body[:200])
    if (ok + fail) % 25 == 0:
        print(f"  {ok} uploaded, {fail} skipped…")

print(f"\nDONE · {ok} garments in the catalog, {fail} skipped.")

# %% [markdown]
# ## 4. Verify — count rows via the API

# %%
st, body = _req(f"{SUPABASE_URL}/rest/v1/garments?select=cloth_type",
                headers={**H_KEY, "Prefer": "count=exact"})
print("catalog rows now:", st)
# Then open your Railway /closet — it will read these live (set KREY_SUPABASE_URL +
# KREY_SUPABASE_KEY (anon key) on Railway so Service A can read the catalog).
