import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, Response, jsonify
import requests

app = Flask(__name__)

# Database configuration (supports SQLite locally or persistent disk path on Render)
DB_PATH = os.environ.get("DB_PATH", "streams.db")

# CDN edge wildcards and Turner/WBD stream targets
CDN_PROVIDERS = ["aka", "lln", "ctl", "cfl", "fna"]
STREAM_NAMES = ["toonwest", "tooneast", "adultswim", "cartoonnetwork"]
PATH_VARIANTS = ["noslate", "slate"]

# Range of Akamai CP/Event IDs to scan
START_ID = 2023150
END_ID = 2023200

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Origin": "https://www.adultswim.com",
    "Referer": "https://www.adultswim.com/",
}


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS active_streams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stream_name TEXT NOT NULL,
            cdn_provider TEXT NOT NULL,
            event_id INTEGER NOT NULL,
            url TEXT UNIQUE NOT NULL,
            status TEXT NOT NULL,
            last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """
    )
    conn.commit()
    conn.close()


def check_endpoint(args):
    cdn, stream_name, event_id, path_variant = args
    url = f"https://tve-live-{cdn}.warnermediacdn.com/hls/live/{event_id}/{stream_name}/{path_variant}/master.m3u8"

    try:
        res = requests.get(
            url, headers=DEFAULT_HEADERS, timeout=3, stream=True
        )
        # 200/206 = Open live stream
        # 403 = Valid event ID exists, but requires Akamai hdnts token
        if res.status_code in (200, 206):
            return {
                "stream_name": stream_name,
                "cdn": cdn,
                "event_id": event_id,
                "url": url,
                "status": "LIVE",
            }
        elif res.status_code == 403:
            return {
                "stream_name": stream_name,
                "cdn": cdn,
                "event_id": event_id,
                "url": url,
                "status": "EXISTS_TOKEN_REQUIRED",
            }
    except Exception:
        pass
    return None


def run_background_scanner():
    while True:
        print("[Scanner] Starting sweep across WBD CDN matrix...")
        tasks = []
        for event_id in range(START_ID, END_ID + 1):
            for stream in STREAM_NAMES:
                for cdn in CDN_PROVIDERS:
                    for variant in PATH_VARIANTS:
                        tasks.append((cdn, stream, event_id, variant))

        results = []
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = executor.map(check_endpoint, tasks)
            for res in futures:
                if res:
                    results.append(res)

        # Save hits to database
        if results:
            conn = get_db_connection()
            cur = conn.cursor()
            for item in results:
                cur.execute(
                    """
                    INSERT INTO active_streams (stream_name, cdn_provider, event_id, url, status, last_checked)
                    VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(url) DO UPDATE SET
                        status = excluded.status,
                        last_checked = CURRENT_TIMESTAMP;
                """,
                    (
                        item["stream_name"],
                        item["cdn"],
                        item["event_id"],
                        item["url"],
                        item["status"],
                    ),
                )
            conn.commit()
            conn.close()
            print(
                f"[Scanner] Sweep complete. Found/updated {len(results)} active endpoints."
            )

        time.sleep(300)  # Re-scan every 5 minutes


# Initialize database and spin up background scanner thread
init_db()
scanner_thread = threading.Thread(target=run_background_scanner, daemon=True)
scanner_thread.start()


@app.route("/")
def generate_playlist():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT stream_name, url, status FROM active_streams;")
    rows = cur.fetchall()
    conn.close()

    m3u_content = "#EXTM3U\n"
    for row in rows:
        tag = " [TOKEN REQUIRED]" if row["status"] == "EXISTS_TOKEN_REQUIRED" else ""
        m3u_content += f'#EXTINF:-1 tvg-name="{row["stream_name"]}",{row["stream_name"].upper()}{tag}\n'
        m3u_content += f"{row['url']}\n"

    return Response(m3u_content, mimetype="audio/x-mpegurl")


@app.route("/status")
def status_check():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM active_streams;")
        total = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM active_streams WHERE status = 'LIVE';"
        )
        live = cur.fetchone()[0]
        cur.close()
        conn.close()
        return jsonify({"total_endpoints_found": total, "live_unlocked": live})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
