import concurrent.futures
import threading
import time
import requests
from flask import Flask, Response

app = Flask(__name__)

DOMAINS = [
    "turnerlive.warnermediacdn.com",
    "tve-live-ctl.warnermediacdn.com",
    "turnerlive.cdn.turner.com"
]

EVENT_IDS = range(2023175, 2024200)
SLATE_TYPES = ["noslate", "slate"]
PROFILES = [
    "VIDEO_1_5128000.m3u8",
    "VIDEO_0_3564000.m3u8",
    "VIDEO_3_1928000.m3u8",
    "index.m3u8"
]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.adultswim.com/",
    "Origin": "https://www.adultswim.com"
}

# Shared cache and lock
cached_feeds = []
cache_lock = threading.Lock()

def check_endpoint(url):
    headers = DEFAULT_HEADERS.copy()
    headers["Range"] = "bytes=0-512"
    try:
        response = requests.get(url, headers=headers, timeout=2, stream=True)
        chunk = next(response.iter_content(chunk_size=512), b"")
        if response.status_code in (200, 206) and (b"#EXTM3U" in chunk or b"#EXTINF" in chunk):
            return url
    except Exception:
        pass
    return None

def scan_toonwest_feeds():
    candidates = []
    for domain in DOMAINS:
        for event_id in EVENT_IDS:
            for slate in SLATE_TYPES:
                for profile in PROFILES:
                    candidates.append(f"https://{domain}/hls/live/{event_id}/toonwest/{slate}/{profile}")
                    
    working_feeds = []
    # Using 50 workers to speed up loop completion
    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(check_endpoint, url): url for url in candidates}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                working_feeds.append(result)
                
    return working_feeds

def background_scanner():
    global cached_feeds
    while True:
        results = scan_toonwest_feeds()
        with cache_lock:
            cached_feeds = results
        # Re-scan every 10 minutes (600 seconds)
        time.sleep(600)

# Start background scanner thread on startup
scanner_thread = threading.Thread(target=background_scanner, daemon=True)
scanner_thread.start()

@app.route("/")
@app.route("/toonwest.m3u")
@app.route("/playlist.m3u")
def generate_playlist():
    with cache_lock:
        feeds = list(cached_feeds)
    
    playlist_lines = ["#EXTM3U\n"]
    for idx, stream_url in enumerate(feeds, 1):
        playlist_lines.append(f'#EXTINF:-1 tvg-id="CartoonNetworkWest.us" tvg-name="CN West Feed {idx}",Cartoon Network West (Feed {idx})')
        playlist_lines.append(f"{stream_url}\n")
        
    playlist_content = "\n".join(playlist_lines)
    return Response(playlist_content, mimetype="audio/x-mpegurl")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
