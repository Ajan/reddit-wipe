# Getting your tokens

Both scripts act on **your own account** using a credential you copy out of your
own logged-in browser session. Nothing here logs in for you, stores anything
remotely, or touches anyone else's data — you capture a token, paste it into an
environment variable, and the script uses it locally.

There are **two different tokens** for the two different jobs, because Reddit
chat and Reddit comments run on completely different backends:

| Job | Backend | Token source |
|-----|---------|--------------|
| Delete chat messages | Matrix (`matrix.redditspace.com`) | `Authorization: Bearer` on a Matrix request |
| Delete comments | Reddit Data API (`oauth.reddit.com`) | `token_v2` bearer from a GraphQL request |

They are **not** interchangeable. The Matrix token will not work for comments and
vice-versa.

---

## ⚠️ Read this first

- **You can only delete content you authored.** Both Reddit and Matrix enforce
  this server-side. The scripts can't remove other people's messages.
- **Deletion is irreversible.** For chat, redaction also removes the message for
  *everyone* in the conversation, not just your view. Always do the dry run first.
- **These tokens are secrets.** Anyone holding one can act as you until it
  expires. Never commit them, never paste them into a file that gets pushed, and
  prefer the hidden prompt or an environment variable over command-line args
  (which leak into shell history and the process list).
- **Tokens are short-lived** (roughly an hour). If a run dies with a `401` /
  `M_UNKNOWN_TOKEN`, just re-capture a fresh one and rerun.
- **These are undocumented, internal endpoints.** Reddit can change them without
  notice. If a capture step doesn't match what's described here, that's the
  signal the flow has shifted — open an issue.

---

## 1. Matrix token (for chat deletion)

Reddit chat is a Matrix client talking to the homeserver at
`https://matrix.redditspace.com`. You need three values: the **homeserver URL**
(constant), your **access token**, and your **Matrix user ID**.

### Capture the access token

1. Open Reddit chat in a **desktop browser** and open a conversation so the chat
   UI is actually loaded.
2. Open developer tools (`F12`) → **Network** tab. Enable **Preserve log** so
   requests don't clear as you navigate.
3. In the filter box, type `redditspace` (or `_matrix`) to isolate chat-backend
   traffic. If the list is empty, send or open a message to generate a request.
4. Click any request going to `matrix.redditspace.com/_matrix/...`, open
   **Headers → Request Headers**, and copy the value after
   `Authorization: Bearer ` — that's your token.

### Get your Matrix user ID

The easiest way is to ask the server, using the token you just copied:

```bash
curl -s -H "Authorization: Bearer YOUR_MATRIX_TOKEN" \
  https://matrix.redditspace.com/_matrix/client/v3/account/whoami
```

The response contains your ID in the form `@t2_xxxxxxxx:reddit.com`. A successful
response also proves the token is live.

> Alternatively you can read it straight from devtools: it appears URL-encoded in
> request paths (`@t2_...%3Areddit.com`, where `%3A` is `:`), and as the `sender`
> field on your own events in a `/sync` response.

### Export and run

```bash
export MATRIX_HOMESERVER="https://matrix.redditspace.com"
export MATRIX_USER_ID="@t2_xxxxxxxx:reddit.com"
export MATRIX_TOKEN="...your token..."

python redact_reddit_chat.py        # dry run — counts only, deletes nothing
```

---

## 2. Comments token (for comment deletion)

Comments live on Reddit's OAuth Data API (`oauth.reddit.com`). Reddit's own web
client authenticates its calls with a bearer token whose value is stored in the
`token_v2` cookie. New Reddit routes most traffic through GraphQL
(`gql.reddit.com`), and the bearer on those requests is the same token — it works
against the REST endpoints the script uses.

### Capture the bearer from a GraphQL request

1. Log into **reddit.com** in a desktop browser (the default site, not
   `old.reddit.com`).
2. Open developer tools (`F12`) → **Network** tab, enable **Preserve log**.
3. Filter for `gql.reddit.com`. Browse your feed or open your profile to generate
   requests if the list is empty.
4. Click any `gql.reddit.com` request → **Headers → Request Headers** → copy the
   value after `Authorization: Bearer `. This is the `token_v2` value, and it's
   your `REDDIT_TOKEN`.

> You can also read the same value from **Application → Cookies →
> `https://www.reddit.com` → `token_v2`**. Copy the **header** value, not the
> session cookie — the script authenticates with the bearer, not the cookie.

### Export and run

```bash
export REDDIT_TOKEN="...the token_v2 / bearer value..."

python delete_reddit_comments.py    # dry run — auto-detects your username, counts
```

The script calls `/api/v1/me` first, so you'll know in one request whether the
token authenticates against REST. If it prints `Authenticated as u/...`, you're
set.

### The ~1000-comment cap

Reddit's listing API only pages back through roughly your **last 1000 comments**.
For an older account, request your data export at
[reddit.com/settings/data-request](https://www.reddit.com/settings/data-request),
then feed the resulting `comments.csv` to the script to reach everything:

```bash
python delete_reddit_comments.py --execute --ids-file comments.csv
```

---

## Troubleshooting

**`No oauth.reddit.com requests appear.`** Use the `gql.reddit.com` requests
instead — the bearer is identical. (Section 2 above.)

**`/api/v1/me` returns 401/403 with a fresh token.** The token may be fenced to
GraphQL-only in your account. The durable alternative is a registered **script**
app via the OAuth authorization-code flow (no password needed; one browser
approval yields a refresh token). See `OAUTH_APP.md` *(if you add that variant)*.

**`'chunk' is a required property` (chat).** This came from `matrix-nio`'s strict
schema validator rejecting Reddit's non-standard `/messages` responses. The
current script talks to the Matrix HTTP API directly to avoid it — make sure
you're on the latest version.

**Redacted chats still appear in your list.** Redaction empties a thread but
doesn't remove it. Use `--leave` (after redacting) or `--leave-all` to drop the
emptied threads from your chat list.

---

## Security checklist before you push

- [ ] No tokens, cookies, `client_secret`, or `comments.csv` committed
      (add them to `.gitignore`).
- [ ] Log files (`*_log.jsonl`) gitignored — they contain room/event IDs.
- [ ] README states clearly that this uses undocumented endpoints and may break.
- [ ] No hardcoded credentials anywhere in the scripts; all via env vars.
