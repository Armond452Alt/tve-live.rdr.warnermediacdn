import concurrent.futures
import os
import requests

# Base parameters for Turner/WBD Akamai HLS endpoints
DOMAINS = [
    "turnerlive.warnermediacdn.com",
    "tve-live-ctl.warnermediacdn.com",
    "turnerlive.cdn.turner.com"
]

# Event ID / CP code range around known Turner allocations
EVENT_IDS = range(2023175, 2024200)

SLATE_TYPES = ["noslate", "slate"]

# Standard profile filenames for Turner HLS streams
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

OUTPUT_PLAYLIST = os.path.expanduser("~/toonwest_active.m3u")

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
    
    # Generate candidate URLs across combinations
    for domain in DOMAINS:
        for event_id in EVENT_IDS:
            for slate in SLATE_TYPES:
                for profile in PROFILES:
                    url = f"https://{domain}/hls/live/{event_id}/toonwest/{slate}/{profile}"
                    candidates.append(url)
                    
    print(f"Generated {len(candidates)} candidate URLs. Scanning with thread pool...")
    
    working_feeds = []
    # Use multi-threading to check hundreds of combinations in seconds
    with concurrent.futures.ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(check_endpoint, url): url for url in candidates}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                print(f"  [LIVE FOUND] {result}")
                working_feeds.append(result)
                
    print(f"\nScan complete. Found {len(working_feeds)} active stream(s).")
    
    if working_feeds:
        with open(OUTPUT_PLAYLIST, "w", encoding="utf-8") as f:
            f.write("#EXTM3U\n\n")
            for idx, stream_url in enumerate(working_feeds, 1):
                f.write(f'#EXTINF:-1 tvg-id="CartoonNetworkWest.us" tvg-name="CN West Feed {idx}",Cartoon Network West (Feed {idx})\n')
                f.write(f"{stream_url}\n\n")
        print(f"Saved active endpoints to '{OUTPUT_PLAYLIST}'")

if __name__ == "__main__":
    scan_toonwest_feeds()
