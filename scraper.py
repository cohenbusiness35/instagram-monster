#!/usr/bin/env python3
"""
Instagram scraper for kitchen remodeler leads.
Step 1: Apify hashtag scraper → unique usernames
Step 2: Apify profile scraper → bio, followers, website
Step 3: Claude Haiku → classify (real kitchen remodeler contractor or not)
Step 4: Claude Haiku → personalized DM for each qualified lead
Step 5: Push to Google Sheets
"""

import os
import csv
import time
import requests
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv()

APIFY_TOKEN = os.getenv("APIFY_API_TOKEN")
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

HASHTAGS = [
    "kitchenremodel",
    "kitchenrenovation",
    "kitchenremodeling",
    "kitchencontractor",
    "kitchendesignbuild",
    "customkitchen",
    "kitchenupgrade",
]

RESULTS_PER_HASHTAG = 20
OUTPUT_FILE = "ig_leads.csv"
DMS_FILE = "ig_dms.csv"


# ── Apify helpers ──────────────────────────────────────────────────────────────

def apify_run(actor: str, payload: dict, timeout_polls: int = 60) -> list[dict]:
    run_url = f"https://api.apify.com/v2/acts/{actor}/runs?token={APIFY_TOKEN}"
    resp = requests.post(run_url, json=payload, timeout=30)
    resp.raise_for_status()
    run_id = resp.json()["data"]["id"]

    for _ in range(timeout_polls):
        time.sleep(5)
        s = requests.get(
            f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_TOKEN}",
            timeout=15,
        ).json()
        status = s["data"]["status"]
        if status == "SUCCEEDED":
            dataset_id = s["data"]["defaultDatasetId"]
            items = requests.get(
                f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_TOKEN}&format=json",
                timeout=30,
            ).json()
            return items if isinstance(items, list) else []
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            print(f"    Apify run ended: {status}")
            return []
    print(f"    Apify run timed out.")
    return []


# ── Step 1: collect usernames from hashtags ────────────────────────────────────

def collect_usernames() -> dict[str, str]:
    seen: dict[str, str] = {}
    for tag in HASHTAGS:
        print(f"  #{tag}...")
        posts = apify_run(
            "apify~instagram-hashtag-scraper",
            {"hashtags": [tag], "resultsLimit": RESULTS_PER_HASHTAG},
        )
        for post in posts:
            handle = post.get("ownerUsername") or post.get("username") or ""
            if handle and handle not in seen:
                seen[handle] = (post.get("caption") or "")[:300]
        print(f"    {len(seen)} unique handles so far")
    return seen


# ── Step 2: enrich with profile data ──────────────────────────────────────────

def enrich_profiles(username_captions: dict[str, str]) -> list[dict]:
    handles = list(username_captions.keys())
    print(f"\nFetching profiles for {len(handles)} accounts...")

    BATCH = 50
    profiles: dict[str, dict] = {}

    for i in range(0, len(handles), BATCH):
        batch = handles[i : i + BATCH]
        print(f"  Profile batch {i//BATCH + 1}: {len(batch)} accounts...")
        items = apify_run(
            "apify~instagram-profile-scraper",
            {"usernames": batch},
            timeout_polls=90,
        )
        for p in items:
            username = p.get("username") or ""
            if username:
                profiles[username] = p

    leads = []
    for handle, caption in username_captions.items():
        p = profiles.get(handle, {})
        followers = p.get("followersCount") or 0
        if followers < 200:
            continue
        leads.append({
            "handle": handle,
            "full_name": p.get("fullName") or "",
            "bio": (p.get("biography") or "")[:300],
            "followers": followers,
            "website": p.get("externalUrl") or "",
            "location": p.get("city") or p.get("businessAddressJson", {}).get("city", "") if isinstance(p.get("businessAddressJson"), dict) else "",
            "recent_caption": caption,
        })

    leads.sort(key=lambda x: x["followers"], reverse=True)
    return leads


# ── Step 3: filter — only real kitchen remodeling contractors ─────────────────

FILTER_PROMPT = """You are vetting Instagram accounts to find kitchen remodeling contractors in the US or Canada.

We want LOCAL CONTRACTORS who physically perform kitchen remodeling and renovation work for homeowners or developers.

EXCLUDE if any of the following are true:
- Paint brand, DIY product, or home improvement supply company
- Cabinet manufacturer, supplier, or wholesaler (sells TO remodelers, doesn't do the work)
- Appliance store or outlet
- Interior designer or decorator only (no construction work)
- Real estate agent or realtor
- Photography, media, marketing, or advertising company
- Single-trade only: flooring, painting, glass, roofing (unless kitchen remodeling is clearly primary)
- Located outside the US or Canada (Australia, UK, Malaysia, etc.)
- Large national chain or franchise headquarters account
- Home improvement retail store

Account info:
- Handle: @{handle}
- Name: {full_name}
- Bio: {bio}
- Website: {website}
- Location: {location}
- Recent post: {caption}

Is this a legitimate kitchen remodeling contractor operating in the US or Canada?

Reply with ONLY: YES or NO, then a comma, then one short reason under 10 words.
Examples:
YES, kitchen remodeling contractor in Dallas TX
NO, DIY paint product brand not a contractor
NO, cabinet supplier sells to remodelers
NO, based in Australia"""


def classify_lead(lead: dict) -> tuple[bool, str]:
    prompt = FILTER_PROMPT.format(
        handle=lead["handle"],
        full_name=lead["full_name"],
        bio=lead["bio"],
        website=lead["website"],
        location=lead["location"],
        caption=lead["recent_caption"],
    )
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=60,
            messages=[{"role": "user", "content": prompt}],
            timeout=20,
        )
        text = msg.content[0].text.strip()
        is_qualified = text.upper().startswith("YES")
        reason = text.split(",", 1)[1].strip() if "," in text else text
        return is_qualified, reason
    except Exception as e:
        return False, f"classification error: {e}"


def filter_leads(leads: list[dict]) -> list[dict]:
    print(f"\nClassifying {len(leads)} accounts...")
    qualified = []
    rejected = []

    for i, lead in enumerate(leads, 1):
        is_qualified, reason = classify_lead(lead)
        status = "KEEP" if is_qualified else "skip"
        print(f"  [{status}] @{lead['handle']} — {reason}")
        if is_qualified:
            qualified.append(lead)
        else:
            rejected.append({**lead, "reason": reason})
        time.sleep(0.2)

    print(f"\n  Qualified: {len(qualified)} | Rejected: {len(rejected)}")
    return qualified


# ── Step 4: generate DMs ───────────────────────────────────────────────────────

def generate_dm(lead: dict) -> str:
    prompt = f"""You are writing a cold Instagram DM for Cohen Rosado, founder of Ascend Stack.

The offer: We help kitchen remodelers get fully booked with high-value clients through a done-for-you system. Guaranteed results or they don't pay.

Lead profile:
- Handle: @{lead['handle']}
- Name/Brand: {lead['full_name']}
- Bio: {lead['bio']}
- Followers: {lead['followers']:,}
- Website: {lead['website']}
- Location: {lead['location']}

Write a short cold DM (2-3 sentences). Rules:
- Sound like a real person reaching out, not a marketer blasting
- Reference something specific from their profile if possible
- Do NOT mention price, revenue numbers, or "150k"
- End with a low-pressure question like "would that be worth a quick chat?" or "open to hearing more?"
- No emojis. No exclamation points. No "Hey there!" opener.
- Start with their first name or brand name if you can tell it, otherwise lead with the message

Return ONLY the DM text."""

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=150,
        messages=[{"role": "user", "content": prompt}],
        timeout=20,
    )
    return msg.content[0].text.strip()


def generate_all_dms(leads: list[dict]) -> list[dict]:
    rows = []
    for i, lead in enumerate(leads, 1):
        print(f"  DM {i}/{len(leads)}: @{lead['handle']}...")
        try:
            dm = generate_dm(lead)
        except Exception as e:
            print(f"    Error: {e}")
            dm = ""
        rows.append({
            "handle": lead["handle"],
            "full_name": lead["full_name"],
            "followers": lead["followers"],
            "website": lead["website"],
            "location": lead["location"],
            "dm": dm,
            "sent": "no",
            "replied": "no",
        })
        time.sleep(0.3)
    return rows


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("=== Instagram Monster: Kitchen Remodelers ===\n")

    print("Step 1: Collecting usernames from hashtags...")
    username_captions = collect_usernames()
    print(f"  Total unique handles: {len(username_captions)}")

    print("\nStep 2: Enriching profiles (bio, followers, website)...")
    leads = enrich_profiles(username_captions)
    print(f"  Profiles pulled (200+ followers): {len(leads)}")

    print("\nStep 3: Filtering — keeping only verified kitchen remodeling contractors...")
    qualified = filter_leads(leads)

    # Save raw leads (all, for reference)
    with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
        if leads:
            writer = csv.DictWriter(f, fieldnames=leads[0].keys())
            writer.writeheader()
            writer.writerows(leads)

    # Load existing DMs so we don't overwrite sent status or duplicate leads
    existing: dict[str, dict] = {}
    if Path(DMS_FILE).exists():
        with open(DMS_FILE, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing[row["handle"]] = row

    new_leads = [l for l in qualified if l["handle"] not in existing]
    print(f"\nStep 4: Generating personalized DMs for {len(new_leads)} new leads ({len(qualified) - len(new_leads)} already in queue)...")
    new_rows = generate_all_dms(new_leads)

    # Merge: existing rows first (preserves sent status), then new rows
    merged = list(existing.values()) + new_rows
    with open(DMS_FILE, "w", newline="", encoding="utf-8") as f:
        if merged:
            writer = csv.DictWriter(f, fieldnames=merged[0].keys())
            writer.writeheader()
            writer.writerows(merged)

    print(f"\nStep 5: Pushing to Google Sheets...")
    try:
        from sheets_sync import push_to_sheets
        push_to_sheets(merged)
    except Exception as e:
        print(f"  Sheets sync failed: {e}")
        print(f"  Run manually: python3 sheets_sync.py")

    unsent = len([r for r in merged if r.get("sent") == "no"])
    print(f"\nDone. {len(new_rows)} new leads added. {unsent} total unsent in queue.")
    print("Track progress: python3 mark_sent.py stats")


if __name__ == "__main__":
    main()
