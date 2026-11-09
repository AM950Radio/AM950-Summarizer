import os
import re
import datetime
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
CHANNEL_URL = "https://www.youtube.com/@AM950Radio/streams"
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
    """Dynamically finds the latest completed stream from AM950's streams tab."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    try:
        resp = requests.get(CHANNEL_URL, headers=headers, timeout=15)
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

    return "CPEGMSH1p8E", "Politics Matters with Bruce Klopfleisch", "Recent broadcast from AM950 Radio Minnesota."

def fetch_video_details(video_id):
    """Fetches clean title and description via oEmbed and metadata."""
    title = ""
    desc = "Recent broadcast from AM950 Radio Minnesota."
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        oembed_url = f"https://www.youtube.com/oembed?url={url}&format=json"
        res = requests.get(oembed_url, timeout=10)
        if res.status_code == 200:
            title = res.json().get("title", "")
    except Exception:
        pass

    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        desc_match = re.search(r'<meta name="description" content="(.*?)">', res.text)
        if desc_match:
            desc = desc_match.group(1).strip()
    except Exception:
        pass

    return title, desc

def identify_focus(title):
    for key in SHOW_PROMPTS:
        if re.search(key, title, re.IGNORECASE):
            return SHOW_PROMPTS[key]
    return "Focus on: Local news stories, community discussion, and guest commentary."

def generate_summary(video_url, title, description):
    client = genai.Client(api_key=GEMINI_API_KEY)
    focus_guidance = identify_focus(title)
    today_str = datetime.datetime.now().strftime("%B %d, %Y")

    prompt = f"""You are an executive assistant to the Station Manager at AM950 Radio in Minnesota.
Today's Date: {today_str}

Analyze this broadcast record and outline for the AM950 program:
Show Title: {title}
URL: {video_url}

Episode Information & Overview:
{description}

Guidance:
{focus_guidance}

Format the response as an executive station memo:
MEMORANDUM
DATE: {today_str}
BROADCAST: {title}

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
        try:
            print("Generating summary with:", model_name, flush=True)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            if response.text:
                return response.text
        except Exception as e:
            print(model_name, "warning:", e, flush=True)

    raise RuntimeError("All Gemini candidate models failed to generate content.")

def send_email(subject, body, video_url):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECIPIENT
    msg['Subject'] = subject

    content = body + "\n\n---\nBroadcast Link: " + video_url
    msg.attach(MIMEText(content, 'plain'))

    print("Connecting to Gmail SMTP via SSL...", flush=True)
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
    print("Processing show:", title, video_url, flush=True)

    summary = generate_summary(video_url, title, desc)
    send_email("[AM950 Broadcast Summary] " + title, summary, video_url)

    with open(PROCESSED_FILE, "a") as f:
        f.write(video_id + "\n")

if __name__ == "__main__":
    main()
