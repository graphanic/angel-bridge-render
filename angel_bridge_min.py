# angel_bridge_min.py
import os, re, requests
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, Body, Header

# ===== ENV =====
RAW_TOKEN = os.environ.get("NOTION_TOKEN", "")
RAW_DB_ID = os.environ.get("JOURNAL_DATABASE_ID", "")
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "")  # optional, recommended

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

def _select(name: Optional[str]):  
    return {"select": {"name": name}} if name else None

def _multi(names: Optional[List[str]]):  
    return {"multi_select": [{"name": n} for n in names]} if names else None

def get_parent_for_create() -> dict:
    db = notion_request("GET", f"/v1/databases/{DB_ID}")
    ds_list = db.get("data_sources") or []
    if ds_list:
        return {"type": "data_source_id", "data_source_id": ds_list[0]["id"]}
    return {"type": "database_id", "database_id": DB_ID}  # fallback

def require_secret(secret_header: Optional[str], secret_query: Optional[str]):
    """If BRIDGE_SECRET is set, require it via header or query."""
    if not BRIDGE_SECRET:
        return  # open mode
    if secret_header == BRIDGE_SECRET or secret_query == BRIDGE_SECRET:
        return
    raise HTTPException(status_code=401, detail="Unauthorized: missing/invalid bridge secret")

def make_paragraph_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
        },
    }

def blocks_from_plaintext(content: str) -> List[dict]:
    # Simple: split on blank lines to paragraphs
    paras = [p.strip() for p in content.replace("\r\n", "\n").split("\n\n") if p.strip()]
    return [make_paragraph_block(p) for p in paras] or [make_paragraph_block(content)]

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
@app.api_route("/journal/append", methods=["POST"])
def append(
    text: Optional[str] = Query(None, description="Title (optional if JSON body provided)"),
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

    # body overrides query
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
        raise HTTPException(422, "Provide 'text' either in JSON body {'text': ...} or as ?text=...")

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
        props["Artifacts"] = {"files": [{"name": artifact_url.split("/")[-1] or "attachment",
                                          "external": {"url": artifact_url}}]}

    payload = {"parent": parent, "properties": props}

    # Add body content as blocks on create, if provided
    if content:
        payload["children"] = blocks_from_plaintext(content)

    page = notion_request("POST", "/v1/pages", json=payload)
    return {"status": "ok", "page_id": page.get("id"), "url": page.get("url")}
