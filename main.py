import json
import os
import sys
import feedparser
import requests

FEED_URL = "https://cryptoslate.com/feed/"
STATE_FILE = "last_seen.json"
WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")


def load_seen():
    if not os.path.exists(STATE_FILE):
        return []
    with open(STATE_FILE, "r") as f:
        return json.load(f)


def save_seen(seen_ids):
    # keep only the last 100 to prevent the file from growing forever
    with open(STATE_FILE, "w") as f:
        json.dump(seen_ids[-100:], f, indent=2)


def send_to_discord(entry):
    title = entry.get("title", "No title")
    link = entry.get("link", "")
    summary = entry.get("summary", "")
    # strip html tags roughly and trim
    import re
    clean_summary = re.sub("<[^<]+?>", "", summary).strip()
    if len(clean_summary) > 300:
        clean_summary = clean_summary[:300] + "..."

    image_url = None
    if "media_content" in entry and entry.media_content:
        image_url = entry.media_content[0].get("url")
    elif "links" in entry:
        for l in entry.links:
            if l.get("type", "").startswith("image"):
                image_url = l.get("href")
                break

    embed = {
        "title": title,
        "url": link,
        "description": clean_summary,
        "color": 0xF7931A,
        "footer": {"text": "CryptoSlate"},
    }
    if image_url:
        embed["image"] = {"url": image_url}

    payload = {"embeds": [embed]}
    resp = requests.post(WEBHOOK_URL, json=payload, timeout=15)
    resp.raise_for_status()


def main():
    if not WEBHOOK_URL:
        print("ERROR: DISCORD_WEBHOOK_URL environment variable is not set.")
        sys.exit(1)

    feed = feedparser.parse(FEED_URL)
    if feed.bozo and not feed.entries:
        print(f"Failed to parse feed: {feed.bozo_exception}")
        sys.exit(1)

    seen_ids = load_seen()
    seen_set = set(seen_ids)

    # feed entries are newest-first; reverse so we post oldest-new-item first
    new_entries = [e for e in feed.entries if e.get("id", e.get("link")) not in seen_set]
    new_entries.reverse()

    if not new_entries:
        print("No new articles.")
        return

    for entry in new_entries:
        entry_id = entry.get("id", entry.get("link"))
        try:
            send_to_discord(entry)
            print(f"Posted: {entry.get('title')}")
        except Exception as e:
            print(f"Failed to post entry {entry_id}: {e}")
            continue
        seen_ids.append(entry_id)

    save_seen(seen_ids)


if __name__ == "__main__":
    main()
