import os
import sys
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from google import genai

print("--- Script Starting ---", flush=True)

# ================= Configuration =================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
PROCESSED_FILE = "last_processed_video.txt"
# =================================================

print(f"Sender configured: {'YES' if EMAIL_SENDER else 'NO'}", flush=True)
print(f"Recipient configured: {'YES' if EMAIL_RECIPIENT else 'NO'}", flush=True)
print(f"Gemini API key configured: {'YES' if GEMINI_API_KEY else 'NO'}", flush=True)

def get_latest_stream():
    video_id = "CPEGMSH1p8E"
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    title = "Episode 120 of Politics Matters with Bruce Klopfleisch"
    desc = "Recent broadcast from AM950 Radio Minnesota."
    try:
        oembed_url = f"https://www.youtube.com/oembed?url={video_url}&format=json"
        res = requests.get(oembed_url, timeout=10)
        if res.status_code == 200:
            title = res.json().get("title", title)
    except Exception as e:
        print(f"oEmbed fetch note: {e}", flush=True)

    return video_id, title, desc

def generate_summary(video_url: str, title: str, description: str) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""
    You are an executive assistant to the Station Manager at AM950 Radio.
    Provide a concise broadcast management summary for:
    Show Title: {title}
    URL: {video_url}
    Description: {description}
    
    Format with:
    1. EXECUTIVE SUMMARY
    2. KEY TOPICS & SEGMENTS
    3. GUESTS & INTERVIEWS
    4. STATION PROMOTIONS & SPONSORS
    5. COMPLIANCE & TONE FLAGS
    """
    print("Requesting summary from Gemini 3.8 Flash...", flush=True)
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt
    )
    return response.text

def send_email(subject: str, body: str, video_url: str):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECIPIENT
    msg['Subject'] = subject
    
    content = f"{body}\n\n---\nBroadcast Link: {video_url}"
    msg.attach(MIMEText(content, 'plain'))

    print(f"Connecting to {SMTP_SERVER}:{SMTP_PORT} via SSL...", flush=True)
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

    if video_id in processed_ids:
        print(f"Notice: Video {video_id} is in {PROCESSED_FILE}. Clearing to force test run...", flush=True)

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"Processing show: {title} ({video_url})", flush=True)

    summary = generate_summary(video_url, title, desc)
    print("Summary created. Sending email...", flush=True)
    send_email(f"[AM950 Broadcast Summary] {title}", summary, video_url)

    with open(PROCESSED_FILE, "w") as f:
        f.write(f"{video_id}\n")

if __name__ == "__main__":
    main()
