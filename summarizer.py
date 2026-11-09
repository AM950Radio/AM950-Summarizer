import os
import re
import smtplib
import xml.etree.ElementTree as ET
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from google import genai

# ================= Configuration =================
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
    """Gets the channel ID from a known AM950 stream and reads the latest broadcast."""
    # Use oEmbed on a known AM950 broadcast to find the official channel URL
    known_video_url = "https://www.youtube.com/watch?v=CPEGMSH1p8E"
    oembed_url = f"https://www.youtube.com/oembed?url={known_video_url}&format=json"
    
    author_url = None
    try:
        res = requests.get(oembed_url, timeout=10)
        if res.status_code == 200:
            author_url = res.json().get("author_url")
    except Exception as e:
        print(f"oEmbed error: {e}")

    # Fetch author page to extract the real UC... channel ID
    channel_id = None
    if author_url:
        try:
            r = requests.get(author_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            # Find the true canonical channel ID tag
            match = re.search(r'itemprop="channelId"\s+content="(UC[a-zA-Z0-9_-]{22})"', r.text)
            if match:
                channel_id = match.group(1)
        except Exception as e:
            print(f"Error finding channelId: {e}")

    # Fallback to direct video page lookup if channelId tag wasn't found
    if not channel_id:
        try:
            r = requests.get(known_video_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            match = re.search(r'itemprop="channelId"\s+content="(UC[a-zA-Z0-9_-]{22})"', r.text)
            if match:
                channel_id = match.group(1)
        except Exception:
            pass

    if not channel_id:
        print("Could not locate verified channel ID. Fetching direct video details...")
        title, desc = fetch_video_details("CPEGMSH1p8E")
        return "CPEGMSH1p8E", title, desc

    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    print(f"Checking verified feed: {rss_url}")
    
    resp = requests.get(rss_url, timeout=10)
    if resp.status_code == 200:
        root = ET.fromstring(resp.content)
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'yt': 'http://www.youtube.com/xml/schemas/2015',
            'media': 'http://search.yahoo.com/mrss/'
        }
        entries = root.findall('atom:entry', ns)
        if entries:
            latest = entries[0]
            vid_id = latest.find('yt:videoId', ns).text
            title = latest.find('atom:title', ns).text
            media_group = latest.find('media:group', ns)
            desc = ""
            if media_group is not None:
                desc_elem = media_group.find('media:description', ns)
                if desc_elem is not None and desc_elem.text:
                    desc = desc_elem.text
            return vid_id, title, desc

    # Final reliable fallback: process the latest known broadcast directly
    print("Using direct stream fallback...")
    title, desc = fetch_video_details("CPEGMSH1p8E")
    return "CPEGMSH1p8E", title, desc

def fetch_video_details(video_id: str):
    """Fetches clean title and description from the video page."""
    try:
        url = f"https://www.youtube.com/watch?v={video_id}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        }
        res = requests.get(url, headers=headers, timeout=10)
        
        title_match = re.search(r'<meta name="title" content="(.*?)">', res.text)
        if not title_match:
            title_match = re.search(r'<title>(.*?)</title>', res.text)
        title = title_match.group(1).replace(" - YouTube", "").strip() if title_match else "AM950 Broadcast"

        desc_match = re.search(r'<meta name="description" content="(.*?)">', res.text)
        if not desc_match:
            desc_match = re.search(r'"shortDescription":"(.*?)"', res.text)
        desc = desc_match.group(1).strip() if desc_match else "No description available."

        return title, desc
    except Exception:
        return "AM950 Broadcast", "No description available."

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

    video_id, title, desc = get_latest_stream()
    if not video_id:
        print("No stream found. Exiting.")
        return

    if video_id in processed_ids:
        print(f"Video {video_id} ('{title}') was already processed. Exiting.")
        return

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"Processing show: {title} ({video_url})")

    summary = generate_summary(video_url, title, desc)
    send_email(f"[AM950 Broadcast Summary] {title}", summary, video_url)

    with open(PROCESSED_FILE, "a") as f:
        f.write(f"{video_id}\n")

if __name__ == "__main__":
    main()
