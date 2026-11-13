import os
import re
import json
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

# Credentials and Config
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
PROCESSED_FILE = "last_processed_video.txt"
HISTORY_FILE = "episode_history.json"
AUDIO_PATH = "broadcast_episode.mp3"

SHOW_FEEDS = {
    "The Matt McNeil Show": [
        "https://www.am950radio.com/category/the-matt-mcneil-show/feed/",
        "https://www.am950radio.com/category/podcasts/mcneil/feed/",
        "https://www.am950radio.com/category/matt-mcneil/feed/",
        "https://www.am950radio.com/category/mcneil/feed/"
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
        "https://www.am950radio.com/category/podcasts/pm/feed/"
    ]
}

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def clean_html(raw_html):
    if not raw_html:
        return ""
    text = re.sub(r'<[^>]+>', ' ', raw_html)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_show_notes(item):
    parts = []
    for child in item:
        tag = child.tag.lower()
        if tag.endswith("description") or tag.endswith("encoded") or tag.endswith("summary"):
            if child.text:
                cleaned = clean_html(child.text)
                if cleaned and cleaned not in parts:
                    parts.append(cleaned)
    return "\n".join(parts).strip()

def extract_mp3_from_text(text):
    if not text:
        return None
    patterns = [
        r'https?://[^\s"\'<>]+\.mp3(?:\?[^\s"\'<>]*)?',
        r'https?://media\.blubrry\.com/[^\s"\'<>]+',
        r'https?://feeds\.soundcloud\.com/stream/[^\s"\'<>]+'
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0)
    return None

def extract_mp3_from_item(item, link=""):
    enc = item.find("enclosure")
    if enc is not None and "url" in enc.attrib:
        return enc.attrib["url"]

    raw_xml = ET.tostring(item, encoding="unicode")
    mp3 = extract_mp3_from_text(raw_xml)
    if mp3:
        return mp3

    if link and link.startswith("http"):
        try:
            r = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if r.status_code == 200:
                mp3 = extract_mp3_from_text(r.text)
                if mp3:
                    print(f"Extracted audio URL from episode page: {mp3}", flush=True)
                    return mp3
        except Exception as e:
            print(f"Page scrape fallback error for {link}: {e}", flush=True)

    return None

def item_matches_show(item, keyword):
    title_node = item.find("title")
    title = title_node.text if (title_node is not None and title_node.text) else ""
    if re.search(keyword, title, re.IGNORECASE):
        return True
    for cat in item.findall("category"):
        if cat.text and re.search(keyword, cat.text, re.IGNORECASE):
            return True
    desc = extract_show_notes(item)
    if re.search(keyword, desc, re.IGNORECASE):
        return True
    return False

def get_recent_episodes():
    headers = {"User-Agent": "Mozilla/5.0"}
    episodes = []
    seen = set()

    for show, urls in SHOW_FEEDS.items():
        found = False
        print(f"\nChecking feed for: {show}", flush=True)
        for url in urls:
            for net_try in range(2):
                try:
                    r = requests.get(url, headers=headers, timeout=15)
                    print(f"URL {url} -> Status {r.status_code}", flush=True)
                    if r.status_code != 200:
                        break
                    root = ET.fromstring(r.content)
                    items = root.findall(".//item")
                    print(f"  Items in feed: {len(items)}", flush=True)
                    for item in items:
                        title_node = item.find("title")
                        title = title_node.text.strip() if (title_node is not None and title_node.text) else show
                        link_node = item.find("link")
                        link = link_node.text.strip() if (link_node is not None and link_node.text) else ""

                        mp3 = extract_mp3_from_item(item, link)
                        ep_id = link if link else title
                        if mp3 and ep_id not in seen:
                            seen.add(ep_id)
                            notes = extract_show_notes(item)
                            episodes.append({
                                "id": ep_id,
                                "show": show,
                                "title": title,
                                "mp3": mp3,
                                "notes": notes
                            })
                            print(f"Found latest episode: {title}", flush=True)
                            found = True
                            break
                    break
                except Exception as e:
                    print(f"Feed attempt {net_try+1} error {url}: {e}", flush=True)
                    time.sleep(3)
            if found:
                break

        if not found:
            keyword = "McNeil" if "McNeil" in show else show.split()[0]
            try:
                r = requests.get("https://www.am950radio.com/category/podcasts/feed/", headers=headers, timeout=15)
                print(f"Master feed fallback for {show} (keyword: {keyword}) -> Status {r.status_code}", flush=True)
                if r.status_code == 200:
                    root = ET.fromstring(r.content)
                    for item in root.findall(".//item"):
                        if item_matches_show(item, keyword):
                            title_node = item.find("title")
                            title = title_node.text.strip() if (title_node is not None and title_node.text) else show
                            link_node = item.find("link")
                            link = link_node.text.strip() if (link_node is not None and link_node.text) else title
                            mp3 = extract_mp3_from_item(item, link)
                            if mp3 and link not in seen:
                                seen.add(link)
                                notes = extract_show_notes(item)
                                episodes.append({
                                    "id": link,
                                    "show": show,
                                    "title": title,
                                    "mp3": mp3,
                                    "notes": notes
                                })
                                print(f"Found via master feed: {title}", flush=True)
                                found = True
                                break
            except Exception as e:
                print(f"Master feed fallback error: {e}", flush=True)

        if not found:
            print(f"No active MP3 found for {show}", flush=True)

    print(f"\nTotal episodes ready to check: {len(episodes)}", flush=True)
    return episodes

def download_audio(url):
    print(f"Downloading MP3: {url}", flush=True)
    if os.path.exists(AUDIO_PATH):
        os.remove(AUDIO_PATH)
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, stream=True, timeout=120)
        r.raise_for_status()
        with open(AUDIO_PATH, "wb") as f:
            for chunk in r.iter_content(chunk_size=1048576):
                if chunk:
                    f.write(chunk)
        if os.path.exists(AUDIO_PATH):
            size_mb = os.path.getsize(AUDIO_PATH) / 1048576
            print(f"Audio downloaded: {size_mb:.2f} MB", flush=True)
            return True
    except Exception as e:
        print(f"Download failed: {e}", flush=True)
    return False

def generate_summary(show_name, title, notes, past_episodes):
    client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=300000.0))
    today_str = datetime.datetime.now().strftime("%B %d, %Y")

    if past_episodes:
        history_context = "RECENT PREVIOUS EPISODES AND TOPICS COVERED:\n"
        for p in past_episodes[-6:]:
            history_context += f"- Date: {p.get('date', 'Recent')}, Episode: {p.get('title', '')}\n  Topics: {p.get('topics', 'N/A')}\n"
    else:
        history_context = "No previous episode topic history recorded yet for this show."

    notes_block = notes if notes else "No text show notes provided in RSS feed; rely strictly on the spoken audio."

    prompt = f"""You are the Executive Station & Editorial Director at AM950 Radio (KTNF) in Minneapolis-St. Paul, AND the Lead Digital Strategist / SEO Social Copy Expert for Heartland Signal.
Today's Date: {today_str}
Show Name: {show_name}
Episode Title: {title}

OFFICIAL PODCAST EPISODE NOTES (GROUND TRUTH METADATA):
{notes_block}

{history_context}

CRITICAL TIMESTAMP & ANTI-HALLUCINATION RULES:
1. Listen to the ENTIRE attached audio file starting from 00:00 — pay close attention to the exact second/minute when the intro music ends and the first topic or guest interview begins (often around 00:30 to 02:00).
2. NEVER round timestamps to arbitrary 5-minute blocks (such as "00:00 – 05:00") and NEVER invent generic filler summaries (such as "Host opens the show welcoming listeners and setting the stage for discussions"). State the exact [MM:SS] timestamp when each segment or guest actually starts speaking.
