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

# Credentials and Config
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
PROCESSED_FILE = "last_processed_video.txt"
AUDIO_PATH = "broadcast_episode.mp3"

SHOW_FEEDS = {
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
        "https://www.am950radio.com/category/podcasts/pm/feed/"
    ]
}

def get_recent_episodes():
    headers = {"User-Agent": "Mozilla/5.0"}
    episodes = []
    seen = set()

    for show, urls in SHOW_FEEDS.items():
        found = False
        print(f"\nChecking feed for: {show}", flush=True)
        for url in urls:
            try:
                r = requests.get(url, headers=headers, timeout=10)
                print(f"URL {url} -> Status {r.status_code}", flush=True)
                if r.status_code != 200:
                    continue
                root = ET.fromstring(r.content)
                items = root.findall(".//item")
                for item in items:
                    title_node = item.find("title")
                    title = title_node.text if title_node is not None else show
                    link_node = item.find("link")
                    link = link_node.text if link_node is not None else ""
                    desc_node = item.find("description")
                    desc = desc_node.text if desc_node is not None else ""

                    mp3 = None
                    enc = item.find("enclosure")
                    if enc is not None and "url" in enc.attrib:
                        mp3 = enc.attrib["url"]
                    if not mp3:
                        m = re.search(r'https?://[^\s"]+\.mp3', desc)
                        if m:
                            mp3 = m.group(0)

                    ep_id = link if link else title
                    if mp3 and ep_id not in seen:
                        seen.add(ep_id)
                        episodes.append({"id": ep_id, "title": title, "mp3": mp3})
                        print(f"Found latest episode: {title}", flush=True)
                        found = True
                        break
                if found:
                    break
            except Exception as e:
                print(f"Feed error {url}: {e}", flush=True)
        if not found:
            print(f"No active MP3 found for {show}", flush=True)

    print(f"\nTotal episodes ready to check: {len(episodes)}", flush=True)
    return episodes

def download_audio(url):
    print(f"Downloading MP3: {url}", flush=True)
    if os.path.exists(AUDIO_PATH):
        os.remove(AUDIO_PATH)
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, stream=True, timeout=90)
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

def generate_summary(title):
    client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=180000.0))
    today_str = datetime.datetime.now().strftime("%B %d, %Y")

    prompt = f"""You are an executive assistant to the Station Manager at AM950 KTNF in Minneapolis-St. Paul.
Today's Date: {today_str}
Broadcast: {title}

Analyze this attached audio broadcast. Base your memorandum STRICTLY on what was spoken on-air. Do NOT fabricate topics, callers, or races.

Format:
MEMORANDUM
TO: Station Manager, AM950 KTNF
FROM: Executive Assistant
DATE: {today_str}
BROADCAST: {title}

1. EXECUTIVE SUMMARY:
   - 3-4 dense sentences detailing key topics, news items, and broadcast flow.

2. COMPREHENSIVE SEGMENT BREAKDOWN:
   - Chronological summary of specific discussions, guests, policy arguments, and candidates cited.

3. GUESTS & CALLERS:
   - Named guests with their specific arguments.
   - Notable callers (name, location, topic). If none, state "Solo monologue; no callers."

4. SPONSORS & UNDERWRITING:
   - Businesses, unions, or organizations promoted.

5. REGULATORY & TONE FLAGS:
   - FCC or language issues. If clean, state "Clean - No compliance flags noted."
"""

    print("Uploading MP3 to Gemini...", flush=True)
    uploaded = client.files.upload(file=AUDIO_PATH)
    print("Generating summary...", flush=True)

    config = types.GenerateContentConfig(temperature=0.2, max_output_tokens=3000)
    for model in ["gemini-3.8-flash", "gemini-3.5-flash-lite"]:
        try:
            print(f"Calling {model}...", flush=True)
            res = client.models.generate_content(model=model, contents=[uploaded, prompt], config=config)
            if res and res.text:
                try:
                    client.files.delete(name=uploaded.name)
                except Exception:
                    pass
                return res.text
        except Exception as e:
            print(f"{model} error: {e}", flush=True)
            time.sleep(4)

    raise RuntimeError("All models failed to generate summary.")

def send_email(title, body, link):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECIPIENT
    msg['Subject'] = f"[AM950 Broadcast Summary] {title}"
    msg.attach(MIMEText(body + f"\n\n---\nEpisode Link: {link}", 'plain'))

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as s:
        s.login(EMAIL_SENDER, EMAIL_PASSWORD)
        s.send_message(msg)
    print("Email sent successfully!", flush=True)

def main():
    if not os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "w") as f:
            f.write("")

    with open(PROCESSED_FILE, "r") as f:
        done = set(line.strip() for line in f if line.strip())

    candidates = get_recent_episodes()
    pending = [ep for ep in candidates if ep["id"] not in done]

    if not pending:
        print("All target shows already processed. Exiting cleanly.", flush=True)
        return

    print(f"Found {len(pending)} new episode(s) to process.", flush=True)
    for ep in pending:
        print(f"\n--- Processing: {ep['title']} ---", flush=True)
        if download_audio(ep["mp3"]):
            try:
                summary = generate_summary(ep["title"])
                send_email(ep["title"], summary, ep["id"])
                with open(PROCESSED_FILE, "a") as f:
                    f.write(ep["id"] + "\n")
                print(f"Recorded ID: {ep['id']}", flush=True)
            except Exception as e:
                print(f"Processing error: {e}", flush=True)
            finally:
                if os.path.exists(AUDIO_PATH):
                    os.remove(AUDIO_PATH)
        time.sleep(3)

    print("\nBatch process complete.", flush=True)

if __name__ == "__main__":
    main()
