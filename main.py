import json
import os
import re
import sys
import time

import feedparser
import requests

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

# RSS sources to monitor. Add/remove feeds here.
FEEDS = [
    {"name": "CryptoSlate", "url": "https://cryptoslate.com/feed/"},
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
]

STATE_FILE = "last_seen.json"
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash"

# Explicit list of notable people / entities. The AI filter is also allowed
# to use its own general knowledge beyond this list, but these are always
# treated as automatic passes.
NOTABLE_ENTITIES = [
    # People
    "Donald Trump", "Changpeng Zhao", "CZ", "Jack Dorsey", "Jack Mallers",
    "Elon Musk", "Michael Saylor", "Vitalik Buterin", "Brian Armstrong",
    "Sam Altman", "Gary Gensler", "Paul Atkins",
    # Founders / protocol figures
    "Anatoly Yakovenko", "Paolo Ardoino", "Jed McCaleb",
    # VCs
    "Paradigm", "Polychain Capital", "a16z", "Andreessen Horowitz",
    "Sequoia Capital", "Pantera Capital",
    # Exchanges / platforms
    "Coinbase", "Binance", "Bybit", "Kraken", "OKX", "Robinhood",
    # Protocols / assets often tied to major narratives
    "Solana", "Tether", "Sui", "Hyperliquid", "BNB Chain", "Ethereum",
    "Bitcoin",
]


# ---------------------------------------------------------------------------
# STATE HELPERS
# ---------------------------------------------------------------------------

def load_seen():
    if not os.path.exists(STATE_FILE):
        return []
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_seen(seen_ids):
    # keep only the last 300 to prevent the file from growing forever
    # (300 because we now track 3 feeds instead of 1)
    with open(STATE_FILE, "w") as f:
        json.dump(seen_ids[-300:], f, indent=2)


def clean_html(raw_html):
    return re.sub("<[^<]+?>", "", raw_html or "").strip()


# ---------------------------------------------------------------------------
# GEMINI: FILTER + TRANSLATE
# ---------------------------------------------------------------------------

def analyze_with_gemini(title, summary):
    """
    Sends the article to Gemini and asks it to:
    1. Decide if it mentions a notable crypto/AI/finance figure or major entity.
    2. If yes, produce an Indonesian headline + short summary in Enclavium's
       breaking-news style.
    Returns a dict: {"relevant": bool, "id_title": str, "id_summary": str}
    """
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)

    entity_list_str = ", ".join(NOTABLE_ENTITIES)

    prompt = f"""Kamu adalah asisten kurasi berita untuk media crypto Instagram bernama Enclavium.

Tugas kamu ada 2:
1. Tentukan apakah artikel ini menyebut tokoh besar, founder proyek besar, VC ternama, atau exchange besar di dunia crypto/AI/finance. Contoh nama yang WAJIB dianggap relevan: {entity_list_str}. Selain daftar ini, kamu boleh pakai pengetahuanmu sendiri untuk mengenali tokoh/entitas besar lain yang relevan di dunia crypto, AI, atau makroekonomi global, meskipun tidak ada di daftar.
2. Jika relevan, buat judul singkat ala breaking news (bombastis tapi tetap akurat, gaya media crypto Indonesia) dan ringkasan 2-3 kalimat dalam Bahasa Indonesia yang mudah dipahami.

Artikel:
Judul: {title}
Ringkasan asli: {summary}

Jawab HANYA dalam format JSON persis seperti ini, tanpa markdown, tanpa penjelasan tambahan:
{{"relevant": true atau false, "id_title": "judul dalam bahasa indonesia atau kosong jika tidak relevan", "id_summary": "ringkasan dalam bahasa indonesia atau kosong jika tidak relevan"}}
"""

    response = model.generate_content(prompt)
    text = response.text.strip()
    # strip potential markdown code fences
    text = re.sub(r"^```json\s*|\s*```$", "", text.strip(), flags=re.MULTILINE).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        print(f"Failed to parse Gemini response as JSON: {text[:200]}")
        return {"relevant": False, "id_title": "", "id_summary": ""}

    return {
        "relevant": bool(data.get("relevant", False)),
        "id_title": data.get("id_title", "").strip(),
        "id_summary": data.get("id_summary", "").strip(),
    }


# ---------------------------------------------------------------------------
# DISCORD
# ---------------------------------------------------------------------------

def send_to_discord(entry, source_name, id_title, id_summary):
    link = entry.get("link", "")

    image_url = None
    if "media_content" in entry and entry.media_content:
        image_url = entry.media_content[0].get("url")
    elif "links" in entry:
        for l in entry.links:
            if l.get("type", "").startswith("image"):
                image_url = l.get("href")
                break

    embed = {
        "title": id_title,
        "url": link,
        "description": id_summary,
        "color": 0xF7931A,
        "footer": {"text": source_name},
    }
    if image_url:
        embed["image"] = {"url": image_url}

    payload = {"embeds": [embed]}
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    if not WEBHOOK_URL:
        print("ERROR: DISCORD_WEBHOOK_URL environment variable is not set.")
        sys.exit(1)
    if not GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY environment variable is not set.")
        sys.exit(1)

    seen_ids = load_seen()
    seen_set = set(seen_ids)

    all_new_entries = []  # list of (entry, source_name)

    for feed_conf in FEEDS:
        feed = feedparser.parse(feed_conf["url"])
        if feed.bozo and not feed.entries:
            print(f"Failed to parse feed {feed_conf['name']}: {feed.bozo_exception}")
            continue

        for entry in feed.entries:
            entry_id = entry.get("id", entry.get("link"))
            if entry_id not in seen_set:
                all_new_entries.append((entry, feed_conf["name"]))

    if not all_new_entries:
        print("No new articles across all feeds.")
        return

    print(f"Found {len(all_new_entries)} new article(s) across {len(FEEDS)} feed(s). Analyzing...")

    posted_count = 0
    skipped_count = 0

    for entry, source_name in all_new_entries:
        entry_id = entry.get("id", entry.get("link"))
        title = entry.get("title", "")
        summary = clean_html(entry.get("summary", ""))

        try:
            analysis = analyze_with_gemini(title, summary)
        except Exception as e:
            print(f"Gemini analysis failed for '{title}': {e}")
            # mark as seen anyway so we don't retry forever on a broken entry
            seen_ids.append(entry_id)
            continue

        if analysis["relevant"]:
            try:
                send_to_discord(entry, source_name, analysis["id_title"], analysis["id_summary"])
                print(f"[POSTED] ({source_name}) {analysis['id_title']}")
                posted_count += 1
            except Exception as e:
                print(f"Failed to post to Discord: {e}")
                continue
        else:
            print(f"[SKIPPED] ({source_name}) {title}")
            skipped_count += 1

        seen_ids.append(entry_id)
        # small delay to be gentle on the free-tier rate limit
        time.sleep(2)

    save_seen(seen_ids)
    print(f"Done. Posted: {posted_count}, Skipped: {skipped_count}")


if __name__ == "__main__":
    main()
