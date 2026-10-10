# Xporter

Export the **complete follower list of any public X (Twitter) account** to CSV +
JSONL. Handles accounts of any size (tested on 20,000+ followers).
 

> [!WARNING]
> The two cookies you provide give the script * are personal and shouldn't be shared publicly.
> Never share them. Rotate the session after heavy use
> (X → Settings → Security and access → Log out of all other sessions).
> Using this script may violate X's Terms of Service , you are responsible for
> how you use it. Public data only; protected accounts cannot be exported.

## Requirements

Python 3.8+ and an X account you are logged into. That's all.

## Getting your session cookies (once per account)

1. Log into [x.com](https://x.com) in your browser.
2. Open DevTools (**F12**) → **Application** tab (Chrome/Edge) or **Storage**
   (Firefox) → **Cookies** → `https://x.com`.
3. Copy the **Value** of two cookies:
   - `auth_token` - 40-character hex string
   - `ct0` -  long hex string (may end in `%0A`)
  
## Video Tut

https://github.com/user-attachments/assets/39842be6-5c4c-4f5d-83fe-69e7760279b2

## Usage

```bash
# Interactive , the script asks for the two values itself
python3 x_follower_export.py --target @anyhandle

# Non-interactive , pass the session as an argument
python3 x_follower_export.py --target @anyhandle \
    --cookie "auth_token=...; ct0=..."

# Quick sanity check: session + one page, then exit (~5 seconds)
python3 x_follower_export.py --target @anyhandle --probe \
    --cookie "auth_token=...; ct0=..."

# Stop after N followers (0 or omitted = everything)
python3 x_follower_export.py --target @anyhandle --max 500 \
    --cookie "auth_token=...; ct0=..."
```

### Speed up large exports with multiple sessions

Rate limits are per account (~50 requests / 15 min). Put one session per line:

```bash
# cookies.txt
auth_token=AAA...; ct0=AAA...
auth_token=BBB...; ct0=BBB...
```

```bash
python3 x_follower_export.py --target @anyhandle --cookie-file cookies.txt
```

N sessions ≈ N× speed. Rough numbers: 20,000 followers ≈ 2–3 h with one
session, ≈ 30–40 min with four.

### All options

| Flag | Meaning |
|---|---|
| `--target @handle` | account to export (required; `@` optional) |
| `--cookie "..."` | single session: `auth_token=X; ct0=Y` |
| `--cookie-file FILE` | one session per line (multi-account rotation) |
| `--probe` | test the session with one page, then exit |
| `--max N` | stop after N followers (default: all) |
| `--out DIR` | output directory (default: `./followers_<handle>`) |
| `--page-size {50,100,200}` | users requested per page (X caps actual page size at ~50–70) |

No TTY (cron, pipes)? Then `--cookie` or `--cookie-file` is required ,
the interactive prompt is only shown in a real terminal.

## Output

```
followers_<handle>/
├── followers.csv     # spreadsheet-ready, one row per follower
├── followers.jsonl   # same data, one JSON object per line
└── state.json        # resume checkpoint (cursor + collected count)
```

Columns: `user_id, screen_name, name, location, bio, website, followers_count,
following_count, tweets_count, account_created_at, is_blue_verified, protected, avatar`

Interrupted? **Ctrl+C is always safe** , progress is flushed after every page.
Rerun the exact same command and it resumes from the saved cursor; if the
export already finished, rerunning detects that and does nothing.

## How it works

The script calls X's internal GraphQL API , the same one the x.com web client
uses , authenticated with your two session cookies. Two operations matter, and
their `queryId`s were extracted from X's own `client-web/main.<hash>.js` bundle:

| Operation | queryId (verified 2026-10) |
|---|---|
| `UserByScreenName` | `AMIBMjtxEEATh4z8V9GtRg` |
| `Followers` | `NPvSAR1p8XUWh8J6PeP3-g` |

Plus the operation's feature-switch list (the `FEATURE_SWITCHES` constant).

### When X rotates the queryIds or features

Errors will mention an unknown queryId or features. To re-extract:

1. While logged into x.com, view the page source and find the script tag:
   `src=".../responsive-web/client-web/main.<hash>.js"`
2. Download that bundle and search around the operation name, e.g.:
   `grep -aoE '.{120}operationName:"Followers"' main.js`
3. Update `FOLLOWERS_QID`, `USER_BY_SCREEN_NAME_QID`, and
   `FEATURE_SWITCHES` in the script.

## Tested on

Linux + Python 3.14, October 2026 , full export of a 20,700-follower account,
resumable after interruption, multi-session rotation, invalid-session detection.
