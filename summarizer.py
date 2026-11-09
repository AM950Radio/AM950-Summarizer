import os
import re
import time
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from youtube_transcript_api import YouTubeTranscriptApi
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
CHANNEL_URL = "https://www.youtube.com/@AM950Radio/streams"
MAX_RECENT_VIDEOS = 10
# =================================================

SHOW_PROMPTS = {
    "Gaily": (
        "Focus on: Specific LGBTQ+ legislation, local Twin Cities community organizers, "
        "trans/queer rights initiatives, upcoming rallies, cultural events, and direct caller quotes."
    ),
    "McNeil": (
        "Focus on: Specific named Minnesota state legislators/officials, contentious caller debates, "
        "local and national policy bills, host opinions, and broadcast rhetoric."
    ),
    "Native Roots": (
        "Focus on: Specific tribal governments, treaty rights, pipeline/water/land defense cases, "
        "indigenous community leaders, cultural preservation, and state/federal policy actions."
    ),
    "Politics Matters": (
        "Focus on: Minnesota legislative priorities, election post-mortems, state budget impacts, "
        "progressive public-affairs analysis, and detailed guest arguments."
    )
}

def get_recent_streams(limit=MAX_RECENT_VIDEOS):
    """Scrapes the AM950 streams page to find up to `limit` unique recent stream IDs."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    videos = []
    try:
        resp = requests.get(CHANNEL_URL, headers=headers, timeout=15)
        if resp.status_code == 200:
            vids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
            seen = set()
            for vid in vids:
                if vid not in seen:
                    seen.add(vid)
                    videos.append(vid)
                if len(videos) >= limit:
                    break
    except Exception as e:
        print("Stream scraping warning:", e, flush=True)

    if not videos:
        # Fallback to test ID if scraping returns empty
        videos = ["CPEGMSH1p8E"]

    print(f"Discovered {len(videos)} recent stream candidate(s): {videos}", flush=True)
    return videos

def fetch_video_details(video_id):
    """Fetches video title using YouTube oEmbed."""
    title = f"AM950 Broadcast ({video_id})"
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
        res = requests.get(oembed_url, timeout=8)
        if res.status_code == 200:
            title = res.json().get("title", title)
    except Exception:
        pass
    return title

def fetch_transcript(video_id):
    """Retrieves full spoken transcript using YouTubeTranscriptApi."""
    print(f"Checking transcript for video {video_id}...", flush=True)
    raw_entries = None

    try:
        if hasattr(YouTubeTranscriptApi, 'get_transcript'):
            raw_entries = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        else:
            api_instance = YouTubeTranscriptApi()
            raw_entries = api_instance.get_transcript(video_id, languages=['en'])
    except Exception:
        pass

    if not raw_entries:
        try:
            transcript_list_obj = YouTubeTranscriptApi.list_transcripts(video_id)
            try:
                transcript_obj = transcript_list_obj.find_transcript(['en'])
            except Exception:
                transcript_obj = transcript_list_obj.find_generated_transcript(['en'])
            raw_entries = transcript_obj.fetch()
        except Exception as e:
            print(f"Transcript unavailable for {video_id}: {e}", flush=True)
            return None

    if raw_entries:
        formatted = []
        for item in raw_entries:
            start_sec = int(float(item.get('start', 0)))
            minutes = start_sec // 60
            seconds = start_sec % 60
            text = str(item.get('text', '')).strip()
            if text:
                formatted.append(f"[{minutes:02d}:{seconds:02d}] {text}")
        full_text = "\n".join(formatted)
        print(f"Transcript loaded for {video_id} ({len(full_text)} characters)", flush=True)
        return full_text

    return None

def identify_focus(title):
    for key in SHOW_PROMPTS:
        if re.search(key, title, re.IGNORECASE):
            return SHOW_PROMPTS[key]
    return "Focus on: Detailed policy arguments, exact guest statements, caller discussions, and local news."

def generate_summary(video_url, title, transcript_text):
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=90000.0)
    )
    focus_guidance = identify_focus(title)
    today_str = datetime.datetime.now().strftime("%B %d, %Y")

    prompt = f"""You are an executive assistant to the Station Manager at AM950 Radio (KTNF) in Minneapolis-St. Paul.
Today's Date: {today_str}

Analyze this AM950 broadcast from its official word-for-word transcript:
Show Title: {title}
URL: {video_url}

Show Directives:
{focus_guidance}

FULL BROADCAST TRANSCRIPT (with timestamps):
{transcript_text[:40000]}

Write a comprehensive, granular executive station memorandum based strictly on the spoken words above. Do not speculate, invent, or extrapolate.

Format the memorandum as follows:

MEMORANDUM
TO: Station Manager, AM950 KTNF
FROM: Executive Assistant
DATE: {today_str}
BROADCAST: {title}

1. EXECUTIVE SUMMARY:
   - Provide 3-4 dense sentences detailing the actual lead news items, specific policy debates, caller dynamics, and overall broadcast quality.

2. COMPREHENSIVE SEGMENT BREAKDOWN:
   - Chronological breakdown of each topic discussed with approximate timestamps (e.g., [12:30]).
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

    gen_config = types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=3000
    )

    candidate_models = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]

    for model_name in candidate_models:
        for attempt in range(1, 3):
            print(f"Requesting summary from {model_name} (attempt {attempt}/2)...", flush=True)
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=gen_config
                )
                if response and response.text:
                    print(f"Summary successfully generated via {model_name}!", flush=True)
                    return response.text
            except Exception as e:
                print(f"{model_name} attempt {attempt} error: {e}", flush=True)
                time.sleep(5)

    raise RuntimeError("All candidate models failed to generate content.")

def send_email(subject, body, video_url):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECIPIENT
    msg['Subject'] = subject

    content = body + "\n\n---\nBroadcast Link: " + video_url
    msg.attach(MIMEText(content, 'plain'))

    print("Connecting to Gmail SMTP via SSL on port 465...", flush=True)
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
    print("Email sent successfully!", flush=True)

def main():
    if not os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "w") as f:
            f.write("")

    with open(PROCESSED_FILE, "r") as f:
        processed_ids = set(line.strip() for line in f.readlines() if line.strip())

    candidates = get_recent_streams(limit=MAX_RECENT_VIDEOS)
    unprocessed = [vid for vid in candidates if vid not in processed_ids]

    if not unprocessed:
        print("All recent streams have already been processed. Exiting cleanly.", flush=True)
        return

    print(f"Found {len(unprocessed)} stream(s) to process.", flush=True)

    for vid in unprocessed:
        title = fetch_video_details(vid)
        video_url = f"https://www.youtube.com/watch?v={vid}"
        print(f"\nEvaluating: {title} ({vid})", flush=True)

        transcript = fetch_transcript(vid)
        if not transcript:
            print(f"Skipping {vid} for now (transcript not generated yet). Will re-check on next run.", flush=True)
            continue

        try:
            summary = generate_summary(video_url, title, transcript)
            send_email(f"[AM950 Broadcast Summary] {title}", summary, video_url)

            # Record success immediately so re-runs won't duplicate
            with open(PROCESSED_FILE, "a") as f:
                f.write(vid + "\n")
            print(f"Successfully processed and recorded: {vid}", flush=True)
            time.sleep(3)
        except Exception as e:
            print(f"Failed to process video {vid}: {e}", flush=True)

    print("\nBatch process complete.", flush=True)

if __name__ == "__main__":
    main()
