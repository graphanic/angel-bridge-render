# angel_bridge_min.py
import os, re, requests
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Query, Body

# ----- env (what Render provides)
RAW_TOKEN = os.environ.get("NOTION_TOKEN", "")
RAW_DB_ID = os.environ.get("JOURNAL_DATABASE_ID", "")

# ----- normalize ids (accept 32 or 36 chars)
def normalize_uuid(s: str) -> str:
    """Return hyphenated UUID (8-4-4-4-12) from compact or hyphenated input."""
    if not s:
        return s
    t = s.strip().lower()
    t = t.replace("-", "")
    if not re.fullmatch(r"[0-9a-f]{32}", t or ""):
        return s  # leave as-is; we'll let Notion complain
    return f"{t[0:8]}-{t[8:12]}-{t[12:16]}-{t[16:20]}-{t[20:32]}"

TOKEN = RAW_TOKEN.strip()
DB_ID = normalize_uuid(RAW_DB_ID)

# ----- app (must exist before decorators)
app = FastAPI(title="Angel Bridge (Render)")

# ----- constants
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2025-09-03",
    "Content-Type": "application/json",
}
BASE = "https://api.notion.com"

# ----- helpers
def notion_request(method: str, path: str, json: dict | None = None) -> dict:
    r = requests.request(method, f"{BASE}{path}", headers=HEADERS, json=json)
    if r.status_code >= 400:
        # bubble up Notion's error body for easy debugging
        raise HTTPException(r.status_code, r.text)
    return r.json()

def _select(name: Optional[str]):
    return {"select": {"name": name}} if name else None

def _multi(names: Optional[List[str]]):
    return {"multi_select": [{"name": n} for n in names]} if names else None

# ----- debug routes (harmless, no secrets leaked)
@app.get("/debug/env")
def debug_env():
    return {
        "token_present": bool(TOKEN),
        "token_len": len(TOKEN),
        "token_tail": TOKEN[-4:] if TOKEN else None,
        "db_present": bool(DB_ID),
        "db_len": len(DB_ID),
        "db_value": DB_ID,  # hyphenated form after normalization
    }

@app.get("/probe/db")
def probe_db():
    """Ask Notion for the DB and return its data_sources + title."""
    db = notion_request("GET", f"/v1/databases/{DB_ID}")
    return {
        "object": db.get("object"),
        "id": db.get("id"),
        "title_plain": " ".join([t["plain_text"] for t in db.get("title", [])]),
        "data_sources": db.get("data_sources", []),
    }

# ----- main routes
@app.get("/health")
def health():
    return {"ok": True}

@app.api_route("/journal/append", methods=["GET", "POST"])
def append(
    text: str = Query(..., description="Title for the new journal entry"),
    type: Optional[str] = Query(None),
    phase: Optional[str] = Query(None),
    compass: Optional[str] = Query(None, description="Comma-separated"),
    shadow: Optional[bool] = Query(None),
    resonance: Optional[float] = Query(None),
    status: Optional[str] = Query(None),
    tags: Optional[str] = Query(None, description="Comma-separated"),
    artifact_url: Optional[str] = Query(None),
    body: Optional[dict] = Body(None),
):
    if body:
        text        = body.get("text", text)
        type        = body.get("type", type)
        phase       = body.get("phase", phase)
        compass     = body.get("compass", compass)
        shadow      = body.get("shadow", shadow)
        resonance   = body.get("resonance", resonance)
        status      = body.get("status", status)
        tags        = body.get("tags", tags)
        artifact_url= body.get("artifact_url", artifact_url)

    # Discover the first data_source under this database
    db   = notion_request("GET", f"/v1/databases/{DB_ID}")
    ds_id = db["data_sources"][0]["id"]

    props = {"Name": {"title": [{"text": {"content": text}}]}}
    if type:    props["Type"]    = _select(type)
    if phase:   props["Phase"]   = _select(phase)
    if status:  props["Status"]  = _select(status)
    if compass: props["Compass"] = _multi([c.strip() for c in compass.split(",") if c.strip()])
    if tags:    props["Tags"]    = _multi([t.strip() for t in tags.split(",") if t.strip()])
    if shadow is not None:    props["Shadow"]    = {"checkbox": bool(shadow)}
    if resonance is not None: props["Resonance"] = {"number": float(resonance)}

    payload = {
        "parent": {"type": "data_source_id", "data_source_id": ds_id},
        "properties": props,
    }
    if artifact_url:
        payload["properties"]["Artifacts"] = {
            "files": [{
                "name": artifact_url.split("/")[-1] or "attachment",
                "external": {"url": artifact_url}
            }]
        }

    page = notion_request("POST", "/v1/pages", json=payload)
    return {"ok": True, "page_id": page["id"], "title": text}
