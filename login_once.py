#!/usr/bin/env python3
"""
Run this ONCE from a trusted IP (phone hotspot, home WiFi, etc.)
to generate ig_session.json. After that, dm_sender.py uses the
saved session and won't need fresh credentials for weeks.
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from instagrapi import Client

load_dotenv()

USERNAME = os.getenv("IG_USERNAME")
PASSWORD = os.getenv("IG_PASSWORD")

def challenge_code_handler(username, choice):
    print(f"\nInstagram sent a verification code to your phone/email.")
    return input("Enter the code: ").strip()

cl = Client()
cl.challenge_code_handler = challenge_code_handler

SESSION_FILE = "ig_session.json"

if Path(SESSION_FILE).exists():
    print("Found existing session, checking if still valid...")
    cl.load_settings(SESSION_FILE)
    cl.set_settings(cl.get_settings())
    try:
        cl.get_timeline_feed()
        cl.dump_settings(SESSION_FILE)
        info = cl.account_info()
        print(f"\nSession still valid — @{info.username}. No re-login needed.")
        raise SystemExit(0)
    except Exception:
        print("  Session expired, doing fresh login...")

print(f"Logging in as @{USERNAME}...")
cl.login(USERNAME, PASSWORD)
cl.dump_settings(SESSION_FILE)

info = cl.account_info()
print(f"\nSuccess! Logged in as @{info.username}")
print("ig_session.json saved — dm_sender.py will use this for all future runs.")
