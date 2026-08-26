import concurrent.futures
import os
import threading
import time
import requests
import psycopg2
from psycopg2.extras import execute_values
from flask import Flask, Response, jsonify

app = Flask(__name__)

# Neon DB Connection String
DATABASE_URL = os.environ.get(
    "DATABASE_URL", 
    "postgresql://neondb_owner:npg_hgdH3uxfFc0X@ep-billowing-leaf-ax2m99uj-pooler.c-4.us-east-2.aws.neon.tech/neondb?sslmode=require"
)

DOMAINS = [
    "turnerlive.warnermediacdn.com",
    "tve-live-ctl.warnermediacdn.com",
    "turnerlive.cdn.turner.com"
]

EVENT_IDS = range(2023175, 2024200)
SLATE_TYPES = ["noslate", "slate"]
PATH_TEMPLATES = [
    "hls/live/{event_id}/toonwest/{slate}/index.m3u8",
    "hls/live/{event_id}/toonwest/{slate}/master.m3u8",
    "hls/live/{event_id}/toonwest/{slate}/VIDEO_1_5128000.m3u8",
    "hls/live/{event_id}/toonwest/index.m3u8"
]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.adultswim.com/",
    "Origin": "https://www.adultswim.com"
}

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    """Create the streams table if it does not exist."""
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS active_streams (
                id SERIAL PRIMARY KEY,
                channel_name VARCHAR(100),
                url TEXT UNIQUE NOT NULL,
                last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Init Error: {e}")

# Initialize DB table on boot
init_db()

def check_endpoint(url):
    headers = DEFAULT_HEADERS.copy()
    headers["Range"] = "bytes=0-512"
    try:
        response = requests.get(url, headers=headers, timeout=2.5, stream=True)
        if response.status_code in (200, 206):
            chunk = next(response.iter_content(chunk_size=512), b"")
            if b"#EXTM3U" in chunk or b"#EXTINF" in chunk:
                return url
    except Exception:
        pass
    return None

def update_db_feeds():
    """Background worker that scans candidate URLs and saves active ones to Neon DB."""
    candidates = []
    for domain in DOMAINS:
        for event_id in EVENT_IDS:
            for slate in SLATE_TYPES:
                for path_tmpl in PATH_TEMPLATES:
                    candidates.append(f"https://{domain}/" + path_tmpl.format(event_id=event_id, slate=slate))

    # Keep thread pool moderate (20 max) to stay within Render's 512MB RAM cap
    working_feeds = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(check_endpoint, url): url for url in candidates}
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                working_feeds.append(res)

    if working_feeds:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("TRUNCATE TABLE active_streams;")
            records = [("Cartoon Network West", url) for url in working_feeds]
            execute_values(cur, "INSERT INTO active_streams (channel_name, url) VALUES %s ON CONFLICT (url) DO NOTHING;", records)
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"DB Update Error: {e}")

def background_loop():
    while True:
        update_db_feeds()
        time.sleep(900)  # Scan every 15 minutes

# Run thread in background
threading.Thread(target=background_loop, daemon=True).start()

@app.route("/")
@app.route("/toonwest.m3u")
@app.route("/playlist.m3u")
def generate_playlist():
    feeds = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT url FROM active_streams;")
        rows = cur.fetchall()
        feeds = [row[0] for row in rows]
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Fetch Error: {e}")

    playlist_lines = ["#EXTM3U\n"]
    for idx, stream_url in enumerate(feeds, 1):
        playlist_lines.append(f'#EXTINF:-1 tvg-id="CartoonNetworkWest.us" tvg-name="CN West Feed {idx}",Cartoon Network West (Feed {idx})')
        playlist_lines.append(f"{stream_url}\n")

    return Response("\n".join(playlist_lines), mimetype="audio/x-mpegurl")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
