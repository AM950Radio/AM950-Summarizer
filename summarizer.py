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
            file_bytes = os.path.getsize(AUDIO_PATH)
            mb_val = file_bytes / (1024 * 1024)
            print(f"Audio downloaded: {mb_val:.2f} MB", flush=True)
            return True
    except Exception as e:
        print(f"Audio download failed: {e}", flush=True)

    return False

def identify_focus(title):
    for key in SHOW_PROMPTS:
        if re.search(key, title, re.IGNORECASE):
            return SHOW_PROMPTS[key]
    return "Focus on: Detailed policy arguments, exact guest statements, caller discussions, and local news."

def generate_summary(title, description, audio_available):
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=180000.0)
    )
    focus_guidance = identify_focus(title)
    today_str = datetime.datetime.now().strftime("%B %d, %Y")

    prompt = f"""You are an executive assistant to the Station Manager at AM950 Radio (KTNF) in Minneapolis-St. Paul.
Today's Date: {today_str}

Analyze this AM950 broadcast:
Show Title: {title}

Show Directives:
{focus_guidance}

INSTRUCTIONS:
Listen carefully to the broadcast audio attached. Produce a detailed executive memo summarizing ONLY what was actually spoken on air: the real topics, specific election results, candidate names, races, arguments, and commentary.
Do NOT invent topics, do NOT fabricate callers, and do NOT extrapolate beyond what was actually said.

Format the memorandum as follows:

MEMORANDUM
TO: Station Manager, AM950 KTNF
FROM: Executive Assistant
DATE: {today_str}
BROADCAST: {title}

1. EXECUTIVE SUMMARY:
   - Provide 3-4 dense sentences detailing the actual lead news items, election results, guest arguments, and overall broadcast quality.

2. COMPREHENSIVE SEGMENT BREAKDOWN:
   - Chronological breakdown of each topic discussed.
   - Detail the core argument, specific candidate/ballot races, local/state context, and notable claims cited.

3. GUESTS, INTERVIEWS & CALLERS:
   - Identify every named guest and direct bullet points summarizing their key arguments and direct quotes.
   - Summarize notable listener call-ins if present: caller name/location, topic raised, and host's response. If no guests or callers, state: "Solo monologue by host; no guest appearances or caller segments."

4. SPONSORS, UNDERWRITING & STATION PROMOTIONS:
   - List every business, non-profit, union, or sponsor explicitly thanked or promoted.
   - Note any station events or upcoming AM950 show promos mentioned.

5. REGULATORY, COMPLIANCE & TONE FLAGS:
   - Check for broadcast decency, FCC language concerns, unverified personal attacks, or contentious exchanges. If clean, state "Clean - No compliance flags noted."
"""

    uploaded_file = None
    if audio_available and os.path.exists(AUDIO_PATH):
        print("Uploading audio to Gemini File API...", flush=True)
        uploaded_file = client.files.upload(file=AUDIO_PATH)
        print("Audio uploaded. Processing summary...", flush=True)
        contents = [uploaded_file, prompt]
    else:
        print("Audio missing. Using metadata only...", flush=True)
        contents = [prompt + f"\n\nShow Description: {description}"]

    gen_config = types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=3000
    )

    candidate_models = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]

    for model_name in candidate_models:
        for attempt in range(
