# reddit-wipe

Bulk-delete **your own** Reddit chat messages and comments from the command line.
Dry-run by default, deletes only what you authored, and logs every action.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)

---

## Why two tools?

Reddit chat and Reddit comments live on completely different backends, so each
needs its own script and its own token:

| Tool | What it deletes | Backend |
|------|-----------------|---------|
| `redact_reddit_chat.py` | Your messages in Reddit chat | Matrix (`matrix.redditspace.com`) |
| `delete_reddit_comments.py` | Your comments | Reddit Data API (`oauth.reddit.com`) |

Reddit chat runs on Matrix, where "delete" is called **redaction** — it strips a
message's content. Comments use Reddit's OAuth Data API. The two tokens are
**not** interchangeable.

## Features

- **Dry run by default** — every tool counts and previews before touching
  anything. You opt into destruction with `--execute` and a typed confirmation.
- **Only your own content** — enforced server-side by both Reddit and Matrix.
- **Optional overwrite** — scrub comment text to a placeholder before deleting,
  to defeat archive mirrors.
- **Handles the ~1000-comment cap** — feed a Reddit data-export CSV to reach
  everything on older accounts.
- **Clear the chat list** — `--leave` / `--leave-all` drop emptied threads.
- **Rate-limit aware** — honors `Retry-After` / `X-Ratelimit-*` and backs off.
- **Audit log** — every action is appended to a `*_log.jsonl` file.

> ⚠️ **Deletion is irreversible.** For chat, redaction removes the message for
> *everyone* in the conversation, not just your view. Always run the dry run
> first.

## Requirements

- Python 3.9+
- [`aiohttp`](https://pypi.org/project/aiohttp/)

```bash
pip install aiohttp        # or: uv pip install aiohttp
```

## Getting your tokens

Both scripts authenticate with a token you copy out of your own logged-in
browser session — no passwords, nothing stored remotely. Full step-by-step
instructions (with screenshots of where to look in devtools) are in
**[GETTING_TOKENS.md](GETTING_TOKENS.md)**.

Short version:
- **Chat:** copy the `Authorization: Bearer` value from any
  `matrix.redditspace.com` request, and get your user ID from `whoami`.
- **Comments:** copy the bearer (`token_v2`) from any `gql.reddit.com` request.

Tokens are short-lived (~1 hour). On a `401` / `M_UNKNOWN_TOKEN`, re-capture and
rerun.

---

## Usage — chat

```bash
export MATRIX_HOMESERVER="https://matrix.redditspace.com"
export MATRIX_USER_ID="@t2_xxxxxxxx:reddit.com"
export MATRIX_TOKEN="...your matrix token..."

python redact_reddit_chat.py                       # dry run: count your messages per room
python redact_reddit_chat.py --execute             # redact everywhere
python redact_reddit_chat.py --execute --room '!roomid:reddit.com'   # one room
python redact_reddit_chat.py --execute --leave     # redact, then drop emptied threads
python redact_reddit_chat.py --execute --leave-all # just leave every room (no redaction)
```

| Flag | Description |
|------|-------------|
| `--execute` | Actually redact (default: dry run). |
| `--room ID` | Limit to a room ID (repeatable). |
| `--leave` | Leave + forget each room **after** its messages are redacted. |
| `--leave-all` | Leave + forget every joined room without redacting. Clears your chat list but does **not** delete message content. |
| `--reason STR` | Redaction reason recorded on each event. |
| `--delay SEC` | Seconds between redactions (default `0.5`). |
| `--limit N` | History page size (default `100`). |

> **Order matters:** leaving a room usually forfeits your ability to redact in
> it. If you want both, redact first — which is exactly what `--leave` does.

## Usage — comments

```bash
export REDDIT_TOKEN="...your token_v2 / bearer value..."
# REDDIT_USERNAME is auto-detected via /api/v1/me; set it only to override.

python delete_reddit_comments.py                       # dry run: count comments
python delete_reddit_comments.py --execute             # delete
python delete_reddit_comments.py --execute --overwrite # scrub text, then delete
python delete_reddit_comments.py --execute --ids-file comments.csv  # everything, via export
```

| Flag | Description |
|------|-------------|
| `--execute` | Actually delete (default: dry run). |
| `--overwrite` | Edit each comment to a placeholder before deleting. |
| `--placeholder STR` | Text used by `--overwrite` (default: `.`). |
| `--ids-file PATH` | Read `t1_` IDs or a Reddit data-export `comments.csv` and delete those instead of crawling the listing. |
| `--delay SEC` | Seconds between write actions (default `1.0`). |
| `--limit N` | Listing page size, max 100 (default `100`). |

### Reaching every comment (the ~1000 cap)

Reddit's listing API only pages back through roughly your **last 1000 comments**.
For older accounts, request your data export at
[reddit.com/settings/data-request](https://www.reddit.com/settings/data-request),
then pass the resulting `comments.csv` via `--ids-file` to delete everything.

## Logs

Each run appends newline-delimited JSON to a log file
(`redaction_log.jsonl`, `comment_deletion_log.jsonl`) recording every
redaction/deletion and any errors. These are gitignored — they contain
room/event/comment IDs.

## Troubleshooting

A few common ones (full list in [GETTING_TOKENS.md](GETTING_TOKENS.md)):

- **No `oauth.reddit.com` requests in devtools** → use a `gql.reddit.com`
  request; the bearer is the same.
- **`'chunk' is a required property`** → you're on an old version; the current
  chat script talks to the Matrix HTTP API directly to avoid this.
- **Redacted chats still show in your list** → use `--leave` or `--leave-all`.
- **`401` mid-run** → token expired; re-capture and rerun.

## Disclaimer

This project automates self-service deletion that Reddit already offers manually.
It acts **only on content you authored** (enforced server-side) and relies on
**undocumented internal endpoints** that Reddit may change or remove without
notice. Use it on your own account, at your own risk. Provided as-is, with no
warranty — see [LICENSE](LICENSE).

## Contributing

Issues and PRs welcome — especially if an endpoint shape changes and a capture
step in `GETTING_TOKENS.md` no longer matches reality. Please never include real
tokens, cookies, or exported data in issues or commits.

## License

[MIT](LICENSE) © 2026 Alig1493
