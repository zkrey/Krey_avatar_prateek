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
# ## 2. Load the dataset metadata + map articleType → cloth_type

# %%
import os, io, json, time, urllib.request, urllib.error
import pandas as pd

styles = pd.read_csv(os.path.join(ROOT, "styles.csv"), on_bad_lines="skip")
UPPER = {"Tshirts","Shirts","Tops","Kurtas","Sweatshirts","Sweaters","Jackets","Blazers","Tunics","Waistcoat"}
LOWER = {"Jeans","Trousers","Track Pants","Shorts","Skirts","Leggings","Capris"}
OVERALL = {"Dresses","Jumpsuit"}
def cloth_type(a):
    return "upper" if a in UPPER else "lower" if a in LOWER else "overall" if a in OVERALL else None
styles["cloth_type"] = styles["articleType"].map(cloth_type)
g = styles.dropna(subset=["cloth_type"])
# spread across types, cap per type
picks = pd.concat([g[g.cloth_type==t].head(N_PER_TYPE) for t in ("upper","lower","overall")])
print("selected:", len(picks), "\n", picks.cloth_type.value_counts().to_dict())

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
