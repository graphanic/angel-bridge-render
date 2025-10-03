# angel_bridge_min.py
import os, re, requests
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, Body, Header

# ===== ENV =====
RAW_TOKEN = os.environ.get("NOTION_TOKEN", "")
RAW_DB_ID = os.environ.get("JOURNAL_DATABASE_ID", "")
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "")  # optional

def normalize_uuid(s: str) -> str:
    if not s:
        return s
    t = s.strip().lower().replace("-", "")
    if not re.fullmatch(r"[0-9a-f]{32}", t or ""):
        return s
    return f"{t[0:8]}-{t[8:12]}-{t[12:16]}-{t[16:20]}-{t[20:32]}"

TOKEN = RAW_TOKEN.strip()
DB_ID = normalize_uuid(RAW_DB_ID)

# ===== APP =====
app = FastAPI(title="Angel Bridge (Render)")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2025-09-03",
    "Content-Type": "application/json",
}
BASE = "https://api.notion.com"

# ===== UTIL =====
def notion_request(method: str, path: str, json: dict | None = None) -> dict:
    r = requests.request(method, f"{BASE}{path}", headers=HEADERS, json=json)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

def _select(name: Optional[str]):  return {"select": {"name": name}} if name else None
def _multi(names: Optional[List[str]]):  return {"multi_select": [{"name": n} for n in names]} if names else None

def get_parent_for_create() -> dict:
    db = notion_request("GET", f"/v1/databases/{DB_ID}")
    ds_list = db.get("data_sources") or []
    if ds_list:
        return {"type": "data_source_id", "data_source_id": ds_list[0]["id"]}
    return {"type": "database_id", "database_id": DB_ID}

def get_data_source_id() -> Optional[str]:
    db = notion_request("GET", f"/v1/databases/{DB_ID}")
    ds_list = db.get("data_sources") or []
    return ds_list[0]["id"] if ds_list else None

def require_secret(secret_header: Optional[str], secret_query: Optional[str]):
    if not BRIDGE_SECRET:
        return
    if secret_header == BRIDGE_SECRET or secret_query == BRIDGE_SECRET:
        return
    raise HTTPException(status_code=401, detail="Unauthorized: missing/invalid bridge secret")

def make_paragraph_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }

def blocks_from_plaintext(content: str) -> List[dict]:
    paras = [p.strip() for p in content.replace("\r\n", "\n").split("\n\n") if p.strip()]
    return [make_paragraph_block(p) for p in paras] or [make_paragraph_block(content)]

def extract_title(properties: dict) -> str:
    t = properties.get("Name", {}).get("title", [])
    return "".join([frag.get("plain_text", "") for frag in t]) if t else ""

def fetch_blocks(page_id: str, max_blocks: int = 2000) -> List[dict]:
    results, start_cursor = [], None
    fetched = 0
    while True:
        path = f"/v1/blocks/{page_id}/children?page_size=100"
        if start_cursor:
            path += f"&start_cursor={start_cursor}"
        data = notion_request("GET", path)
        batch = data.get("results", [])
        results.extend(batch)
        fetched += len(batch)
        if not data.get("has_more") or fetched >= max_blocks:
            break
        start_cursor = data.get("next_cursor")
    return results

# ===== DEBUG =====
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
        "title_plain": " ".join([t.get("plain_text","") for t in db.get("title", [])]),
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

# ===== JOURNAL: create with properties (+ optional content) =====
@app.api_route("/journal/append", methods=["GET", "POST"])
def append(
    text: str = Query(..., description="Title"),
    type: Optional[str] = Query(None),
    phase: Optional[str] = Query(None),
    compass: Optional[str] = Query(None, description="Comma-separated"),
    shadow: Optional[bool] = Query(None),
    resonance: Optional[float] = Query(None),
    status: Optional[str] = Query(None),
    slug: Optional[str] = Query(None),
    artifact_url: Optional[str] = Query(None),
    content: Optional[str] = Query(None, description="Plain text content"),
    body: Optional[dict] = Body(None),
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

    parent = get_parent_for_create()

    props = {"Name": {"title": [{"text": {"content": text}}]}}
    if type:    props["Type"]    = _select(type)
    if phase:   props["Phase"]   = _select(phase)
    if status:  props["Status"]  = _select(status)
    if compass: props["Compass"] = _multi([c.strip() for c in compass.split(",") if c.strip()])
    if shadow is not None:    props["Shadow"] = {"checkbox": bool(shadow)}
    if resonance is not None: props["Resonance (1-5)"] = {"number": float(resonance)}
    if slug:    props["Slug"] = {"rich_text": [{"text": {"content": slug}}]}
    if artifact_url:
        props["Artifacts"] = {"files": [{
            "name": artifact_url.split("/")[-1] or "attachment",
            "external": {"url": artifact_url}
        }]}

    payload = {"parent": parent, "properties": props}
    if content:
        payload["children"] = blocks_from_plaintext(content)

    page = notion_request("POST", "/v1/pages", json=payload)
    return {"status": "ok", "page_id": page.get("id"), "url": page.get("url")}

# ===== JOURNAL: ultra-fast logging with defaults =====
@app.api_route("/journal/log", methods=["GET", "POST"])
def quick_log(
    text: str = Query(..., description="Title"),
    content: Optional[str] = Query(None),
    body: Optional[dict] = Body(None),
    x_bridge_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    require_secret(x_bridge_secret, secret)

    if body:
        text    = body.get("text", text)
        content = body.get("content", content)

    parent = get_parent_for_create()
    props = {
        "Name": {"title": [{"text": {"content": text}}]},
        "Type": _select("Log"),
        "Phase": _select("Seedling"),
        "Status": _select("Seed"),
        "Shadow": {"checkbox": False},
    }
    payload = {"parent": parent, "properties": props}
    if content:
        payload["children"] = blocks_from_plaintext(content)

    page = notion_request("POST", "/v1/pages", json=payload)
    return {"status": "ok", "page_id": page.get("id"), "url": page.get("url")}

# ===== JOURNAL: append content to an existing page =====
@app.post("/journal/add_content")
def add_content(
    page_id: str = Query(..., description="Target Notion page_id"),
    content: str = Query(..., description="Plain text to append"),
    x_bridge_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    require_secret(x_bridge_secret, secret)
    children = blocks_from_plaintext(content)
    res = notion_request("PATCH", f"/v1/blocks/{page_id}/children", json={"children": children})
    return {"status": "ok", "appended": len(children), "result": res}

# ===== JOURNAL: read endpoints =====
@app.get("/journal/fetch_recent")
def fetch_recent(
    limit: int = Query(10, ge=1, le=100),
    include_blocks: bool = Query(False),
    x_bridge_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    require_secret(x_bridge_secret, secret)

    ds_id = get_data_source_id()
    query_payload = {
        "page_size": limit,
        "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
    }

    if ds_id:
        res = notion_request("PATCH", f"/v1/data_sources/{ds_id}/query", json=query_payload)
    else:
        res = notion_request("POST", f"/v1/databases/{DB_ID}/query", json=query_payload)

    pages = []
    for p in res.get("results", []):
        obj = {
            "id": p["id"],
            "url": p.get("url"),
            "last_edited_time": p.get("last_edited_time"),
            "properties": p.get("properties", {}),
            "title": extract_title(p.get("properties", {})),
        }
        if include_blocks:
            obj["blocks"] = fetch_blocks(p["id"])
        pages.append(obj)

    return {"count": len(pages), "pages": pages}

@app.get("/journal/fetch_all")
def fetch_all(
    page_size: int = Query(100, ge=1, le=100),
    include_blocks: bool = Query(False),
    since_last_edited: Optional[str] = Query(None),
    status_equals: Optional[str] = Query(None),
    type_equals: Optional[str] = Query(None),
    x_bridge_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    require_secret(x_bridge_secret, secret)

    ds_id = get_data_source_id()
    payload = {"page_size": page_size}

    filters = []
    if since_last_edited:
        filters.append({
            "timestamp": "last_edited_time",
            "last_edited_time": {"on_or_after": since_last_edited}
        })
    if status_equals:
        filters.append({"property": "Status", "select": {"equals": status_equals}})
    if type_equals:
        filters.append({"property": "Type", "select": {"equals": type_equals}})
    if filters:
        payload["filter"] = {"and": filters}

    pages, next_cursor = [], None
    while True:
        if next_cursor:
            payload["start_cursor"] = next_cursor

        if ds_id:
            res = notion_request("PATCH", f"/v1/data_sources/{ds_id}/query", json=payload)
        else:
            res = notion_request("POST", f"/v1/databases/{DB_ID}/query", json=payload)

        for p in res.get("results", []):
            obj = {
                "id": p["id"],
                "url": p.get("url"),
                "last_edited_time": p.get("last_edited_time"),
                "properties": p.get("properties", {}),
                "title": extract_title(p.get("properties", {})),
            }
            if include_blocks:
                obj["blocks"] = fetch_blocks(p["id"])
            pages.append(obj)

        if not res.get("has_more"):
            break
        next_cursor = res.get("next_cursor")

    return {"count": len(pages), "pages": pages}

@app.get("/journal/fetch_page")
def fetch_page(
    page_id: str = Query(...),
    include_blocks: bool = Query(True),
    x_bridge_secret: Optional[str] = Header(None),
    secret: Optional[str] = Query(None),
):
    require_secret(x_bridge_secret, secret)
    page = notion_request("GET", f"/v1/pages/{page_id}")
    obj = {
        "id": page["id"],
        "url": page.get("url"),
        "last_edited_time": page.get("last_edited_time"),
        "properties": page.get("properties", {}),
        "title": extract_title(page.get("properties", {})),
    }
    if include_blocks:
        obj["blocks"] = fetch_blocks(page["id"])
    return obj
