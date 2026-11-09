import os
import re
import time
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from google import genai

# ================= Configuration =================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

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
    """Fetches the latest show metadata using YouTube oEmbed."""
    video_id = "CPEGMSH1p8E"
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    title = "AM950 Broadcast"
    try:
        oembed_url = f"https://www.youtube.com/oembed?url={video_url}&format=json"
        res = requests.get(oembed_url, timeout=10)
        if res.status_code == 200:
            title = res.json().get("title", title)
    except Exception as e:
        print(f"oEmbed title fetch note: {e}")

    desc = fetch_video_description(video_id)
    return video_id, title, desc

def fetch_video_description(video_id: str) -> str:
    """Fetches video description if available."""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        desc_match = re.search(r'<meta name="description" content="(.*?)">', res.text)
        if desc_match:
            return desc_match.group(1).strip()
    except Exception:
        pass
    return "Recent broadcast from AM950 Radio Minnesota."

def identify_focus(title: str) -> str:
    for key in SHOW_PROMPTS:
        if re.search(key, title, re.IGNORECASE):
            return SHOW_PROMPTS[key]
    return "Focus on: Local news stories, community discussion, and guest commentary."

def generate_summary(video_url: str, title: str, description: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    focus_guidance = identify_focus(title)

    prompt = f"""
    You are an executive assistant to the Station Manager at AM950 Radio in Minnesota.
    Analyze this broadcast record and outline for the AM950 program:
    Show Title: {title}
    URL: {video_url}
    
    Episode Information & Overview:
    {description}
    
    Guidance:
    {focus_guidance}
    
    Provide a professional broadcast management summary:
    1. EXECUTIVE SUMMARY:
       - 2-3 sentences summarizing core topics, overall tone, and lead stories.
    2. KEY TOPICS & SEGMENTS:
       - Chronological bullet points of issues and policies discussed.
    3. GUESTS & INTERVIEWS:
       - Featured guests, titles, and key quotes or viewpoints.
    4. STATION PROMOTIONS & SPONSORS:
       - Sponsors or community announcements mentioned.
    5. COMPLIANCE & TONE FLAGS:
       - Any broadcast tone concerns or coarse language. If clean, state "None noted."
    """

    candidate_models = ["gemini-3.8-flash", "gemini-2.5-flash", "gemini-1.5-flash"]
    
    for model_name in candidate_models:
        for attempt in range(2):
            try:
                print(f"Generating summary with {model_name} (attempt {attempt + 1})...")
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt
                )
                if response.text:
                    return response.text
            except Exception as e:
                print(f"{model_name} error: {e}")
                time.sleep(3)
                
    raise RuntimeError("All Gemini candidate models failed to generate content.")

def send_email(subject: str, body: str, video_url: str):
    msg
