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
    )
}

def get_latest_stream():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        resp = requests.get(CHANNEL_URL, headers=headers, timeout=10)
        if resp.status_code == 200:
            vids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', resp.text)
            seen = set()
            unique_vids = [v for v in vids if not (v in seen or seen.add(v))]
            for vid in unique_vids:
                title, desc = fetch_video_details(vid)
                if title and len(title) > 5 and not any(term in title.lower() for term in ["keyboard shortcuts", "live now"]):
                    return vid, title, desc
    except Exception as e:
        print("Stream detection note:", e, flush=True)

    return "CPEGMSH1p8E", "Episode 120 of Politics Matters with Bruce Klopfleisch", "Recent broadcast from AM950 Radio Minnesota."

def fetch_video_details(video_id):
    title = ""
    desc = "Recent broadcast from AM950 Radio Minnesota."
    url = "https://www.youtube.com/watch?v=" + video_id
    try:
        oembed_url = "https://www.youtube.com/oembed?url=" + url + "&format=json"
        res = requests.get(oembed_url, timeout=8)
        if res.status_code == 200:
            title = res.json().get("title", "")
    except Exception:
        pass

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=8)
        desc_match = re.search(r'<meta name="description" content="(.*?)">', res.text)
        if desc_match:
            desc = desc_match.group(1).strip()
    except Exception:
        pass

    return title, desc

def fetch_transcript(video_id):
    """Pulls broadcast transcript safely, handling both class and instance methods."""
    print("Fetching broadcast transcript...", flush=True)
    transcript_list = None

    # Method 1: Direct fetch via class or instance
    try:
        if hasattr(YouTubeTranscriptApi, 'get_transcript'):
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        else:
            api_instance = YouTubeTranscriptApi()
            transcript_list = api_instance.get_transcript(video_id, languages=['en'])
    except Exception:
        pass

    # Method 2: Transcripts listing fallback (handles auto-generated captions)
    if not transcript_list:
        try:
            transcript_list_obj = YouTubeTranscriptApi.list_transcripts(video_id)
            try:
                transcript_obj = transcript_list_obj.find_transcript(['en'])
            except Exception:
                transcript_obj = transcript_list_obj.find_generated_transcript(['en'])
            transcript_list = transcript_obj.fetch()
        except Exception as e:
            print("Transcript unavailable or not generated yet:", e, flush=True)
            return None

    if transcript_list:
        formatted_lines = []
        for entry in transcript_list:
            minutes = int(entry['start'] // 60)
            seconds = int(entry['start'] % 60)
            formatted_lines.append(f"[{minutes:02d}:{seconds:02d}] {entry['text']}")
        full_text = "\n".join(formatted_lines)
        print("Transcript pulled:", len(full_text), "characters", flush=True)
        return full_text

    return None

def identify_focus(title):
    for key in SHOW_PROMPTS:
        if re.search(key, title, re.IGNORECASE):
            return SHOW_PROMPTS[key]
    return "Focus on: Detailed policy arguments, exact guest statements, caller discussions, and local news."

def generate_summary(video_url, title, description, transcript_text):
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=50000.0)
    )
    focus_guidance = identify_focus(title)
    today_str = datetime.datetime.now().strftime("%B %d, %Y")

    if transcript_text:
        source_data = "FULL BROADCAST TRANSCRIPT (with timestamps):\n" + transcript_text[:50000]
    else:
        source_data = "BROADCAST DESCRIPTION & METADATA:\n" + description

    prompt = f"""You are an executive assistant to the Station Manager at AM950 Radio (KTNF) in Minneapolis-St. Paul.
Today's Date: {today_str}

Analyze this AM950 broadcast:
Show Title: {title}
URL: {video_url}

Show Directives:
{focus_guidance}

{source_data}

Write a comprehensive, granular executive station memorandum. Avoid vague generalizations; name specific individuals, exact policy/bill numbers, explicit arguments made by callers or hosts, and specific station sponsors.

Format the memorandum as follows:

MEMORANDUM
TO: Station Manager, AM950 KTNF
FROM: Executive Assistant
DATE: {today_str}
BROADCAST: {title}

1. EXECUTIVE SUMMARY:
   - Provide 3-4 dense sentences detailing the core news items, policy positions taken, caller dynamics, and overall broadcast quality.

2. COMPREHENSIVE SEGMENT BREAKDOWN:
   - Chronological breakdown of each topic discussed with approximate timestamps (e.g., [12:30]).
   - For each topic, detail: the core conflict or argument, specific local/state context, and notable claims or statistics cited.

3. GUESTS, INTERVIEWS & CALLERS:
   - Identify every named guest, their organization/title, and 2-3 direct bullet points summarizing their key arguments and direct quotes.
   - Summarize notable listener call-ins: caller name/location, topic raised, and host's response.

4. SPONSORS, UNDERWRITING & STATION PROMOTIONS:
   - List every business, non-profit, union, or community sponsor explicitly mentioned or thanked during breaks.
   - Note any station events, pledge drives, or upcoming AM950 show promos mentioned.

5. REGULATORY, COMPLIANCE & TONE FLAGS:
   - Check for broadcast decency, FCC language concerns, unverified personal attacks, or contentious exchanges. If clean, state "Clean - No compliance flags noted."
"""

    gen_config = types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=3500
    )

    candidate_models = ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-2.5-pro"]

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
                print(f"{model_name} error on attempt {attempt}: {e}", flush=True)
                time.sleep(4)

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
        processed_ids = set(line.strip() for line in f.readlines())

    video_id, title, desc = get_latest_stream()
    if not video_id:
        print("No stream found. Exiting.", flush=True)
        return

    if video_id in processed_ids:
        print("Video already processed:", video_id, flush=True)
        return

    video_url = "https://www.youtube.com/watch?v=" + video_id
    print("Processing show:", title, "(" + video_url + ")", flush=True)

    transcript_text = fetch_transcript(video_id)
    summary = generate_summary(video_url, title, desc, transcript_text)
    send_email("[AM950 Broadcast Summary] " + title, summary, video_url)

    with open(PROCESSED_FILE, "a") as f:
        f.write(video_id + "\n")
    print("Process complete.", flush=True)

if __name__ == "__main__":
    main()
