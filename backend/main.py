from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
import psycopg2
import os
import hmac
import csv
from io import StringIO

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASS = os.getenv("POSTGRES_PASSWORD")
MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
RESPONSES_PASSWORD = os.getenv("RESPONSES_PASSWORD", "")

def ensure_table():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS markers (
            id SERIAL PRIMARY KEY,
            lat DOUBLE PRECISION,
            lng DOUBLE PRECISION,
            comment TEXT,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    # Backfill/ensure created_at exists for older tables.
    cur.execute("ALTER TABLE markers ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT now()")
    cur.execute("UPDATE markers SET created_at = now() WHERE created_at IS NULL")
    conn.commit()
    cur.close()
    conn.close()

def get_conn():
    return psycopg2.connect(
        host=DB_HOST,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

class Marker(BaseModel):
    lat: float
    lng: float
    comment: str

class PasswordCheck(BaseModel):
    password: str

@app.post("/markers")
def create_marker(marker: Marker):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO markers (lat, lng, comment) VALUES (%s, %s, %s)",
        (marker.lat, marker.lng, marker.comment)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "saved"}

@app.get("/markers")
def get_markers():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, lat, lng, comment, created_at FROM markers ORDER BY created_at DESC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {"id": r[0], "lat": r[1], "lng": r[2], "comment": r[3], "created_at": r[4].isoformat() if r[4] else None}
        for r in rows
    ]

@app.delete("/markers")
def delete_markers():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE markers")
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "cleared"}

@app.get("/markers/export")
def export_markers():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, lat, lng, comment, created_at FROM markers ORDER BY created_at DESC, id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "lat", "lng", "comment", "created_at"])
    for r in rows:
        writer.writerow([r[0], r[1], r[2], r[3] or "", r[4].isoformat() if r[4] else ""])
    csv_data = buffer.getvalue()
    buffer.close()

    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=markers.csv"}
    )

@app.delete("/markers/{marker_id}")
def delete_marker(marker_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM markers WHERE id = %s", (marker_id,))
    deleted = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Marker not found")
    return {"status": "deleted", "id": marker_id}

@app.get("/maps-key")
def get_maps_key():
    if not MAPS_API_KEY:
        return {"error": "GOOGLE_MAPS_API_KEY not configured"}
    return {"apiKey": MAPS_API_KEY}

@app.post("/auth/check")
def auth_check(body: PasswordCheck):
    if not RESPONSES_PASSWORD:
        raise HTTPException(status_code=500, detail="Responses password not configured")
    if not hmac.compare_digest(body.password or "", RESPONSES_PASSWORD):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"ok": True}

# Make sure the table exists on startup
ensure_table()
