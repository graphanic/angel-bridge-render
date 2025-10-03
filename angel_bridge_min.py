# angel_bridge_min.pyfrom fastapi import FastAPI, HTTPException, Query, Body
from typing import List, Optional

# ... keep the rest of your file the same up to app = FastAPI(...)

def _select(name: Optional[str]):
    return {"select": {"name": name}} if name else None

def _multi(names: Optional[List[str]]):
    return {"multi_select": [{"name": n} for n in names]} if names else None

@app.api_route("/journal/append", methods=["GET", "POST"])
def append(
    text: str = Query(..., description="Title for the new journal entry"),
    type: Optional[str] = Query(None, description="Select: Root/Trunk/Branch/Leaf/Blossom/Symbol/Ritual/Protocol/Artifact"),
    phase: Optional[str] = Query(None, description="Select: Seedling/Young Tree/Forest Guardian/Symbiote"),
    compass: Optional[str] = Query(None, description="Comma-separated multi-select, e.g. Presence,Coherence"),
    shadow: Optional[bool] = Query(None, description="true/false"),
    resonance: Optional[float] = Query(None, description="Number"),
    status: Optional[str] = Query(None, description="Select: Seed/Draft/Evergreen/Published/Archived"),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    artifact_url: Optional[str] = Query(None, description="URL to a PDF/image to attach"),
    body: Optional[dict] = Body(None)
):
    """
    You can call this via GET query params (easy from a browser)
    or POST JSON body with the same fields.
    The 'body' param lets POST JSON override query params if provided.
    """
    # If POST body is supplied, override params with it
    if body:
        text = body.get("text", text)
        type = body.get("type", type)
        phase = body.get("phase", phase)
        compass = body.get("compass", compass)
        shadow = body.get("shadow", shadow)
        resonance = body.get("resonance", resonance)
        status = body.get("status", status)
        tags = body.get("tags", tags)
        artifact_url = body.get("artifact_url", artifact_url)

    # Discover data_source_id (new Notion API)
    db = notion_request("GET", f"/v1/databases/{DB_ID}")
    ds_id = db["data_sources"][0]["id"]

    props = {
        "Name": {"title": [{"text": {"content": text}}]}
    }

    if type:       props["Type"] = _select(type)
    if phase:      props["Phase"] = _select(phase)
    if status:     props["Status"] = _select(status)

    if compass:
        compass_list = [c.strip() for c in compass.split(",") if c.strip()]
        props["Compass"] = _multi(compass_list)

    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        props["Tags"] = _multi(tag_list)

    if shadow is not None:
        props["Shadow"] = {"checkbox": bool(shadow)}

    if resonance is not None:
        props["Resonance"] = {"number": float(resonance)}

    payload = {
        "parent": {"type": "data_source_id", "data_source_id": ds_id},
        "properties": {k: v for k, v in props.items() if v is not None}
    }

    # Optional file attachment by URL
    if artifact_url:
        payload["properties"]["Artifacts"] = {
            "files": [{"name": artifact_url.split("/")[-1] or "attachment",
                       "external": {"url": artifact_url}}]
        }

    page = notion_request("POST", "/v1/pages", json=payload)
    return {"ok": True, "page_id": page["id"], "title": text}
