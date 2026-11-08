import os
import re
import smtplib
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from google import genai
from google.genai.types import Part

# ================= Configuration =================
AM950_CHANNEL_ID = "UCeqoQjJn89rE1qHvolb0XTA"
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
    """Fetch the latest published video/stream from AM950's public feed."""
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={AM950_CHANNEL_ID}"
    resp = requests.get(rss_url, timeout=15)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    
    entry = root.find("atom:entry", ns)
    if entry is None:
        return None, None

    video_id = entry.find("yt:videoId", ns).text
    title = entry.find("atom:title", ns).text
    return video_id, title

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
        model="gemini-2.5-flash",
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
        print("No videos found on channel.")
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
