import os
import re
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
import yt_dlp
from google import genai

# ================= Configuration =================
STREAMS_URL = "https://www.youtube.com/@AM950Radio/streams"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT")
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))

PROCESSED_FILE = "last_processed_video.txt"
# =================================================

SHOW_PROMPTS = {
    "Gaily": (
        "Focus specifically on: LGBTQ+ legislative and community topics, local MN cultural events, "
        "personal perspectives, community support resources, and guest commentary."
    ),
    "McNeil": (
        "Focus specifically on: Minnesota state and national political updates, interviews with elected officials "
        "or candidates, key caller arguments/debates, and any broadcast tone or potential FCC flags."
    ),
    "Native Roots": (
        "Focus specifically on: Tribal sovereignty, Indian affairs, environmental/land/water rights, "
        "cultural preservation, and featured indigenous leaders and activists."
    )
}

def get_latest_stream():
    """Scrapes the newest stream directly from AM950's live streams tab."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    resp = requests.get(STREAMS_URL, headers=headers, timeout=15)
    resp.raise_for_status()

    matches = re.findall(r'\"videoId\":\"([a-zA-Z0-9_-]{11})\".*?\"title\":\{\"runs\":\[\{\"text\":\"(.*?)\"\}\]', resp.text)
    if matches:
        video_id, title = matches[0]
        return video_id, title

    id_match = re.search(r'\"videoId\":\"([a-zA-Z0-9_-]{11})\"', resp.text)
    if id_match:
        return id_match.group(1), "AM950 Broadcast"

    return None, None

def download_audio(video_url: str) -> str:
    """Downloads audio in low-bitrate m4a/mp3 for fast transfer."""
    output_filename = "stream_audio.m4a"
    if os.path.exists(output_filename):
        os.remove(output_filename)

    ydl_opts = {
        'format': 'ba[ext=m4a]/ba/b',
        'outtmpl': 'stream_audio.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios']
            }
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])

    for ext in ['m4a', 'mp3', 'webm', 'opus']:
        fname = f"stream_audio.{ext}"
        if os.path.exists(fname):
            return fname
    raise FileNotFoundError("Audio download failed.")

def identify_focus(title: str) -> str:
    for key in SHOW_PROMPTS:
        if re.search(key, title, re.IGNORECASE):
            return SHOW_PROMPTS[key]
    return "Focus on: Local news stories, community discussion, guest highlights, and potential broadcast flags."

def generate_summary(audio_path: str, title: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    focus_guidance = identify_focus(title)

    print(f"Uploading audio ({audio_path}) to Gemini File API...")
    audio_file = client.files.upload(file=audio_path)

    # Allow brief moment if file is processing
    while audio_file.state.name == "PROCESSING":
        time.sleep(3)
        audio_file = client.files.get(name=audio_file.name)

    prompt = f"""
    You are an executive assistant to the Station Manager at AM950 Radio.
    Analyze the full audio from this radio broadcast for: "{title}".
    
    Show Focus:
    {focus_guidance}
    
    Provide a concise, professional broadcast management summary:
    1. EXECUTIVE SUMMARY:
       - 2-3 sentences summarizing core topics, overall tone, and lead stories.
    2. KEY TOPICS & SEGMENTS:
       - Chronological bullet points of issues, local MN news, and policies covered.
    3. GUESTS, INTERVIEWS & NOTABLE CALLERS:
       - Identify guests or callers, their affiliations, positions, and memorable quotes.
    4. STATION PROMOTIONS & SPONSORS:
       - Station sponsors, upcoming events, or host promotions noted on-air.
    5. COMPLIANCE & TONE FLAGS:
       - Note any potential broadcast flags (coarse language, personal attacks, or unverified claims) needing management review. If clean, write "None noted."
    """

    print("Generating summary...")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[audio_file, prompt]
    )

    # Clean up uploaded cloud file
    try:
        client.files.delete(name=audio_file.name)
    except Exception:
        pass

    return response.text

def send_email(subject: str, body: str, video_url: str):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECIPIENT
    msg['Subject'] = subject
    
    email_content = f"{body}\n\n---\nArchived Stream: {video_url}"
    msg.attach(MIMEText(email_content, 'plain'))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
    print("Email notification dispatched successfully.")

def main():
    if not os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "w") as f:
            f.write("")

    with open(PROCESSED_FILE, "r") as f:
        processed_ids = set(line.strip() for line in f.readlines())

    video_id, title = get_latest_stream()
    if not video_id:
        print("No stream found on channel.")
        return

    if video_id in processed_ids:
        print(f"Video {video_id} ('{title}') was already processed. Exiting.")
        return

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"Processing stream: {title} ({video_url})")
    
    audio_file = download_audio(video_url)
    try:
        summary = generate_summary(audio_file, title)
        send_email(f"[AM950 Summary] {title}", summary, video_url)
        with open(PROCESSED_FILE, "a") as f:
            f.write(f"{video_id}\n")
    finally:
        if os.path.exists(audio_file):
            os.remove(audio_file)

if __name__ == "__main__":
    main()
