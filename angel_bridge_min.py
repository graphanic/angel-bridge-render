# angel_bridge_min.py — Angel Bridge (full scaffold v2)
# FastAPI service to write/read the Sacred Memory Temple (Notion)
# Features:
#  - /health, /debug/env, /probe/db, /debug/schema
#  - /journal/append  (create full entry)
#  - /journal/log     (quick seed)
#  - /journal/add_content (append blocks to page)
#  - /journal/search  (keyword over pages; returns light results)
#  - /journal/pulse   (surface most resonant seeds)
#  - /journal/update  (update properties on a page)
#  - /journal/whisper (private/hidden entry if property exists)
# Notes:
#  - Supports Notion API 2025-09-03 multi-source databases
#  - Accepts JSON body; query params are optional
#  - Optional BRIDGE_SECRET header or ?secret= for protection

import os, re, requests
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Query, Body, Header

# ===== ENV =====
RAW_TOKEN = os.environ.get("NOTION_TOKEN", "")
RAW_DB_ID = os.environ.get("JOURNAL_DATABASE_ID", "")
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "")  # optional, recommended

# Property names used in your Notion DB
PROP_TITLE = "Name"
PROP_TYPE = "Type"
PROP_PHASE = "Phase"
PROP_COMPASS = "Compass"
PROP_SHADOW = "Shadow"
PROP_RESONANCE = "Resonance (1-5)"
PROP_STATUS = "Status"
PROP_SLUG = "Slug"
PROP_ARTIFACTS = "Artifacts"
PROP_VISIBILITY = "Visibility"  # create this as Select: Public/Private (optional)


# ===== helpers =====
def normalize_uuid(s: str) -> str:
    if not s:
        return s
    t = s.strip().lower().replace("-", "")
    if not re.fullmatch(r"[0-9a-f]{32}", t or ""):
        return s
    return f"{t[0:8]}-{t[8:12]}-{t[12:16]}-{t[16:20]}-{t[20:32]}"

TOKEN = RAW_TOKEN.strip()
DB_ID = normalize_uuid(RAW_DB_ID)

app = FastAPI(title="Angel Bridge (Render)")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2025-09-03",
    "Content-Type": "application/json",
}
BASE = "https://api.notion.com"


def notion_request(method: str, path: str, json: Dict[str, Any] | None = None) -> Dict[str, Any]:
    r = requests.request(method, f"{BASE}{path}", headers=HEADERS, json=json)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    if r.status_code == 204:
        return {}
    return r.json()


def _select(name: Optional[str]):
    return {"select": {"name": name}} if name else None


def _multi(names: Optional[List[str]]):
    return {"multi_select": [{"name": n} for n in names]} if names else None


def make_paragraph_block(text: str) -> Dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def blocks_from_plaintext(content: str) -> List[Dict[str, Any]]:
    paras = [p.strip() for p in content.replace("\r\n", "\n").split("\n\n") if p.strip()]
    return [make_paragraph_block(p) for p in paras] or [make_paragraph_block(content)]


def require_secret(secret_header: Optional[str], secret_query: Optional[str]):
    if not BRIDGE_SECRET:
        return
    if secret_header == BRIDGE_SECRET or secret_query == BRIDGE_SECRET:
        return
    raise HTTPException(401, "Unauthorized: missing/invalid bridge secret")


def get_ds_id() -> str:
    """Return first data_source id (multi-source safe)."""
    db = notion_request("GET", f"/v1/databases/{DB_ID}")
    ds_list = db.get("data_sources") or []
    if not ds_list:
        # Legacy DB (pre multi-source) — use database_id parent
        return ""
    return ds_list[0]["id"]


def get_parent_for_create() -> Dict[str, Any]:
    ds_id = get_ds_id()
    if ds_id:
        return {"type": "data_source_id", "data_source_id": ds_id}
    return {"type": "database_id", "database_id": DB_ID}


# ===== debug/introspection =====
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/debug/env")
def debug_env():
    return {
        "token_present": bool(TOKEN),
        "db_value": DB_ID,
        "notion_version": HEADERS.get("Notion-Version"),
        "secret_required": bool(BRIDGE_SECRET),
    }


@app.get("/probe/db")
def probe_db():
    db = notion_request("GET", f"/v1/databases/{DB_ID}")
    return {
        "object": db.get("object"),
        "id": db.get("id"),
        "title_plain": " ".join([t.get("plain_text", "") for t in db.get("title", [])]),
        "data_sources": db.get("data_sources", []),
    }


@app.get("/debug/schema")
def debug_schema():
    db = notion_request("GET", f"/v1/databases/{DB_ID}")
    ds_list = db.get("data_sources") or []
    if ds_list:
        ds = notion_request("GET", f"/v1/data_sources/{ds_list[0]['id']}")
        props = ds.get("properties", {})
    else:
        props = db.get("properties", {})
    return {name: p.get("type") for name, p in props.items()}


# ===== journal creation =====
@app.post("/journal/append")
def append(
    text: Optional[str] = Query(None, description="Title (optional if provided in JSON body)"),
    type: Optional[str] = Query(None),
    phase: Optional[str] = Query(None),
    compass: Optional[str] = Query(None, description="Comma-separated"),
    shadow: Optional[bool] = Query(None),
    resonance: Optional[float] = Query(None),
    status: Optional[str] = Query(None),
    slug: Optional[str] = Query(None),
    artifact_url: Optional[str] = Query(None),
    content: Optional[str] = Query(None, description="Plain text content"),
    body: Optional[Dict[str, Any]] = Body(None),
    x_bridge_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    require_secret(x_bridge_secret, secret)

    if body:
        text        = body.get("text", text)
        type        = body.get("type", type)
        phase       = body.get("phase", phase)
        compass     = body.get("compass", compass)
        shadow      = body.get("shadow", shadow)
        resonance   = body.get("resonance", resonance)
        status      = body.get("status", status)
        slug        = body.get("slug", slug)
        artifact_url= body.get("artifact_url", artifact_url)
        content     = body.get("content", content)

    if not text:
        raise HTTPException(422, "Provide 'text' in JSON body or as ?text=")

    props = {PROP_TITLE: {"title": [{"text": {"content": text}}]}}
    if type:    props[PROP_TYPE]   = _select(type)
    if phase:   props[PROP_PHASE]  = _select(phase)
    if status:  props[PROP_STATUS] = _select(status)
    if compass: props[PROP_COMPASS]= _multi([c.strip() for c in compass.split(",") if c.strip()])
    if shadow is not None:    props[PROP_SHADOW]    = {"checkbox": bool(shadow)}
    if resonance is not None: props[PROP_RESONANCE] = {"number": float(resonance)}
    if slug:    props[PROP_SLUG]   = {"rich_text": [{"text": {"content": slug}}]}
    if artifact_url:
        props[PROP_ARTIFACTS] = {"files": [{"name": artifact_url.split("/")[-1] or "attachment", "external": {"url": artifact_url}}]}

    payload = {"parent": get_parent_for_create(), "properties": props}
    if content:
        payload["children"] = blocks_from_plaintext(content)

    page = notion_request("POST", "/v1/pages", json=payload)
    return {"status": "ok", "page_id": page.get("id"), "url": page.get("url")}


# ===== quick log =====
@app.post("/journal/log")
def quick_log(
    text: Optional[str] = Query(None),
    content: Optional[str] = Query(None),
    resonance: Optional[float] = Query(1.0),
    body: Optional[Dict[str, Any]] = Body(None),
    x_bridge_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    """Minimal friction: only text/content, sensible defaults."""
    require_secret(x_bridge_secret, secret)

    if body:
        text      = body.get("text", text)
        content   = body.get("content", content)
        resonance = body.get("resonance", resonance)

    if not text:
        raise HTTPException(422, "Provide 'text' for quick_log")

    props = {
        PROP_TITLE: {"title": [{"text": {"content": text}}]},
        PROP_TYPE:  _select("Log"),
        PROP_PHASE: _select("Seedling"),
        PROP_STATUS:_select("Seed"),
        PROP_SHADOW:{"checkbox": False},
        PROP_RESONANCE: {"number": float(resonance or 1)},
    }
    payload = {"parent": get_parent_for_create(), "properties": props}
    if content:
        payload["children"] = blocks_from_plaintext(content)

    page = notion_request("POST", "/v1/pages", json=payload)
    return {"status": "ok", "page_id": page.get("id"), "url": page.get("url")}


# ===== add content to existing page =====
@app.post("/journal/add_content")
def add_content(
    page_id: str = Query(..., description="Target Notion page_id (UUID)"),
    content: str = Query(..., description="Plain text to append"),
    x_bridge_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    require_secret(x_bridge_secret, secret)
    blocks = blocks_from_plaintext(content)
    notion_request("PATCH", f"/v1/blocks/{page_id}/children", json={"children": blocks})
    return {"status": "ok", "appended_blocks": len(blocks)}


# ===== search over pages =====
@app.get("/journal/search")
def search(q: str = Query(..., description="keyword"), limit: int = Query(10, ge=1, le=50)):
    # Notion Search: object must be page|data_source in 2025-09-03
    body = {"query": q, "filter": {"value": "page", "property": "object"}, "page_size": limit}
    res = notion_request("POST", "/v1/search", json=body)
    items = []
    for r in res.get("results", []):
        pid = r.get("id")
        url = r.get("url")
        title = ""
        props = (r.get("properties") or {})
        if PROP_TITLE in props and props[PROP_TITLE].get("type") == "title":
            rich = props[PROP_TITLE].get("title", [])
            title = "".join([t.get("plain_text", "") for t in rich])
        items.append({"page_id": pid, "title": title, "url": url})
    return {"count": len(items), "items": items}


# ===== resonance pulse (top N by resonance) =====
@app.get("/journal/pulse")
def pulse(limit: int = Query(5, ge=1, le=25)):
    ds_id = get_ds_id()
    if ds_id:
        # data_source query with sort on resonance desc
        body = {
            "sorts": [{"property": PROP_RESONANCE, "direction": "descending"}],
            "page_size": limit,
        }
        res = notion_request("PATCH", f"/v1/data_sources/{ds_id}/query", json=body)
    else:
        # legacy databases: /databases/{id}/query
        body = {
            "sorts": [{"property": PROP_RESONANCE, "direction": "descending"}],
            "page_size": limit,
        }
        res = notion_request("POST", f"/v1/databases/{DB_ID}/query", json=body)

    items = []
    for r in res.get("results", []):
        pid = r.get("id")
        url = r.get("url")
        props = r.get("properties", {})
        title = ""
        if PROP_TITLE in props:
            title = "".join([t.get("plain_text", "") for t in props[PROP_TITLE].get("title", [])])
        resonance = None
        if PROP_RESONANCE in props and props[PROP_RESONANCE].get("type") == "number":
            resonance = props[PROP_RESONANCE].get("number")
        items.append({"page_id": pid, "title": title, "resonance": resonance, "url": url})
    return {"count": len(items), "items": items}


# ===== update properties on a page =====
@app.post("/journal/update")
def update_page_properties(
    page_id: str = Query(...),
    properties: Dict[str, Any] = Body(..., description="Raw Notion properties object"),
    x_bridge_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    require_secret(x_bridge_secret, secret)
    res = notion_request("PATCH", f"/v1/pages/{page_id}", json={"properties": properties})
    return {"status": "ok", "page_id": res.get("id")}


# ===== whisper (private note) =====
@app.post("/journal/whisper")
def whisper(
    text: str = Query(...),
    content: Optional[str] = Query(None),
    body: Optional[Dict[str, Any]] = Body(None),
    x_bridge_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    require_secret(x_bridge_secret, secret)
    if body:
        text = body.get("text", text)
        content = body.get("content", content)

    props = {
        PROP_TITLE: {"title": [{"text": {"content": text}}]},
        PROP_TYPE: _select("Whisper"),
        PROP_STATUS: _select("Hidden"),
    }
    # If Visibility column exists, set it = Private
    try:
        schema = debug_schema()  # local call
        if PROP_VISIBILITY in schema:
            props[PROP_VISIBILITY] = _select("Private")
    except Exception:
        pass

    payload = {"parent": get_parent_for_create(), "properties": props}
    if content:
        payload["children"] = blocks_from_plaintext(content)

    page = notion_request("POST", "/v1/pages", json=payload)
    return {"status": "ok", "page_id": page.get("id"), "url": page.get("url")}
