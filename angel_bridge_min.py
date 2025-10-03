# angel_bridge_min.py
import os, requests
from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.environ["NOTION_TOKEN"]
DB_ID = os.environ["JOURNAL_DATABASE_ID"]

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Notion-Version": "2025-09-03",
    "Content-Type": "application/json"
}

BASE = "https://api.notion.com"
app = FastAPI()

def notion_request(method, path, json=None):
    url = f"{BASE}{path}"
    r = requests.request(method, url, headers=HEADERS, json=json)
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text)
    return r.json()

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/journal/append")
def append(text: str):
    # Discover data_source_id for this DB
    db = notion_request("GET", f"/v1/databases/{DB_ID}")
    ds_id = db["data_sources"][0]["id"]

    payload = {
        "parent": {"type": "data_source_id", "data_source_id": ds_id},
        "properties": {
            "Name": {"title": [{"text": {"content": text}}]}
        }
    }
    page = notion_request("POST", "/v1/pages", json=payload)
    return {"ok": True, "page_id": page["id"]}
