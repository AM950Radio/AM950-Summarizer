import os
import re
import smtplib
import json
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from google import genai
from google.genai.types import Part

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

    # Find the videoId and title from YouTube's initial page state
    matches = re.findall(r'\"videoId\":\"([a-zA-Z0-9_-]{11})\".*?\"title\":\{\"runs\":\[\{\"text\":\"(.*?)\"\}\]', resp.text)
    if matches:
        video_id, title = matches[0]
        return video_id, title

    # Fallback pattern if layout slightly differs
    id_match = re.search(r'\"videoId\":\"([a-zA-Z0-9_-]{11})\"', resp.text)
    if id_match:
        return id_match.group(1), "AM950 Broadcast"

    return None, None

def identify_focus(title: str) -> str:
    for key in SHOW_PROMPTS:
        if re.search(key, title, re.IGNORECASE):
            return SHOW_PROMPTS[key]
    return "Focus on: Local news stories, community discussion, guest highlights, and potential broadcast flags."

def generate_summary(video_url: str, title: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    focus_guidance = identify_focus(title)

    prompt = f"""
    You are an executive assistant to the Station Manager at AM950 Radio.
    Analyze the broadcast content from this YouTube live stream for: "{title}".
    
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

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=[
            Part.from_uri(file_uri=video_url, mime_type="video/mp4"),
            prompt
        ]
    )
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
    print(f"Processing new stream: {title} ({video_url})")
    
    summary = generate_summary(video_url, title)
    send_email(f"[AM950 Summary] {title}", summary, video_url)

    with open(PROCESSED_FILE, "a") as f:
        f.write(f"{video_id}\n")

if __name__ == "__main__":
    main()
