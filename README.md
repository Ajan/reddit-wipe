# reddit-wipe

Bulk-delete **your own** Reddit comments from the command line — one command,
with a live progress bar, and without copying tokens manually.

```
[████████████░░░░░░░░░░░░░░░░░░] 210/501  42%  ✓209 ✗1  ETA 14m  ⏸ rate-limit 4:51
```

- **Dry run by default** — see what would be deleted before anything changes.
- **Only your own content** — Reddit enforces this server-side.
- **Overwrite, then delete** — scrubs each comment's text first, so archive
  sites that re-scrape edits pick up the blank version.
- **Finds your login token automatically** from Chrome (or clipboard / a file).
- **Safe to stop and resume** — Ctrl + C anytime; rerun to finish the rest.

Built on [Alig1493/redact-reddit](https://github.com/Alig1493/redact-reddit),
which does the actual deleting. This repo adds `wipe.py`, an easier front end.

> ⚠️ **Deletion is permanent.** If you want a copy of your comments, request your
> data export at [reddit.com/settings/data-request](https://www.reddit.com/settings/data-request)
> *before* you start.

---

## Quick start

You need Python 3.9 or newer.

### 1. Download and install (once)

**macOS / Linux**
```bash
git clone https://github.com/Ajan/reddit-wipe.git
cd reddit-wipe
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell)**
```powershell
git clone https://github.com/Ajan/reddit-wipe.git
cd reddit-wipe
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 2. Log into reddit.com in Chrome

That's it — `wipe.py` reads your login token from Chrome. On macOS, the first
run shows a Keychain prompt for **"Chrome Safe Storage"**; click **Allow**.

### 3. Dry run (changes nothing)

```bash
python wipe.py --overwrite
```

Check the username and comment count it prints:

```
Authenticated as u/yourname
Found 501 comments via listing.
DRY RUN -- would overwrite+delete 501 comments. Re-run with --execute.
```

### 4. Delete for real

```bash
python wipe.py --execute --overwrite
```

Type `DELETE` when asked. Expect roughly **5 minutes per 50 comments** with `--overwrite` — Reddit
rate-limits deletions, and the bar shows a countdown during each pause.

---

## If Chrome doesn't work

Recent Chrome on **Windows** blocks other programs from reading its cookies, and
some setups (other browsers, profiles) won't match either. `wipe.py` then falls
back to:

1. **`token.txt`** in this folder, or
2. **your clipboard**.

To get the token by hand:

1. On reddit.com (logged in), open DevTools — **Cmd + Option + I** (Mac) or
   **Ctrl + Shift + I** (Windows).
2. Go to **Application → Cookies → https://www.reddit.com**.
3. Click the **`token_v2`** row and copy its full value (starts with `eyJ`).
4. Either keep it on your clipboard, or paste it into `token.txt` — then run
   `wipe.py` as above.

**Delete `token.txt` when you're done** — it's a live login token. (It's in
`.gitignore`, so it won't be committed by accident.)

More detail and screenshots: [GETTING_TOKENS.md](GETTING_TOKENS.md).

---

## Options

Everything after `wipe.py` is passed to the deleter:

| Flag | What it does |
| --- | --- |
| `--execute` | Actually delete (default is a dry run). |
| `--overwrite` | Replace each comment's text before deleting it. |
| `--placeholder TEXT` | Text used by `--overwrite` (default: `.`). |
| `--ids-file comments.csv` | Delete the comments listed in your Reddit data export. |
| `--delay SEC` | Pause between actions (default `1.0`). |

### More than ~1000 comments?

Reddit's listing only goes back about 1000 comments. Either:

- run `wipe.py` again after the first pass — older comments then appear, or
- use your data export: `python wipe.py --execute --overwrite --ids-file comments.csv`

---

## Troubleshooting

| You see | Do this |
| --- | --- |
| `No token found` | Open reddit.com in Chrome while logged in, or use the manual steps above. |
| `Token check failed` / `401` | The token expired (they last ~1 hour). Refresh reddit.com and rerun. |
| `⏸ rate-limit` in the bar | Normal. It waits and continues on its own. |
| Comments still visible on your profile | Reddit caches profiles; check again in a few minutes, or do a dry run. |

Every action is recorded in `comment_deletion_log.jsonl` (ignored by git).

---

## Reddit chat

To remove your Reddit **chat** messages, use `redact_reddit_chat.py` directly —
see [the upstream instructions](https://github.com/Alig1493/redact-reddit#usage--chat).
`wipe.py` handles comments only.

## Privacy

- Your token is used only to talk to `oauth.reddit.com`. It's never printed,
  logged or sent anywhere else.
- `wipe.py` reads only the `token_v2` cookie for `reddit.com` from Chrome.
- Nothing is uploaded. Logs stay on your machine and are ignored by git.

## Disclaimer

This automates deletion Reddit already lets you do by hand. It relies on
endpoints Reddit may change. Use it on your own account, at your own risk.
Provided as-is with no warranty.

## License

MIT — see [LICENSE](LICENSE). Original deletion scripts © Alig1493.
