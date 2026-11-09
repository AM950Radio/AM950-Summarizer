import os
import re
import time
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET
import requests
from google import genai
from google.genai import types

print("--- Script Starting ---", flush=True)

# ================= Configuration =================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
PROCESSED_FILE = "last_processed_video.txt"
AUDIO_PATH = "broadcast_episode.mp3"

# Confirmed AM950 podcast category slugs
SHOW_FEED_CANDIDATES = {
    "The Matt McNeil Show": [
        "https://www.am950radio.com/category/the-matt-mcneil-show/feed/",
        "https://www.am950radio.com/category/matt-mcneil/feed/",
        "https://www.am950radio.com/category/podcasts/mcneil/feed/"
    ],
    "Native Roots Radio": [
        "https://www.am950radio.com/category/podcasts/im-awake/feed/",
        "https://www.am950radio.com/category/im-awake/feed/",
        "https://www.am950radio.com/category/native-roots-radio/feed/"
    ],
    "The Gaily Show": [
        "https://www.am950radio.com/category/podcasts/gaily/feed/",
        "https://www.am950radio.com/category/gaily/feed/",
        "https://www.am950radio.com/category/the-gaily-show/feed/"
    ],
    "Politics Matters": [
        "https://www.am950radio.com/category/podcasts/pm/feed/",
        "https://www.am950radio.com/category/politics-matters/feed/"
    ]
}
# =================================================

SHOW_PROMPTS = {
    "Politics Matters": (
        "Focus on: Minnesota legislative priorities, election post-mortems, state budget impacts, "
        "progressive public-affairs analysis, and detailed guest arguments."
    ),
    "McNeil": (
        "Focus on: Specific named Minnesota state legislators/officials, contentious caller debates, "
        "local and national policy bills, host opinions, and broadcast rhetoric."
    ),
    "Native Roots": (
        "Focus on: Specific tribal governments, treaty rights, pipeline/water/land defense cases, "
        "indigenous community leaders, cultural preservation, and state/federal policy actions."
    ),
    "Gaily": (
        "Focus on: Specific LGBTQ+ legislation, local Twin Cities community organizers, "
        "trans/queer rights initiatives, upcoming rallies, cultural events, and direct caller quotes."
    )
}

def get_recent_episodes():
    """Fetches the latest single episode per targeted show using multi-slug resolution."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    episodes = []
    seen_ids = set()

    for show_name, candidate_urls in SHOW_FEED_CANDIDATES.items():
        found = False
        print(f"\n--- Checking for {show_name} ---", flush=True)

        for feed_url in candidate_urls:
            try:
                resp = requests.get(feed_url, headers=headers, timeout=12)
                print(f"Testing URL: {feed_url} -> Status {resp.status_code}", flush=True)
                if resp.status_code != 200:
                    continue

                root = ET.fromstring(resp.content)
                items = root.findall(".//item")
                print(f"Found {len(items)} items in feed.", flush=True)

                for item in items:
                    title_elem = item.find("title")
                    title = title_elem.text if title_elem is not None else show_name
                    
                    link_elem = item.find("link")
                    link = link_elem.text if link_elem is not None else ""
                    
                    desc_elem = item.find("description")
                    desc = desc_elem.text if desc_elem is not None else ""
                    clean_desc = re.sub(r'<[^>]+>', '', desc).strip()

                    # Locate direct audio enclosure
                    mp3_url = None
                    enclosure = item.find("enclosure")
                    if enclosure is not None and "url" in enclosure.attrib:
                        mp3_url = enclosure.attrib["url"]

                    if not mp3_url:
                        mp3_match = re.search(r'https?://[^\s"]+\.mp3', desc)
                        if mp3_match:
                            mp3_url = mp3_match.group(0)

                    ep_id = link if link else title

                    if mp3_url and (ep_id not in seen_ids):
                        seen_ids.add(ep_id)
                        episodes.append({
                            "id": ep_id,
                            "title": title,
                            "desc": clean_desc,
                            "mp3_url": mp3_url
                        })
                        print(f"Identified latest episode for {show_name}: {title}", flush=True)
                        found = True
                        break

                if found:
                    break
            except Exception as e:
                print(f"Error parsing {feed_url}: {e}", flush=True)

        if not found:
            print(f"No valid MP3 episodes found for {show_name} across candidate URLs.", flush=True)

    print(f"\nTotal target episodes queued: {len(episodes)}", flush=True)
    return episodes

def download_audio(mp3_url):
    """Downloads audio directly from the station/host CDN."""
    print(f"Downloading MP3 from {mp3_url}...", flush=True)
    if os.path.exists(AUDIO_PATH):
        os.remove(AUDIO_PATH)

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        with requests.get(mp3_url, headers=headers, stream=True, timeout=90) as r:
            r.raise_for_status()
            with open(AUDIO_PATH, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)

        if os.path.exists(AUDIO_PATH):
            size_
