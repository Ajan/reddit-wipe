#!/usr/bin/env python3
"""
Bulk-redact (delete) your own Reddit chat messages via the Matrix client-server API.

Reddit chat runs on Matrix (homeserver: https://matrix.redditspace.com). In Matrix
there is no "delete" -- the equivalent is *redaction*, which strips an event's
content. You can only redact events you sent, matching Reddit's own rule.

This version talks to the Matrix HTTP API directly with aiohttp instead of going
through matrix-nio. Reason: Reddit's homeserver returns /messages responses that
omit the `chunk` field, which nio's strict schema validator rejects ("'chunk' is a
required property"), killing pagination for a room and leaving its messages intact.
Raw HTTP lets us treat a missing/empty chunk as simply "end of history".

Auth: reuse an access token captured from your browser's network tab (a request to
matrix.redditspace.com/_matrix/... -> Authorization: Bearer <token>). Tokens are
short-lived; on 401 / M_UNKNOWN_TOKEN, re-capture and rerun.

Usage:
    export MATRIX_HOMESERVER="https://matrix.redditspace.com"
    export MATRIX_USER_ID="@t2_xxxxxxxx:reddit.com"
    export MATRIX_TOKEN="...."          # or omit -> prompted securely

    python redact_reddit_chat.py                       # DRY RUN (counts only)
    python redact_reddit_chat.py --execute             # redact everywhere
    python redact_reddit_chat.py --execute --room '!id:reddit.com'
    python redact_reddit_chat.py --execute --leave     # also leave+forget emptied rooms

Options:
    --execute        Actually redact (default: dry run).
    --room ROOM_ID   Limit to a room ID (repeatable).
    --reason "text"  Redaction reason recorded on each event.
    --delay 0.5      Seconds between redactions.
    --limit 100      History page size.
    --leave          After fully redacting a room, leave and forget it (removes the
                     emptied thread from your chat list). Irreversible.
"""

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from getpass import getpass
from urllib.parse import quote

try:
    import aiohttp
except ImportError:
    sys.exit("aiohttp is not installed. Run: uv pip install aiohttp  (or pip install aiohttp)")

REDACTABLE_TYPES = {"m.room.message", "m.room.encrypted", "m.sticker", "m.reaction"}
LOG_PATH = "redaction_log.jsonl"
API = "/_matrix/client/v3"


def log(record: dict) -> None:
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")


def get_credentials():
    homeserver = (os.environ.get("MATRIX_HOMESERVER")
                  or input("Homeserver URL [https://matrix.redditspace.com]: ").strip()
                  or "https://matrix.redditspace.com")
    user_id = (os.environ.get("MATRIX_USER_ID")
               or input("Your Matrix user ID (@t2_xxxx:reddit.com): ").strip())
    token = os.environ.get("MATRIX_TOKEN") or getpass("Access token (hidden): ").strip()
    if not user_id or not token:
        sys.exit("user_id and token are both required.")
    return homeserver.rstrip("/"), user_id, token


async def api_get(session, base, path, params=None):
    async with session.get(f"{base}{path}", params=params) as r:
        try:
            data = await r.json(content_type=None)
        except Exception:
            data = {"_raw": await r.text()}
        return r.status, data


async def api_put(session, base, path, body):
    async with session.put(f"{base}{path}", json=body) as r:
        try:
            data = await r.json(content_type=None)
        except Exception:
            data = {"_raw": await r.text()}
        return r.status, data


async def collect_own_events(session, base, room_id, my_id, page_limit):
    """Page backwards through a room, returning (event_id, type) you authored.

    Missing/empty `chunk` is treated as end-of-history rather than an error, which
    is the whole point of this rewrite.
    """
    own = []
    enc_room = quote(room_id, safe="")
    from_token = None
    while True:
        params = {"dir": "b", "limit": str(page_limit)}
        if from_token:
            params["from"] = from_token
        status, data = await api_get(
            session, base, f"{API}/rooms/{enc_room}/messages", params
        )
        if status != 200:
            print(f"    ! messages error in {room_id}: "
                  f"{data.get('errcode', status)} {data.get('error', '')}".rstrip())
            break
        chunk = data.get("chunk") or []
        for ev in chunk:
            if ev.get("sender") != my_id:
                continue
            if ev.get("type") not in REDACTABLE_TYPES:
                continue
            if ev.get("unsigned", {}).get("redacted_because"):
                continue
            if not ev.get("content"):  # already-redacted events carry empty content
                continue
            if "event_id" in ev:
                own.append((ev["event_id"], ev["type"]))
        end = data.get("end")
        # Stop when we run out of events or the cursor stops advancing.
        if not chunk or not end or end == from_token:
            break
        from_token = end
    return own


async def redact_one(session, base, room_id, event_id, reason):
    enc_room = quote(room_id, safe="")
    enc_event = quote(event_id, safe="")
    txn = uuid.uuid4().hex
    path = f"{API}/rooms/{enc_room}/redact/{enc_event}/{txn}"
    return await api_put(session, base, path, {"reason": reason})


async def redact_events(session, base, room_id, events, reason, delay):
    ok, fail = 0, 0
    for event_id, etype in events:
        while True:
            status, data = await redact_one(session, base, room_id, event_id, reason)
            if status == 200:
                ok += 1
                log({"ts": time.time(), "room": room_id, "event": event_id,
                     "type": etype, "result": "redacted"})
                break
            if status == 429 or data.get("errcode") == "M_LIMIT_EXCEEDED":
                wait = data.get("retry_after_ms", 5000) / 1000.0
                print(f"    rate limited, sleeping {wait:.1f}s ...")
                await asyncio.sleep(wait)
                continue
            fail += 1
            msg = f"{data.get('errcode', status)} {data.get('error', '')}".strip()
            print(f"    ! failed {event_id}: {msg}")
            log({"ts": time.time(), "room": room_id, "event": event_id,
                 "type": etype, "result": "error", "message": msg})
            break
        await asyncio.sleep(delay)
    return ok, fail


async def leave_forget(session, base, room_id):
    enc = quote(room_id, safe="")
    async with session.post(f"{base}{API}/rooms/{enc}/leave", json={}) as r:
        await r.read()
    async with session.post(f"{base}{API}/rooms/{enc}/forget", json={}) as r:
        await r.read()


async def main():
    p = argparse.ArgumentParser(description="Bulk-redact your own Reddit chat messages.")
    p.add_argument("--execute", action="store_true", help="Actually redact (default: dry run).")
    p.add_argument("--room", action="append", dest="rooms", help="Limit to room ID (repeatable).")
    p.add_argument("--reason", default="user requested deletion", help="Redaction reason.")
    p.add_argument("--delay", type=float, default=0.5, help="Seconds between redactions.")
    p.add_argument("--limit", type=int, default=100, help="History page size.")
    p.add_argument("--leave", action="store_true", help="Leave+forget rooms after redacting.")
    p.add_argument("--leave-all", action="store_true", dest="leave_all",
                   help="Leave+forget EVERY joined room without redacting first. "
                        "Clears your chat list but does NOT delete message content.")
    args = p.parse_args()

    homeserver, user_id, token = get_credentials()
    headers = {"Authorization": f"Bearer {token}"}

    async with aiohttp.ClientSession(headers=headers) as session:
        status, who = await api_get(session, homeserver, f"{API}/account/whoami")
        if status != 200:
            sys.exit(f"Token check failed: {who.get('errcode', status)} {who.get('error', '')}")
        if who.get("user_id") and who["user_id"] != user_id:
            print(f"  note: token belongs to {who['user_id']}, not {user_id}. Using token's id.")
            user_id = who["user_id"]
        print(f"Authenticated as {user_id} on {homeserver}")

        status, jr = await api_get(session, homeserver, f"{API}/joined_rooms")
        if status != 200:
            sys.exit(f"Could not list rooms: {jr.get('errcode', status)}")
        rooms = args.rooms or jr.get("joined_rooms", [])
        print(f"{len(rooms)} room(s) to scan.\n")

        # Standalone mode: just clear the chat list, no redaction.
        if args.leave_all:
            print("LEAVE-ALL: this removes every room from your list but does NOT")
            print("delete message content (other members can still read what you sent).")
            if not args.execute:
                for room_id in rooms:
                    print(f"  would leave + forget {room_id}")
                print("\nDRY RUN -- nothing left. Re-run with --execute --leave-all.")
                return
            confirm = input(f"\nType LEAVE to leave+forget all {len(rooms)} rooms: ").strip()
            if confirm != "LEAVE":
                print("Aborted.")
                return
            for room_id in rooms:
                print(f"  leaving + forgetting {room_id}")
                await leave_forget(session, homeserver, room_id)
                log({"ts": time.time(), "room": room_id, "result": "left"})
            print(f"\nLeft {len(rooms)} rooms. Log: {LOG_PATH}")
            return

        plan, grand_total = {}, 0
        for room_id in rooms:
            own = await collect_own_events(session, homeserver, room_id, user_id, args.limit)
            plan[room_id] = own
            grand_total += len(own)
            print(f"  {room_id}: {len(own)} of your messages")

        print(f"\nTotal of your messages found: {grand_total}")

        if not args.execute:
            print("\nDRY RUN -- nothing deleted. Re-run with --execute to redact the above.")
            return

        confirm = input(f"\nType DELETE to redact all {grand_total} messages: ").strip()
        if confirm != "DELETE":
            print("Aborted.")
            return

        total_ok, total_fail = 0, 0
        for room_id, events in plan.items():
            if events:
                print(f"\nRedacting {len(events)} in {room_id} ...")
                ok, fail = await redact_events(session, homeserver, room_id, events,
                                               args.reason, args.delay)
                total_ok += ok
                total_fail += fail
                print(f"  done: {ok} redacted, {fail} failed")
            if args.leave and not (events and fail):
                print(f"  leaving + forgetting {room_id}")
                await leave_forget(session, homeserver, room_id)

        print(f"\nFinished: {total_ok} redacted, {total_fail} failed. Log: {LOG_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
