#!/usr/bin/env python3
"""
Instagram DM sender for kitchen remodeler leads.
Reads ig_dms.csv, sends unsent DMs via Instagram private API (instagrapi).
Saves session so you only log in once.

Usage:
  python3 dm_sender.py          # sends up to 12 DMs then stops
  python3 dm_sender.py --limit 5  # send only 5 today
"""

import csv
import os
import random
import sys
import time
from pathlib import Path

# pull scraper_state from sibling email-monster project
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "email-monster"))
try:
    from scraper_state import update as _sc
except ImportError:
    def _sc(*a, **kw): pass

from dotenv import load_dotenv
from instagrapi import Client
from instagrapi.exceptions import (
    LoginRequired,
    RateLimitError,
    UserNotFound,
    DirectThreadNotFound,
    ChallengeRequired,
)

load_dotenv()

IG_USERNAME   = os.getenv("IG_USERNAME", "")
IG_PASSWORD   = os.getenv("IG_PASSWORD", "")
IG_SESSION_ID = os.getenv("IG_SESSION_ID", "").strip()
IG_PROXY      = os.getenv("IG_PROXY", "").strip()
DMS_FILE     = "ig_dms.csv"
SESSION_FILE = "ig_session.json"
DAILY_LIMIT  = 15   # conservative — stays under Instagram's radar


# ── Session management ─────────────────────────────────────────────────────────

def get_client() -> Client:
    cl = Client()
    cl.delay_range = [2, 5]
    if IG_PROXY:
        cl.set_proxy(IG_PROXY)
        print(f"Using proxy: {IG_PROXY.split('@')[-1]}")

    # Try reusing existing session without submitting credentials
    if Path(SESSION_FILE).exists():
        print("Loading saved session...")
        cl.load_settings(SESSION_FILE)
        cl.set_settings(cl.get_settings())
        try:
            cl.get_timeline_feed()
            cl.dump_settings(SESSION_FILE)
            print(f"  Session valid — @{IG_USERNAME}")
            return cl
        except LoginRequired:
            print("  Session expired, re-authenticating...")
        except Exception as e:
            if _is_rate_limited(e):
                # Rate-limited but session is still valid — proceed anyway
                cl.dump_settings(SESSION_FILE)
                print(f"  Session OK (rate-limited on probe, proceeding) — @{IG_USERNAME}")
                return cl
            print(f"  Session check failed ({e}), re-authenticating...")

    # Session missing or expired — fall back to password login
    if not IG_USERNAME or not IG_PASSWORD:
        print("ERROR: ig_session.json is expired and no credentials set in .env.")
        print("Run: python3 login_once.py")
        raise SystemExit(1)

    print("Logging in with username/password...")
    cl.login(IG_USERNAME, IG_PASSWORD)
    cl.dump_settings(SESSION_FILE)
    print(f"  Logged in as @{IG_USERNAME}")
    # Fresh login — let Instagram settle before making requests
    print("  Warming up (30s)...")
    time.sleep(30)
    return cl


# ── CSV helpers ────────────────────────────────────────────────────────────────

def load_rows() -> list[dict]:
    with open(DMS_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_rows(rows: list[dict]):
    with open(DMS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def update_sheets(rows: list[dict]):
    try:
        from sheets_sync import push_to_sheets
        push_to_sheets(rows)
    except Exception as e:
        print(f"  Sheets update failed: {e}")


# ── Sending ────────────────────────────────────────────────────────────────────

def reauth(cl: Client) -> bool:
    """Try to recover a dead session. Returns True if successful."""
    print("  Session dropped mid-run — attempting recovery...")
    try:
        cl.login(IG_USERNAME, IG_PASSWORD)
        cl.dump_settings(SESSION_FILE)
        print("  Recovered via username/password.")
        time.sleep(30)
        return True
    except ChallengeRequired:
        print("  Instagram requires a challenge (2FA). Run: python3 login_once.py")
        return False
    except Exception as e:
        print(f"  Recovery failed: {e}")
        return False


def _is_rate_limited(e: Exception) -> bool:
    return "429" in str(e) or "too many" in str(e).lower()


def send_dm(cl: Client, handle: str, message: str) -> bool:
    """Send a DM to a handle. Returns True on success."""
    try:
        user_id = cl.user_id_from_username(handle)
    except UserNotFound:
        print(f"    @{handle} not found — skipping")
        return False
    except LoginRequired:
        if not reauth(cl):
            raise
        try:
            user_id = cl.user_id_from_username(handle)
        except Exception as e:
            print(f"    Could not resolve @{handle} after re-auth: {e}")
            return False
    except Exception as e:
        if _is_rate_limited(e):
            print("    Rate limit hit — stopping for today.")
            raise RateLimitError()
        print(f"    Could not resolve @{handle}: {e}")
        return False

    try:
        cl.direct_send(message, user_ids=[user_id])
        return True
    except RateLimitError:
        print("    Rate limit hit — stopping for today.")
        raise
    except LoginRequired:
        if not reauth(cl):
            raise
        try:
            cl.direct_send(message, user_ids=[user_id])
            return True
        except Exception as e:
            print(f"    DM failed after re-auth for @{handle}: {e}")
            return False
    except Exception as e:
        if _is_rate_limited(e):
            print("    Rate limit hit — stopping for today.")
            raise RateLimitError()
        print(f"    DM failed for @{handle}: {e}")
        return False


def human_delay(min_minutes: float = 3.0, max_minutes: float = 8.0):
    """Wait a random amount of time between DMs to look human."""
    seconds = random.uniform(min_minutes * 60, max_minutes * 60)
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    print(f"  Waiting {mins}m {secs}s before next DM...")
    time.sleep(seconds)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    # Parse --limit flag
    limit = DAILY_LIMIT
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        try:
            limit = int(sys.argv[idx + 1])
        except (IndexError, ValueError):
            pass

    if not IG_USERNAME or not IG_PASSWORD or IG_USERNAME == "your_instagram_username":
        print("ERROR: Set IG_USERNAME and IG_PASSWORD in .env before running.")
        return

    rows = load_rows()
    unsent = [r for r in rows if r.get("sent", "no").lower() == "no" and r.get("dm", "").strip()]

    if not unsent:
        print("No unsent DMs remaining. Run scraper.py to get more leads.")
        _sc("instagram", status="idle", sent=0, unsent=0)
        return

    print(f"\n=== Instagram DM Sender ===")
    print(f"Unsent leads: {len(unsent)} | Sending today: min({limit}, {len(unsent)})\n")

    total_today = min(limit, len(unsent))
    _sc("instagram", status="running", sent=0, limit=total_today,
        unsent=len(unsent), current_handle="", current=0, total=total_today,
        start_time=time.strftime("%Y-%m-%d %H:%M:%S"))

    cl = get_client()

    sent_count = 0
    rows_by_handle = {r["handle"]: r for r in rows}

    for lead in unsent[:limit]:
        handle = lead["handle"].lstrip("@")
        dm     = lead["dm"].strip()

        print(f"[{sent_count+1}/{total_today}] Sending to @{handle}...")
        _sc("instagram", current_handle=f"@{handle}", current=sent_count + 1, total=total_today)

        try:
            success = send_dm(cl, handle, dm)
        except RateLimitError:
            _sc("instagram", status="paused", sent=sent_count, note="rate limited")
            break

        if success:
            rows_by_handle[lead["handle"]]["sent"] = "yes"
            sent_count += 1
            print(f"  Sent.")
            _sc("instagram", sent=sent_count, current=sent_count, total=total_today)
            save_rows(list(rows_by_handle.values()))
            if sent_count < total_today:
                human_delay(3.0, 8.0)
        else:
            rows_by_handle[lead["handle"]]["sent"] = "skip"
            save_rows(list(rows_by_handle.values()))

    print(f"\nDone. Sent {sent_count} DMs today.")
    print("Updating Google Sheets...")
    update_sheets(list(rows_by_handle.values()))

    remaining = len([r for r in rows_by_handle.values() if r.get("sent") == "no"])
    print(f"Remaining unsent: {remaining}")
    _sc("instagram", status="done", sent=sent_count, remaining=remaining, current_handle="")


if __name__ == "__main__":
    main()
