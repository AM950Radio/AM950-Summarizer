import os
import re
import time
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import subprocess
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
CHANNEL_URL = "https://www.youtube.com/@AM950Radio/streams"
AUDIO_PATH = "broadcast_audio.mp3"
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
    return title, desc

def download_audio(video_url):
    """Downloads audio using yt-dlp with the android client emulator to bypass bot checks."""
    print("Downloading broadcast audio via yt-dlp...", flush=True)
    if os.path.exists(AUDIO_PATH):
        os.remove(AUDIO_PATH)

    cmd = [
        "yt-dlp",
        "--extractor-args", "youtube:player_client=android,web",
        "-f", "ba/b",
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "9",
        "--no-check-certificates",
        "-o", AUDIO_PATH,
        video_url
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if os.path.exists(AUDIO_PATH):
            size_mb = os.path.getsize(AUDIO_PATH) / (1024 * 1024)
            print(f"Audio downloaded: {size_mb:.2f} MB", flush=True)
            return True
    except subprocess.CalledProcessError as e:
        print("yt-dlp error output:", e.stderr[:300] if e.stderr else e, flush=True)
    except Exception as e:
        print("Audio download error:", e, flush=True)

    return False

def identify_focus(title):
    for key in SHOW_PROMPTS:
        if re.search(key, title, re.IGNORECASE):
            return SHOW_PROMPTS[key]
    return "Focus on: Detailed policy arguments, exact election analysis, guest statements, caller discussions, and local news."

def generate_summary(video_url, title, description, audio_available):
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=120000.0)
    )
    focus_guidance = identify_focus(title)
    today_str = datetime.datetime.now().strftime("%B %d, %Y")

    prompt = f"""You are an executive assistant to the Station Manager at AM950 Radio (KTNF) in Minneapolis-St. Paul.
Today's Date: {today_str}

Analyze this AM950 broadcast:
Show Title: {title}
URL: {video_url}

Show Directives:
{focus_guidance}

Listen carefully to the actual attached broadcast audio. Detail the true topics, races, election results, candidates, and arguments discussed on air. Do not extrapolate, hallucinate, or invent topics.

Format the memorandum as follows:

MEMORANDUM
TO: Station Manager, AM950 KTNF
FROM: Executive Assistant
DATE: {today_str}
BROADCAST: {title}

1. EXECUTIVE SUMMARY:
   - Provide 3-4 dense sentences detailing the actual lead news items, election results, guest arguments, and overall broadcast quality.

2. COMPREHENSIVE SEGMENT BREAKDOWN:
   - Chronological breakdown of each topic discussed with approximate timestamps.
   - Detail the core argument, specific candidate/ballot races, local/state context, and notable claims cited.

3. GUESTS, INTERVIEWS & CALLERS:
   - Identify every named guest and direct bullet points summarizing their key arguments.
   - Summarize notable listener call-ins if present: caller name/location, topic raised, and host's response.

4. SPONSORS, UNDERWRITING & STATION PROMOTIONS:
   - List every business, union, or sponsor explicitly mentioned during breaks.
   - Note any station events or upcoming AM950 show promos mentioned.

5. REGULATORY, COMPLIANCE & TONE FLAGS:
   - Check for broadcast decency, FCC language concerns, unverified personal attacks, or contentious exchanges. If clean, state "Clean - No compliance flags noted."
"""

    contents = []
    uploaded_file = None

    if audio_available and os.path.exists(AUDIO_PATH):
        print("Uploading audio to Gemini File API...", flush=True)
        uploaded_file = client.files.upload(file=AUDIO_PATH)
        print("Audio uploaded. Waiting for processing...", flush=True)
        time.sleep(3)
        contents = [uploaded_file, prompt]
    else:
        print("Audio unavailable, falling back to show metadata...", flush=True)
        contents = [prompt + f"\n\nShow Description: {description}"]

    gen_config = types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=3500
    )

    candidate_models = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]

    for model_name in candidate_models:
        for attempt in range(1, 3):
            print(f"Requesting summary from {model_name} (attempt {attempt}/2)...", flush=True)
            try:
                response_stream = client.models.generate_content_stream(
                    model=model_name,
                    contents=contents,
                    config=gen_config
                )
                chunks = []
                for chunk in response_stream:
                    if chunk.text:
                        chunks.append(chunk.text)
                
                full_text = "".join(chunks)
                if len(full_text.strip()) > 50:
                    print(f"Summary successfully generated via {model_name}!", flush=True)
                    if uploaded_file:
                        try:
                            client.files.delete(name=uploaded_file.name)
                        except Exception:
                            pass
                    return full_text
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

    audio_downloaded = download_audio(video_url)
    summary = generate_summary(video_url, title, desc, audio_downloaded)
    send_email("[AM950 Broadcast Summary] " + title, summary, video_url)

    if os.path.exists(AUDIO_PATH):
        os.remove(AUDIO_PATH)

    with open(PROCESSED_FILE, "a") as f:
        f.write(video_id + "\n")
    print("Process complete.", flush=True)

if __name__ == "__main__":
    main()
