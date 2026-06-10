#!/usr/bin/env python3
"""
Interactive tool to mark DMs as sent/replied in ig_dms.csv.
Run after sending DMs to keep track of progress.

Usage:
  python3 mark_sent.py sent @handle
  python3 mark_sent.py replied @handle
  python3 mark_sent.py stats
"""

import csv
import sys
import os

DMS_FILE = "ig_dms.csv"


def load_rows():
    if not os.path.exists(DMS_FILE):
        print(f"{DMS_FILE} not found. Run scraper.py first.")
        sys.exit(1)
    with open(DMS_FILE, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_rows(rows):
    if not rows:
        return
    with open(DMS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def mark(action, handle):
    handle = handle.lstrip("@")
    rows = load_rows()
    found = False
    for row in rows:
        if row["handle"].lower() == handle.lower():
            row[action] = "yes"
            found = True
            break
    if found:
        save_rows(rows)
        print(f"Marked @{handle} as {action}=yes")
    else:
        print(f"Handle @{handle} not found in {DMS_FILE}")


def stats():
    rows = load_rows()
    total = len(rows)
    sent = sum(1 for r in rows if r.get("sent") == "yes")
    replied = sum(1 for r in rows if r.get("replied") == "yes")
    unsent = total - sent
    print(f"Total leads : {total}")
    print(f"DMs sent    : {sent}")
    print(f"Replied     : {replied}")
    print(f"Not sent yet: {unsent}")
    if sent > 0:
        print(f"Reply rate  : {replied/sent*100:.1f}%")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "stats":
        stats()
    elif len(args) == 2 and args[0] in ("sent", "replied"):
        mark(args[0], args[1])
    else:
        print("Usage:")
        print("  python3 mark_sent.py stats")
        print("  python3 mark_sent.py sent @handle")
        print("  python3 mark_sent.py replied @handle")
