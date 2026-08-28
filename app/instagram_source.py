"""
Instagram source adapter — one of the capture SOURCES that feed the twin auto-picker.

SCOPE (be honest): this works only for **Business / Creator** Instagram accounts via the
Instagram Graph API with the `instagram_basic` permission, after Meta App Review. Personal
accounts cannot be read by third parties since the Basic Display API shut down (Dec 2024),
so this covers creators/brands, not the typical consumer. The images it returns are handed
to the SAME capture pipeline (`capture_session.analyze_capture`), which finds the account
owner by face-dominance and discards everyone else (owner-only retention).

Architecture mirrors the rest of Service A: the network I/O (list media, download bytes)
is an INJECTED interface, so the adapter is deterministic and unit-testable with stubs —
no Meta app, no token, no live call, no spend. The reference live fetcher/downloader are
provided but lazy (httpx imported only when actually used); wiring them needs credentials
you provision (see PROVISIONING below).

PROVISIONING (yours to set up — accounts/keys, out of scope for the code):
  1. Meta developer app; IG Business/Creator account linked to a Facebook Page.
  2. App Review for `instagram_basic` (+ `pages_show_list`); Facebook Login (OAuth).
  3. Exchange the login for a long-lived access token + the ig-user-id. Pass BOTH here.
"""
from __future__ import annotations
from typing import Callable, List, Optional, Sequence, Mapping

GRAPH_VERSION = "v21.0"
GRAPH_BASE = "https://graph.facebook.com"
MEDIA_FIELDS = "id,media_type,media_url,timestamp"

# Injected I/O — keeps the adapter testable and credential-free.
#   MediaFetcher(ig_user_id, access_token) -> list of media node dicts
#   Downloader(media_url) -> image bytes
MediaFetcher = Callable[[str, str], List[dict]]
Downloader = Callable[[str], bytes]


def media_endpoint(ig_user_id: str, version: str = GRAPH_VERSION) -> str:
    """The Graph API media edge for an IG user node. Pure (URL builder)."""
    return f"{GRAPH_BASE}/{version}/{ig_user_id}/media"


def image_media(nodes: Sequence[Mapping]) -> List[dict]:
    """Keep only still IMAGE nodes with a usable url; carry the timestamp for recency."""
    out: List[dict] = []
    for n in nodes:
        if n.get("media_type") == "IMAGE" and n.get("media_url"):
            out.append({"id": n.get("id"), "url": n["media_url"], "timestamp": n.get("timestamp")})
    return out


def fetch_account_images(ig_user_id: str, access_token: str, fetcher: MediaFetcher,
                         limit: int = 50) -> List[dict]:
    """List the account's still images (newest as the API returns them), capped at `limit`."""
    nodes = fetcher(ig_user_id, access_token) or []
    return image_media(nodes)[:limit]


def download_images(images: Sequence[Mapping], downloader: Downloader) -> List[bytes]:
    """Fetch bytes for each image url; skip any that fail (never raise on one bad item)."""
    out: List[bytes] = []
    for im in images:
        try:
            b = downloader(im["url"])
        except Exception:
            continue
        if b:
            out.append(b)
    return out


def ingest_from_instagram(ig_user_id: str, access_token: str, fetcher: MediaFetcher,
                          downloader: Downloader, limit: int = 50) -> List[bytes]:
    """
    End-to-end source step: list -> download -> image bytes ready for the capture pipeline
    (write to temp files and call analyze_capture, exactly like an upload set). The owner
    auto-pick + owner-only retention happen downstream in capture_session — this adapter
    only sources the pixels. Returns [] when the account has no usable images.
    """
    images = fetch_account_images(ig_user_id, access_token, fetcher, limit=limit)
    return download_images(images, downloader)


# ---------------------------------------------------------------------------
# Reference live I/O — NOT invoked by tests; needs a real token (you provision).
# Lazy httpx import keeps this module pure to import.
# ---------------------------------------------------------------------------
def graph_media_fetcher(ig_user_id: str, access_token: str) -> List[dict]:
    """Live MediaFetcher: GET the media edge with fields+token. Requires a valid token."""
    import httpx
    url = media_endpoint(ig_user_id)
    nodes, params = [], {"fields": MEDIA_FIELDS, "access_token": access_token, "limit": 100}
    with httpx.Client(timeout=30) as client:
        while url:
            r = client.get(url, params=params)
            r.raise_for_status()
            body = r.json()
            nodes.extend(body.get("data", []))
            url = (body.get("paging") or {}).get("next")
            params = None  # `next` is a fully-formed URL
    return nodes


def http_downloader(media_url: str) -> bytes:
    """Live Downloader: GET the image bytes from a media_url (short-lived CDN URL)."""
    import httpx
    r = httpx.get(media_url, timeout=30)
    r.raise_for_status()
    return r.content
