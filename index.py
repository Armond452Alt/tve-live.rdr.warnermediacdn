import concurrent.futures
import os
import requests
from flask import Flask, Response

app = Flask(__name__)

# Base parameters for Turner/WBD Akamai HLS endpoints
DOMAINS = [
    "turnerlive.warnermediacdn.com",
    "tve-live-ctl.warnermediacdn.com",
    "turnerlive.cdn.turner.com"
]

EVENT_IDS = range(2023175, 2026200)
SLATE_TYPES = ["noslate", "slate"]
PROFILES = [
    "VIDEO_1_5128000.m3u8",  # 1080p / High
    "VIDEO_0_3564000.m3u8",  # 720p / Mid
    "VIDEO_3_1928000.m3u8",  # 432p / Low
    "index.m3u8"            # Master playlist
]

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.adultswim.com/",
    "Origin": "https://www.adultswim.com"
}

def check_endpoint(url):
    headers = DEFAULT_HEADERS.copy()
    headers["Range"] = "bytes=0-512"
    try:
        response = requests.get(url, headers=headers, timeout=3, stream=True)
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_endpoint, url): url for url in candidates}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                working_feeds.append(result)
                
    return working_feeds

@app.route("/")
@app.route("/toonwest.m3u")
def generate_playlist():
    feeds = scan_toonwest_feeds()
    
    playlist_lines = ["#EXTM3U\n"]
    for idx, stream_url in enumerate(feeds, 1):
        playlist_lines.append(f'#EXTINF:-1 tvg-id="CartoonNetworkWest.us" tvg-name="CN West Feed {idx}",Cartoon Network West (Feed {idx})')
        playlist_lines.append(f"{stream_url}\n")
        
    playlist_content = "\n".join(playlist_lines)
    return Response(playlist_content, mimetype="audio/x-mpegurl")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
