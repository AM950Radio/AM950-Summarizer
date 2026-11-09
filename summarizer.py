import os
import re
import smtplib
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from google import genai
from google.genai import types

# ================= Configuration =================
# AM950 Official YouTube Channel RSS Feed
RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id=UC6P7_B57oV1L57K_x0ZkMtg"
FALLBACK_CHANNEL_URL = "https://www.youtube.com/@AM950Radio/videos"

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
        "Focus on: LGBTQ+ legislative and community topics, Minnesota cultural events, "
        "personal perspectives, support resources, and guest commentary."
    ),
    "McNeil": (
        "Focus on: Minnesota state and national political updates, interviews with elected officials "
        "or candidates, caller arguments/debates, and broadcast tone."
    ),
    "Native Roots": (
        "Focus on: Tribal sovereignty, Indian affairs, environmental/land/water rights, "
        "cultural preservation, and featured indigenous leaders."
    )
}

def get_latest_stream():
    """Fetches the latest public video directly from AM950's channel."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    # Primary: check public video list page
    resp = requests.get(FALLBACK_CHANNEL_URL, headers=headers, timeout=15)
    if resp.status_code == 200:
        matches = re.findall(r'\"videoId\":\"([a-zA-Z0-9_-]{11})\".*?\"title\":\{\"runs\":\[\{\"text\":\"(.*?)\"\}\]', resp.text)
        for vid_id, vid_title in matches:
            if any(term in vid_title.lower() for term in ["gaily", "mcneil", "native roots", "am950", "politics", "show"]):
                return vid_id, vid_title
        if matches:
            return matches[0][0], matches[0][1]

    return None, None

def identify_focus(title: str) -> str:
    for key in SHOW_PROMPTS:
        if re.search(key, title, re.IGNORECASE):
            return SHOW_PROMPTS[key]
    return "Focus on: Local news stories, community discussion, and guest commentary."

def generate_summary(video_url: str, title: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    focus_guidance = identify_focus(title)

    prompt = f"""
    You are an executive assistant to the Station Manager at AM950 Radio in Minnesota.
    Provide a professional broadcast management summary for this radio episode:
    Show Title: {title}
    URL: {video_url}
    
    Guidance:
    {focus_guidance}
    
    Using your search tools, look up this AM950 episode, topic breakdown, and discussion points.
    Provide:
    1. EXECUTIVE SUMMARY: 2-3 sentences on core topics and lead stories.
    2. KEY TOPICS & SEGMENTS: Chronological bullet points of issues and policies discussed.
    3. GUESTS & INTERVIEWS: Featured guests, titles, and key quotes or viewpoints.
    4. STATION PROMOTIONS & SPONSORS: Sponsors or community announcements mentioned.
    5. COMPLIANCE & TONE FLAGS: Any broadcast tone concerns or coarse language. If clean, state "None noted."
    """

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
    )
    return response.text

def send_email(subject: str, body: str, video_url: str):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECIPIENT
    msg['Subject'] = subject
    
    content = f"{body}\n\n---\nBroadcast Link: {video_url}"
    msg.attach(MIMEText(content, 'plain'))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.send_message(msg)
    print("Email sent successfully.")

def main():
    if not os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "w") as f:
            f.write("")

    with open(PROCESSED_FILE, "r") as f:
        processed_ids = set(line.strip() for line in f.readlines())

    video_id, title = get_latest_stream()
    if not video_id:
        print("No stream found.")
        return

    if video_id in processed_ids:
        print(f"Video {video_id} ('{title}') was already processed. Exiting.")
        return

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"Processing show: {title} ({video_url})")

    summary = generate_summary(video_url, title)
    send_email(f"[AM950 Broadcast Summary] {title}", summary, video_url)

    with open(PROCESSED_FILE, "a") as f:
        f.write(f"{video_id}\n")

if __name__ == "__main__":
    main()
