# angel_bridge_min.py
import os, re, requests
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, Body

# ----- env (from Render)
RAW_TOKEN = os.environ.get("NOTION_TOKEN", "")
RAW_DB_ID = os.environ.get("JOURNAL_DATABASE_ID", "")

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

# ✅ Use the NEW Notion API version (multi-source DBs)
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2025-09-03",
    "Content-Type": "application/json",
}
BASE = "https://api.notion.com"

def notion_request(method: str, path: str, json: dict | None = None) -> dict:
    r = requests.request(method, f"{BASE}{path}", headers=HEADERS, json=json)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

def _select(name: Optional[str]): return {"select": {"name": name}} if name else None
def _multi(names: Optional[List[str]]): return {"multi_select": [{"name": n} for n in names]} if names else None

# -------- helpers for parent handling (new + old APIs)
def get_parent_for_create() -> dict:
    """
    Try to use a data_source_id (2025-09-03).
    If none found (unlikely), fall back to database_id (legacy style).
    """
    db = notion_request("GET", f"/v1/databases/{DB_ID}")
    ds_list = db.get("data_sources") or []
    if ds_list:
        return {"type": "data_source_id", "data_source_id": ds_list[0]["id"]}
    # Fallback for safety (older behavior)
    return {"type": "database_id", "database_id": DB_ID}

# -------- debug routes
@app.get("/health")
def health(): return {"ok": True}

@app.get("/debug/env")
def debug_env():
    return {
        "token_present": bool(TOKEN),
        "token_len": len(TOKEN),
        "token_tail": TOKEN[-4:] if TOKEN else None,
        "db_present": bool(DB_ID),
        "db_len": len(DB_ID),
        "db_value": DB_ID,
        "notion_version": HEADERS.get("Notion-Version"),
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
        # fallback: old style properties on the database itself
        props = db.get("properties", {})
    return {name: p.get("type") for name, p in props.items()}

# -------- main: journal append (GET or POST)
@app.api_route("/journal/append", methods=["GET", "POST"])
def append(
    text: str = Query(..., description="Title for the new journal entry"),
    type: Optional[str] = Query(None),
    phase: Optional[str] = Query(None),
    compass: Optional[str] = Query(None, description="Comma-separated"),
    shadow: Optional[bool] = Query(None),
    resonance: Optional[float] = Query(None),
    status: Optional[str] = Query(None),
    slug: Optional[str] = Query(None),
    artifact_url: Optional[str] = Query(None),
    body: Optional[dict] = Body(None),
):
    # allow JSON body to override query
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

    parent = get_parent_for_create()

    # Properties — use EXACT keys as in your DB
    props = {"Name": {"title": [{"text": {"content": text}}]}}
    if type:    props["Type"]    = _select(type)
    if phase:   props["Phase"]   = _select(phase)
    if status:  props["Status"]  = _select(status)
    if compass: props["Compass"] = _multi([c.strip() for c in compass.split(",") if c.strip()])
    if shadow is not None:    props["Shadow"]            = {"checkbox": bool(shadow)}
    if resonance is not None: props["Resonance (1-5)"]   = {"number": float(resonance)}
    if slug:                  props["Slug"]              = {"rich_text": [{"text": {"content": slug}}]}

    if artifact_url:
        props["Artifacts"] = {
            "files": [{
                "name": artifact_url.split("/")[-1] or "attachment",
                "external": {"url": artifact_url}
            }]
        }

    payload = {"parent": parent, "properties": props}
    page = notion_request("POST", "/v1/pages", json=payload)
    return {"status": "ok", "page_id": page.get("id"), "url": page.get("url")}

    page = notion_request("POST", "/v1/pages", json=payload)
    return {"status": "ok", "page_id": page.get("id"), "url": page.get("url")}

