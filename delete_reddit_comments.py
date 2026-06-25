#!/usr/bin/env python3
"""
Bulk-delete (optionally overwrite-then-delete) your own Reddit COMMENTS.

This is a SEPARATE tool from the chat redactor. Comments live on Reddit's OAuth
Data API (oauth.reddit.com), not on Matrix. Different host, different token,
different IDs (t1_xxxx fullnames).

AUTH (no app registration needed):
  Reddit's own web client authenticates its calls to oauth.reddit.com with a
  bearer token. Capture it the same way you got the Matrix token:
    1. Log into reddit.com in a desktop browser.
    2. Open devtools -> Network, tick "Preserve log".
    3. Filter for `oauth.reddit.com` (browse a bit to generate traffic).
    4. Open any such request -> Request Headers -> copy the
       `Authorization: Bearer ...` value. That's REDDIT_TOKEN.
  These tokens are short-lived (~1 hour). On 401, re-capture and rerun.

  If you instead have a registered script app (client_id/secret) from before
  Reddit tightened access, PRAW is the more durable route -- ask and I'll give
  you that variant. This script uses the captured-token approach to avoid the
  app-registration question entirely.

THE ~1000 CAP:
  Reddit's listing API only pages back through ~1000 of your recent comments.
  To delete everything on an older account, request your data export at
  reddit.com/settings/data-request, then pass its comments.csv via --ids-file.
  The script will delete every ID in that file (and skip the listing crawl).

Usage:
    export REDDIT_TOKEN="...bearer..."
    # username is auto-detected via /api/v1/me, or set it:
    export REDDIT_USERNAME="your_username"

    python delete_reddit_comments.py                      # DRY RUN (lists/counts)
    python delete_reddit_comments.py --execute            # delete
    python delete_reddit_comments.py --execute --overwrite
    python delete_reddit_comments.py --execute --ids-file comments.csv

Options:
    --execute          Actually delete (default: dry run).
    --overwrite        Edit each comment to a placeholder before deleting.
    --placeholder STR  Text used by --overwrite (default: ".").
    --ids-file PATH    Read t1_ IDs (or a Reddit data-export comments.csv) and
                       delete those instead of crawling the listing.
    --delay 1.0        Seconds between write actions.
    --limit 100        Listing page size (max 100).
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
from getpass import getpass

try:
    import aiohttp
except ImportError:
    sys.exit("aiohttp is not installed. Run: uv pip install aiohttp  (or pip install aiohttp)")

OAUTH = "https://oauth.reddit.com"
LOG_PATH = "comment_deletion_log.jsonl"
# Reddit blocks generic/default User-Agents; send a descriptive one.
USER_AGENT = "python:bulk-comment-cleaner:v1.0 (personal use)"
ID_RE = re.compile(r"(t1_[a-z0-9]+)", re.IGNORECASE)


def log(record: dict) -> None:
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def get_credentials():
    token = os.environ.get("REDDIT_TOKEN") or getpass("Reddit bearer token (hidden): ").strip()
    if not token:
        sys.exit("REDDIT_TOKEN is required.")
    username = os.environ.get("REDDIT_USERNAME", "").strip()
    return token, username


def headers(token):
    return {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}


async def api_get(session, url, params=None):
    async with session.get(url, params=params) as r:
        txt = await r.text()
        try:
            data = json.loads(txt)
        except Exception:
            data = {"_raw": txt}
        return r.status, data, r.headers


async def api_post(session, url, data):
    async with session.post(url, data=data) as r:
        txt = await r.text()
        try:
            body = json.loads(txt)
        except Exception:
            body = {"_raw": txt}
        return r.status, body, r.headers


async def respect_ratelimit(resp_headers):
    """If we're near the limit, sleep until the window resets."""
    try:
        remaining = float(resp_headers.get("X-Ratelimit-Remaining", "1"))
        reset = float(resp_headers.get("X-Ratelimit-Reset", "0"))
    except ValueError:
        return
    if remaining <= 1 and reset > 0:
        print(f"    near rate limit, sleeping {reset:.0f}s for reset ...")
        await asyncio.sleep(reset)


async def whoami(session):
    status, data, _ = await api_get(session, f"{OAUTH}/api/v1/me")
    if status != 200:
        return None
    return data.get("name")


async def crawl_comment_ids(session, username, page_limit):
    """Page through /user/{name}/comments, yielding (fullname, body)."""
    out = []
    after = None
    while True:
        params = {"limit": str(page_limit), "raw_json": "1"}
        if after:
            params["after"] = after
        status, data, h = await api_get(
            session, f"{OAUTH}/user/{username}/comments", params
        )
        if status != 200:
            print(f"  ! listing error: {status} {data.get('message', data.get('_raw',''))}")
            break
        children = data.get("data", {}).get("children", [])
        for c in children:
            d = c.get("data", {})
            if d.get("name"):
                out.append((d["name"], d.get("body", "")))
        after = data.get("data", {}).get("after")
        await respect_ratelimit(h)
        if not after or not children:
            break
    return out


def load_ids_file(path):
    """Accept a plain list of t1_ IDs or a Reddit data-export comments.csv."""
    ids = []
    with open(path, newline="", encoding="utf-8") as f:
        sample = f.read()
    # Find every t1_ fullname; also accept bare base36 ids in an 'id' CSV column.
    found = ID_RE.findall(sample)
    if found:
        ids = list(dict.fromkeys(found))  # de-dupe, preserve order
    else:
        # Try CSV with an 'id' column (export format), prefixing t1_.
        for row in csv.DictReader(sample.splitlines()):
            rid = (row.get("id") or "").strip()
            if rid:
                ids.append(rid if rid.startswith("t1_") else f"t1_{rid}")
    return [(i, None) for i in ids]


async def edit_comment(session, fullname, text):
    return await api_post(session, f"{OAUTH}/api/editusertext",
                          {"api_type": "json", "thing_id": fullname, "text": text})


async def delete_comment(session, fullname):
    return await api_post(session, f"{OAUTH}/api/del", {"id": fullname})


async def process(session, items, args):
    ok, fail = 0, 0
    for fullname, body in items:
        # Optional overwrite first (best-effort; failure doesn't block delete).
        if args.overwrite:
            es, eb, eh = await edit_comment(session, fullname, args.placeholder)
            await respect_ratelimit(eh)
            if es != 200:
                print(f"    ~ overwrite failed for {fullname}: {es}")
            await asyncio.sleep(args.delay)

        while True:
            ds, db, dh = await delete_comment(session, fullname)
            if ds == 200:
                ok += 1
                log({"ts": time.time(), "id": fullname, "result": "deleted",
                     "overwritten": bool(args.overwrite)})
                break
            if ds == 429:
                retry = float(dh.get("Retry-After", "5"))
                print(f"    rate limited, sleeping {retry:.0f}s ...")
                await asyncio.sleep(retry)
                continue
            fail += 1
            msg = db.get("message", db.get("_raw", ds))
            print(f"    ! delete failed for {fullname}: {msg}")
            log({"ts": time.time(), "id": fullname, "result": "error", "message": str(msg)})
            break
        await respect_ratelimit(dh)
        await asyncio.sleep(args.delay)
    return ok, fail


async def main():
    p = argparse.ArgumentParser(description="Bulk-delete your Reddit comments.")
    p.add_argument("--execute", action="store_true", help="Actually delete (default: dry run).")
    p.add_argument("--overwrite", action="store_true", help="Overwrite text before deleting.")
    p.add_argument("--placeholder", default=".", help="Overwrite text (default: '.').")
    p.add_argument("--ids-file", dest="ids_file", help="t1_ IDs or export comments.csv.")
    p.add_argument("--delay", type=float, default=1.0, help="Seconds between write actions.")
    p.add_argument("--limit", type=int, default=100, help="Listing page size (max 100).")
    args = p.parse_args()

    token, username = get_credentials()

    async with aiohttp.ClientSession(headers=headers(token)) as session:
        who = await whoami(session)
        if not who:
            sys.exit("Token check failed (/api/v1/me). Re-capture a fresh bearer token.")
        if username and username.lower() != who.lower():
            print(f"  note: token belongs to u/{who}, not u/{username}. Using u/{who}.")
        username = who
        print(f"Authenticated as u/{username}")

        if args.ids_file:
            items = load_ids_file(args.ids_file)
            print(f"Loaded {len(items)} comment IDs from {args.ids_file}")
        else:
            print("Crawling your comment history (listing API, ~1000 cap) ...")
            items = await crawl_comment_ids(session, username, min(args.limit, 100))
            print(f"Found {len(items)} comments via listing.")
            if len(items) >= 1000:
                print("  (hit the ~1000 listing cap -- use --ids-file with your data "
                      "export to reach older comments.)")

        if not items:
            print("Nothing to do.")
            return

        if not args.execute:
            print(f"\nDRY RUN -- would {'overwrite+delete' if args.overwrite else 'delete'} "
                  f"{len(items)} comments. Re-run with --execute.")
            return

        verb = "overwrite+delete" if args.overwrite else "delete"
        confirm = input(f"\nType DELETE to {verb} {len(items)} comments: ").strip()
        if confirm != "DELETE":
            print("Aborted.")
            return

        ok, fail = await process(session, items, args)
        print(f"\nFinished: {ok} deleted, {fail} failed. Log: {LOG_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
