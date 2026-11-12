import os
import re
import json
import time
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import xml.etree.ElementTree as ET
import requests
from google import genai
from google.genai import types

print("--- Script Starting ---", flush=True)

# Credentials and Config
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
EMAIL_SENDER = os.environ.get("EMAIL_SENDER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_RECIPIENT = os.environ.get("EMAIL_RECIPIENT")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465
PROCESSED_FILE = "last_processed_video.txt"
HISTORY_FILE = "episode_history.json"
AUDIO_PATH = "broadcast_episode.mp3"

SHOW_FEEDS = {
    "The Matt McNeil Show": [
        "https://www.am950radio.com/category/the-matt-mcneil-show/feed/",
        "https://www.am950radio.com/category/podcasts/mcneil/feed/",
        "https://www.am950radio.com/category/matt-mcneil/feed/"
    ],
    "Native Roots Radio": [
        "https://www.am950radio.com/category/podcasts/im-awake/feed/",
        "https://www.am950radio.com/category/im-awake/feed/",
        "https://www.am950radio.com/category/native-roots-radio/feed/"
    ],
    "The Gaily Show": [
        "https://www.am950radio.com/category/podcasts/gaily/feed/",
        "https://www.am950radio.com/category/gaily/feed/",
        "https://www.am950radio.com/category/the-gaily-show/feed/"
    ],
    "Politics Matters": [
        "https://www.am950radio.com/category/podcasts/pm/feed/"
    ]
}

def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=2)

def extract_mp3_from_item(item):
    enc = item.find("enclosure")
    if enc is not None and "url" in enc.attrib:
        return enc.attrib["url"]
    raw_xml = ET.tostring(item, encoding="unicode")
    m = re.search(r'https?://[^\s"\'<>]+\.mp3', raw_xml)
    if m:
        return m.group(0)
    return None

def get_recent_episodes():
    headers = {"User-Agent": "Mozilla/5.0"}
    episodes = []
    seen = set()

    for show, urls in SHOW_FEEDS.items():
        found = False
        print(f"\nChecking feed for: {show}", flush=True)
        for url in urls:
            for net_try in range(2):
                try:
                    r = requests.get(url, headers=headers, timeout=15)
                    print(f"URL {url} -> Status {r.status_code}", flush=True)
                    if r.status_code != 200:
                        break
                    root = ET.fromstring(r.content)
                    items = root.findall(".//item")
                    for item in items:
                        title_node = item.find("title")
                        title = title_node.text if title_node is not None else show
                        link_node = item.find("link")
                        link = link_node.text if link_node is not None else ""

                        mp3 = extract_mp3_from_item(item)
                        ep_id = link if link else title
                        if mp3 and ep_id not in seen:
                            seen.add(ep_id)
                            episodes.append({
                                "id": ep_id,
                                "show": show,
                                "title": title,
                                "mp3": mp3
                            })
                            print(f"Found latest episode: {title}", flush=True)
                            found = True
                            break
                    break
                except Exception as e:
                    print(f"Feed attempt {net_try+1} error {url}: {e}", flush=True)
                    time.sleep(3)
            if found:
                break

        if not found:
            keyword = "McNeil" if "McNeil" in show else show.split()[0]
            try:
                r = requests.get("https://www.am950radio.com/category/podcasts/feed/", headers=headers, timeout=15)
                if r.status_code == 200:
                    root = ET.fromstring(r.content)
                    for item in root.findall(".//item"):
                        title_node = item.find("title")
                        title = title_node.text if title_node is not None else ""
                        if re.search(keyword, title, re.IGNORECASE):
                            mp3 = extract_mp3_from_item(item)
                            link_node = item.find("link")
                            link = link_node.text if link_node is not None else title
                            if mp3 and link not in seen:
                                seen.add(link)
                                episodes.append({"id": link, "show": show, "title": title, "mp3": mp3})
                                print(f"Found via master feed: {title}", flush=True)
                                found = True
                                break
            except Exception as e:
                print(f"Master feed fallback error: {e}", flush=True)

        if not found:
            print(f"No active MP3 found for {show}", flush=True)

    print(f"\nTotal episodes ready to check: {len(episodes)}", flush=True)
    return episodes

def download_audio(url):
    print(f"Downloading MP3: {url}", flush=True)
    if os.path.exists(AUDIO_PATH):
        os.remove(AUDIO_PATH)
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, stream=True, timeout=90)
        r.raise_for_status()
        with open(AUDIO_PATH, "wb") as f:
            for chunk in r.iter_content(chunk_size=1048576):
                if chunk:
                    f.write(chunk)
        if os.path.exists(AUDIO_PATH):
            size_mb = os.path.getsize(AUDIO_PATH) / 1048576
            print(f"Audio downloaded: {size_mb:.2f} MB", flush=True)
            return True
    except Exception as e:
        print(f"Download failed: {e}", flush=True)
    return False

def generate_summary(show_name, title, past_episodes):
    client = genai.Client(api_key=GEMINI_API_KEY, http_options=types.HttpOptions(timeout=300000.0))
    today_str = datetime.datetime.now().strftime("%B %d, %Y")

    if past_episodes:
        history_context = "RECENT PREVIOUS EPISODES AND TOPICS COVERED:\n"
        for p in past_episodes[-6:]:
            history_context += f"- Date: {p.get('date', 'Recent')}, Episode: {p.get('title', '')}\n  Topics: {p.get('topics', 'N/A')}\n"
    else:
        history_context = "No previous episode topic history recorded yet for this show."

    prompt = f"""You are the Executive Station & Editorial Director at AM950 Radio (KTNF) in Minneapolis-St. Paul, AND the Lead Digital Strategist / SEO Social Copy Expert for Heartland Signal.
Today's Date: {today_str}
Show Name: {show_name}
Episode Title: {title}

{history_context}

INSTRUCTIONS:
Listen carefully to the full broadcast audio attached. Produce an in-depth promotional, YouTube packaging, editorial, and compliance memorandum based STRICTLY on what was spoken on air. Never invent, extrapolate, or fabricate quotes or topics.

----------------------------------------------------------------------
SOCIAL EXCERPT & "WHAT'S IN IT FOR ME" STYLE RULES (FOR SECTION 1):
- Core SEO Rule (Name & State First): Front-load the named official/guest and the specific state (e.g., Minnesota, Wisconsin, Michigan, Illinois, Iowa, Ohio, etc.) at or near the very front of the excerpt. Never use regional labels like "Midwest" when a specific state name does the SEO work.
- Lead with Accountability Tension or Stakes: Hook listeners with what someone in power did, or who a decision affects ("Records reveal," "defended," "skipped," "100,000 lose"). Intrigue, don't give away the whole payoff.
- Keep it Tight & Sentence Case: 2 to 4 short sentences per excerpt. Use sentence case throughout — NO Title Case headlines.
- Register: Default to straight, plainspoken, attribution-forward news voice — factual, no jokes. Only switch to a sharper/voice-forward register if the broadcast segment is explicitly playful opinion/commentary (and flag when you do so).
- Angles to Offer (Provide 3–4 labeled options per broadcast):
  * **Option 1 (accountability angle)** — lead with what an official or public figure did.
  * **Option 2 (stakes angle)** — lead with who's affected and how much ("what's in it for me").
  * **Option 3 (straight-news angle)** — clean who/what/where, name and state up front, no spin.
  * **Option 4 (curiosity angle)** — a question or tension the broadcast resolves (use ONLY when genuinely earned by the audio).

PATTERN EXAMPLES FOR SECTION 1:
Example A:
**Option 1 (accountability angle)**
Rep. Derrick Van Orden calls agriculture his "true love." Wisconsin committee records tell a different story. He skipped at least 10 of 22 House Agriculture hearings since 2024 — as farm bankruptcies surge across the state.
**Option 2 (stakes angle)**
Farm bankruptcies are surging in Wisconsin. The congressman who calls agriculture his top priority, Derrick Van Orden, missed at least 10 of 22 House Agriculture Committee hearings since 2024. The records are public.

Example B:
**Option 1 (stakes angle)**
Nearly 100,000 Tennesseans have lost SNAP food aid since the One Big Beautiful Bill Act took effect last July. Cassandra Boyle is one of them. Her story shows what the enrollment data looks like up close.
**Option 2 (straight-news angle)**
State enrollment data shows about 100,000 Tennesseans have lost SNAP food benefits since the One Big Beautiful Bill Act took effect in July 2025.

----------------------------------------------------------------------
YOUTUBE HEADLINE GENERATOR RULES (FOR SECTION 2):
- Audience & Tone: Direct, sharp, objective yet impactful, exposing political hypocrisy, highlighting labor/rights issues, and amplifying critical political quotes for progressive and Midwestern political observers.
- Hard Limit: NEVER exceed 100 characters (including spaces).
- Ideal Range: Target 50–70 characters for peak mobile and desktop visibility.
- Front-Loading Rule: Put the politician's name, key organization, or major hook within the FIRST 40 CHARACTERS.
- Specificity: Use direct quotes in quotation marks ("...") when a quote is the primary hook.
- Limit Caps: Maximum 1 ALL-CAPS word per title for emphasis (e.g., EXPOSED, REJECTS, ADMITS).
- Generate 8 to 10 title options organized under these 4 news-centric categories:
  1. 📰 Breaking & Headline News (Clear, SEO-focused, name-first for search)
  2. 🧲 Direct Quote / Exposé Hook (Uses candidate quotes or call-outs to drive CTR)
  3. ⚡ Ultra-Punchy / Shorts Ready (< 45 characters, fast scan on mobile)
  4. 🏛️ Policy & Community Impact (Focused on labor, rights, elections, or Midwest politics)
- CRITICAL RULE: Always display the character count at the end of every title, e.g., "Title Text Here [52 chars]".
----------------------------------------------------------------------

Generate the full memorandum in this exact format:

======================================================================
EXECUTIVE BROADCAST MEMORANDUM & COMPLIANCE LOG
SHOW: {show_name}
EPISODE: {title}
DATE: {today_str}
======================================================================

1. SOCIAL EXCERPTS & PROMOTIONAL COPY ("WHAT'S IN IT FOR ME"):
   - Write 3–4 excerpt options (using the Accountability, Stakes, Straight-News, and Curiosity angles above), front-loading named officials/guests and specific states, written in crisp sentence-case prose designed to intrigue people to listen.
   - **Recommendation:** In 1–2 sentences, state which option(s) to lead with and why.
   - **Editorial Flags:** Flag any accuracy risks, sensitive framing, voice questions, or reasons an angle might not land.

2. YOUTUBE HEADLINES (HIGH-CTR & SHORTS PACKAGING):
   - Provide 8–10 YouTube title options organized under the 4 required categories (📰 Breaking & Headline News, 🧲 Direct Quote / Exposé Hook, ⚡ Ultra-Punchy / Shorts Ready, 🏛️ Policy & Community Impact), strictly following the character limits, front-loading, quote, and ALL-CAPS rules, with [XX chars] at the end of every single title.

3. EXECUTIVE SUMMARY:
   - 3-4 dense sentences detailing the lead news events, overall broadcast trajectory, and central editorial themes.

4. COMPREHENSIVE SEGMENT BREAKDOWN:
   - Chronological breakdown of each topic discussed.
   - Detail the core argument, specific candidate/ballot races, local/state policy implications, and notable claims cited.

5. STORY CONTINUITY & REPEAT COVERAGE MONITOR:
   - Compare today's broadcast against the RECENT PREVIOUS EPISODES list provided above.
   - Note whether this story has been covered previously on this show, if it is a continuing development, a brand new breaking topic, or an interview with a repeating guest.

6. GUESTS, INTERVIEWS & CALLERS:
   - List every named guest with key arguments, organization, and direct quotes.
   - Summarize notable listener call-ins (name, location, topic raised, host response). If none, state: "Solo monologue; no caller segments."

7. HEARTLAND SIGNAL MONITORING (HeartlandSignal.com):
   - Explicitly note whether Heartland Signal, HeartlandSignal.com, or Heartland Signal staff/reporters were cited, interviewed, or credited.
   - Detail the specific reporting, scoop, or byline referenced. If none, state: "None cited."

8. PLAYED CLIPS & RECORDED ACTUALITY:
   - List all recorded audio, debate clips, press conference audio, viral clips, or external news segments played on-air during the broadcast. Note whose voice was played and the context. If none, state: "No external clips played."

9. RURAL MINNESOTAN TONE & SENSITIVITY MONITOR:
   - Identify any disparaging, dismissive, or condescending language directed broadly at rural Minnesotans, Greater Minnesota communities, or rural voters. If fair policy critique or clean, state: "Clean - No derogatory language toward rural Minnesotans noted."

10. CONSPIRACY THEORIES & UNSUPPORTED CLAIMS:
    - Flag any unsubstantiated conspiracy theories, unevidenced allegations, or fringe claims made by hosts, guests, or callers. If none, state: "Clean - No unsubstantiated conspiracy theories detected."

11. SPONSORS, UNDERWRITING & STATION PROMOTIONS:
    - List every business, non-profit, union, or underwriter explicitly promoted or thanked.

12. REGULATORY & FCC FLAGS:
    - Language, broadcast decency, personal attacks, or FCC compliance concerns. If clean, state: "Clean - No compliance flags noted."

13. KEY TOPICS INDEX:
    - Provide a single comma-separated list of 3 to 6 major topics/names discussed in this broadcast (for archiving and historical tracking).
"""

    print("Uploading MP3 to Gemini...", flush=True)
    uploaded = client.files.upload(file=AUDIO_PATH)
    print("Generating comprehensive memo...", flush=True)

    config = types.GenerateContentConfig(temperature=0.2, max_output_tokens=5000)
    for model in ["gemini-3.8-flash", "gemini-3.5-flash-lite"]:
        for attempt in range(1, 4):
            try:
                print(f"Calling {model} (attempt {attempt}/3)...", flush=True)
                res = client.models.generate_content(model=model, contents=[uploaded, prompt], config=config)
                if res and res.text:
                    try:
                        client.files.delete(name=uploaded.name)
                    except Exception:
                        pass
                    return res.text
            except Exception as e:
                print(f"{model} attempt {attempt} error: {e}", flush=True)
                time.sleep(10 * attempt)

    raise RuntimeError("All models failed to generate summary.")

def send_email(show_name, title, body, link):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECIPIENT

    clean_sub = title.replace(show_name, "").strip(" -:|")
    display_title = clean_sub if clean_sub else title
    msg['Subject'] = f"[AM950] {show_name} | {display_title}"

    msg.attach(MIMEText(body + f"\n\n---\nEpisode Link: {link}", 'plain'))

    recipients = [addr.strip() for addr in EMAIL_RECIPIENT.split(",") if addr.strip()]

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, timeout=30) as s:
        s.login(EMAIL_SENDER, EMAIL_PASSWORD)
        s.send_message(msg, to_addrs=recipients)
    print(f"Email sent successfully to {len(recipients)} recipient(s)!", flush=True)

def extract_topics(summary_text):
    match = re.search(r"13\.\s*KEY TOPICS INDEX:\s*\n*(.*?)(?=\n\n|\Z)", summary_text, re.DOTALL)
    if match:
        return match.group(1).replace("-", "").strip()
    return "General news and commentary"

def main():
    if not os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, "w") as f:
            f.write("")

    with open(PROCESSED_FILE, "r") as f:
        done = set(line.strip() for line in f if line.strip())

    history = load_history()
    candidates = get_recent_episodes()
    pending = [ep for ep in candidates if ep["id"] not in done]

    if not pending:
        print("All target shows already processed. Exiting cleanly.", flush=True)
        return

    print(f"Found {len(pending)} new episode(s) to process.", flush=True)
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")

    for ep in pending:
        show_name = ep["show"]
        print(f"\n--- Processing: {show_name} - {ep['title']} ---", flush=True)
        if download_audio(ep["mp3"]):
            try:
                past_episodes = history.get(show_name, [])
                summary = generate_summary(show_name, ep["title"], past_episodes)
                send_email(show_name, ep["title"], summary, ep["id"])

                with open(PROCESSED_FILE, "a") as f:
                    f.write(ep["id"] + "\n")
                print(f"Recorded ID: {ep['id']}", flush=True)

                topics = extract_topics(summary)
                if show_name not in history:
                    history[show_name] = []
                history[show_name].append({
                    "date": today_str,
                    "title": ep["title"],
                    "topics": topics
                })
                history[show_name] = history[show_name][-15:]
                save_history(history)

            except Exception as e:
                print(f"Processing error: {e}", flush=True)
            finally:
                if os.path.exists(AUDIO_PATH):
                    os.remove(AUDIO_PATH)
        time.sleep(3)

    print("\nBatch process complete.", flush=True)

if __name__ == "__main__":
    main()
