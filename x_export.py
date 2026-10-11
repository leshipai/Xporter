#!/usr/bin/env python3
import argparse
import csv
import gzip
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

BEARER = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"

USER_BY_SCREEN_NAME_QID = "AMIBMjtxEEATh4z8V9GtRg"
FOLLOWERS_QID = "NPvSAR1p8XUWh8J6PeP3-g"
FOLLOWING_QID = "nyTOiXy603sofPjdrXYL9Q"
FEATURE_SWITCHES = [
    "rweb_video_screen_enabled", "rweb_cashtags_enabled",
    "profile_label_improvements_pcf_label_in_post_enabled",
    "responsive_web_profile_redirect_enabled", "rweb_tipjar_consumption_enabled",
    "verified_phone_label_enabled", "creator_subscriptions_tweet_preview_api_enabled",
    "responsive_web_graphql_timeline_navigation_enabled", "premium_content_api_read_enabled",
    "communities_web_enable_tweet_community_results_fetch",
    "c9s_tweet_anatomy_moderator_badge_enabled",
    "responsive_web_grok_analyze_button_fetch_trends_enabled",
    "responsive_web_grok_analyze_post_followups_enabled",
    "rweb_cashtags_composer_attachment_enabled", "responsive_web_jetfuel_frame",
    "rweb_sports_post_context_enabled", "responsive_web_grok_share_attachment_enabled",
    "responsive_web_grok_annotations_enabled", "articles_preview_enabled",
    "responsive_web_edit_tweet_api_enabled", "rweb_conversational_replies_downvote_enabled",
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled",
    "view_counts_everywhere_api_enabled", "longform_notetweets_consumption_enabled",
    "responsive_web_twitter_article_tweet_consumption_enabled",
    "content_disclosure_indicator_enabled", "content_disclosure_ai_generated_indicator_enabled",
    "responsive_web_grok_show_grok_translated_post", "responsive_web_grok_analysis_button_from_backend",
    "post_ctas_fetch_enabled", "freedom_of_speech_not_reach_fetch_enabled",
    "standardized_nudges_misinfo",
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled",
    "longform_notetweets_rich_text_read_enabled", "longform_notetweets_inline_media_enabled",
    "responsive_web_nested_quote_preview_enabled", "responsive_web_grok_image_annotation_enabled",
    "responsive_web_grok_imagine_annotation_enabled",
    "responsive_web_grok_community_note_auto_translation_is_enabled",
    "responsive_web_enhance_cards_enabled",
]
FIELD_TOGGLES = ["withPayments", "withDmBlocks", "withAuxiliaryUserLabels",
                 "withArticleRichContentState", "withArticlePlainText",
                 "withArticleSummaryText", "withArticleVoiceOver", "withGrokAnalyze",
                 "withDisallowedReplyControls"]

CSV_FIELDS = [
    "user_id", "screen_name", "name", "location", "bio", "website",
    "followers_count", "following_count", "tweets_count", "account_created_at",
    "is_blue_verified", "protected", "avatar",
]


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


class RateLimited(Exception):
    def __init__(self, reset):
        self.reset = reset


class Account:
    """One X session (auth_token + ct0) with its own rate-limit window."""

    def __init__(self, auth_token, ct0, label=""):
        self.auth_token = auth_token.strip()
        self.ct0 = ct0.strip()
        self.label = label or (auth_token[:6] + "...")
        self.reset_at = 0.0

    def headers(self, content_type=None):
        h = {
            "authorization": f"Bearer {BEARER}",
            "cookie": f"auth_token={self.auth_token}; ct0={self.ct0}",
            "x-csrf-token": self.ct0,
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "user-agent": UA,
            "accept": "application/json, text/plain, */*",
            "referer": "https://x.com/",
        }
        if content_type:
            h["content-type"] = content_type
        return h


def parse_cookie_line(line):
    parts = {}
    for chunk in line.split(";"):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            parts[k.strip()] = v.strip()
    if "auth_token" in parts and "ct0" in parts:
        return parts["auth_token"], parts["ct0"]
    return None


def load_accounts(args):
    """Get sessions from --cookie/--cookie-file, or prompt the user interactively."""
    accounts = []
    if args.cookie:
        pair = parse_cookie_line(args.cookie)
        if pair:
            accounts.append(Account(*pair, label="cli"))
        else:
            sys.exit('ERROR: --cookie must look like: auth_token=...; ct0=...')
    if args.cookie_file:
        with open(args.cookie_file, encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                pair = parse_cookie_line(line)
                if pair:
                    accounts.append(Account(*pair, label=f"line{i}"))
                else:
                    log(f"WARN: skipping malformed cookie line {i}")
    if not accounts:
        if not sys.stdin.isatty():
            sys.exit("ERROR: no session provided. Non-interactive run — pass "
                     '--cookie "auth_token=...; ct0=..." or --cookie-file <file>.')
        print("""
No X session provided. To let this script call X's API, it needs two cookies
from a browser where you are logged into x.com:

  1. Open https://x.com in your browser (logged in).
  2. Press F12 -> Application (Chrome/Edge) or Storage (Firefox)
     -> Cookies -> https://x.com
  3. Copy the values of "auth_token" and "ct0" and paste them below.

  (Tip: next time pass them directly as arguments to skip this prompt:
   --cookie "auth_token=...; ct0=...")
""")
        token = _ask("auth_token: ")
        ct0 = _ask("ct0: ")
        if not token or not ct0:
            sys.exit("ERROR: empty value provided.")
        accounts.append(Account(token, ct0, label="prompt"))
    return accounts


def _maybe_decompress(encoding, body):
    if not encoding:
        return body
    try:
        if "gzip" in encoding:
            return gzip.decompress(body)
        if "deflate" in encoding:
            return zlib.decompress(body)
    except Exception:
        pass
    return body


def _execute(req, account, timeout=30):
    wait = account.reset_at - time.time()
    if wait > 0:
        raise RateLimited(account.reset_at)
    req.add_header("accept-encoding", "gzip, deflate")
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return _maybe_decompress(resp.headers.get("content-encoding"), resp.read()), dict(resp.headers)
        except urllib.error.HTTPError as e:
            body = _maybe_decompress(e.headers.get("content-encoding"), e.read())
            if e.code == 429:
                reset = float(e.headers.get("x-rate-limit-reset", time.time() + 900))
                account.reset_at = reset + random.uniform(2, 6)
                raise RateLimited(reset)
            if e.code in (500, 502, 503, 504) and attempt < 4:
                time.sleep(2 ** attempt + random.random())
                continue
            snippet = body[:400].decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {e.code} from {req.full_url}\n  {snippet}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt < 4:
                time.sleep(2 ** attempt + random.random())
                continue
            raise RuntimeError(f"network error: {e}") from None
    raise RuntimeError("unreachable")


def gql_call(acc, query_id, operation, variables):
    features = {k: True for k in FEATURE_SWITCHES}
    payload = {
        "variables": json.dumps(variables, separators=(",", ":")),
        "features": json.dumps(features, separators=(",", ":")),
        "queryId": query_id,
    }
    req = urllib.request.Request(
        f"https://x.com/i/api/graphql/{query_id}/{operation}",
        data=json.dumps(payload).encode("utf-8"),
        headers=acc.headers("application/json"),
        method="POST")
    body, headers = _execute(req, acc)
    data = json.loads(body)
    if "errors" in data and "data" not in data:
        msgs = "; ".join(e.get("message", "?") for e in data["errors"])
        raise RuntimeError(f"GraphQL {operation} error: {msgs}")
    return data, headers


class Rotator:
    """Round-robin over accounts; sleeps only when ALL are cooling down."""

    def __init__(self, accounts):
        self.accounts = accounts
        self.idx = 0

    def call(self, fn):
        while True:
            acc = self.accounts[self.idx % len(self.accounts)]
            self.idx += 1
            try:
                return fn(acc)
            except RateLimited:
                if all(a.reset_at > time.time() for a in self.accounts):
                    earliest = min(a.reset_at for a in self.accounts) - time.time()
                    log(f"rate limit reached on all {len(self.accounts)} session(s); "
                        f"sleeping {earliest:.0f}s "
                        f"(until {time.strftime('%H:%M:%S', time.localtime(min(a.reset_at for a in self.accounts)))})")
                    time.sleep(earliest + random.uniform(1, 4))


def resolve_user(rot, handle):
    handle = handle.lstrip("@")
    try:
        data, _ = rot.call(lambda acc: gql_call(
            acc, USER_BY_SCREEN_NAME_QID, "UserByScreenName",
            {"screen_name": handle, "withSafetyUserFields": True}))
    except RuntimeError as e:
        if "HTTP 403" in str(e) or "HTTP 401" in str(e):
            sys.exit("ERROR: X rejected the session (403/401). auth_token/ct0 likely "
                     "expired — copy fresh values from the browser (see script header).")
        raise
    result = (data.get("data", {}).get("user", {}) or {}).get("result")
    if not result or result.get("__typename") != "User":
        unavailable = (result or {}).get("reason") if result else "no user object"
        sys.exit(f"ERROR: cannot resolve @{handle}: {unavailable}")
    core = result.get("core", {})
    counts = result.get("relationship_counts", {})
    return {
        "id": result.get("rest_id"),
        "handle": core.get("screen_name", handle),
        "name": core.get("name", ""),
        "followers": counts.get("followers", 0),
        "following": counts.get("following", 0),
    }


LIST_KINDS = {
    "followers": (FOLLOWERS_QID, "Followers"),
    "following": (FOLLOWING_QID, "Following"),
}


def fetch_page(rot, user_id, cursor, count=200, kind="followers"):
    variables = {"userId": user_id, "count": count, "includePromotedContent": False}
    if cursor:
        variables["cursor"] = cursor
    query_id, operation = LIST_KINDS[kind]
    data, headers = rot.call(lambda acc: gql_call(acc, query_id, operation, variables))
    users, next_cursor = _parse_timeline(data)
    return users, next_cursor, headers


def _parse_timeline(data):
    """Handle 2026 instructions-format (and older entries-format) timelines."""
    users, bottom_cursor = [], None

    def walk(node):
        nonlocal bottom_cursor
        if isinstance(node, dict):
            if "rest_id" in node and ("core" in node or "legacy" in node) \
                    and node.get("__typename") in (None, "User"):
                users.append(node)
                return
            if (node.get("__typename") == "TimelineTimelineCursor"
                    or node.get("entryType") == "TimelineTimelineCursor") \
                    and node.get("cursorType") == "Bottom" and node.get("value"):
                bottom_cursor = node["value"]
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(data)
    return users, bottom_cursor or ""


def normalize(node):
    """Flatten a 2026-era user node (with legacy fallback)."""
    core = node.get("core", {})
    legacy = node.get("legacy", {}) or {}
    rel = node.get("relationship_counts", {}) or {}
    tw = node.get("tweet_counts", {}) or {}
    bio = (node.get("profile_bio") or {}).get("description") or legacy.get("description") or ""
    return {
        "user_id": node.get("rest_id", ""),
        "screen_name": core.get("screen_name") or legacy.get("screen_name", ""),
        "name": core.get("name") or legacy.get("name", ""),
        "location": (node.get("location") or {}).get("location") or legacy.get("location", ""),
        "bio": bio.replace("\n", " "),
        "website": (node.get("website") or {}).get("url", ""),
        "followers_count": rel.get("followers", legacy.get("followers_count", "")),
        "following_count": rel.get("following", legacy.get("friends_count", "")),
        "tweets_count": tw.get("tweets", legacy.get("statuses_count", "")),
        "account_created_at": core.get("created_at") or legacy.get("created_at", ""),
        "is_blue_verified": node.get("is_blue_verified", False),
        "protected": (node.get("privacy") or {}).get("protected", legacy.get("protected", False)),
        "avatar": (node.get("avatar") or {}).get("image_url", ""),
    }


def run_export(rot, user, out_dir, kind="followers", max_n=0, page_size=200):
    """Crawl the requested list into out_dir. Returns (collected_count, csv_path)."""
    os.makedirs(out_dir, exist_ok=True)
    jsonl_path = os.path.join(out_dir, f"{kind}.jsonl")
    csv_path = os.path.join(out_dir, f"{kind}.csv")
    state_path = os.path.join(out_dir, "state.json")

    seen = set()
    if os.path.exists(jsonl_path):
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(json.loads(line)["user_id"])
                except Exception:
                    pass
    cursor = ""
    complete = False
    if os.path.exists(state_path):
        st = json.load(open(state_path))
        if st.get("user_id") == user["id"] and st.get("kind", "followers") != kind:
            sys.exit(f"ERROR: {state_path} contains a {st.get('kind')} export; "
                     "use a separate --out directory per list kind.")
        if st.get("user_id") == user["id"]:
            cursor = st.get("cursor", "")
            complete = not cursor and bool(seen)

    if complete:
        log(f"export already complete: {len(seen):,} records on disk; skipping crawl")
    else:
        if seen:
            log(f"resuming: {len(seen):,} already collected")
        _crawl(rot, user, cursor, seen, jsonl_path, state_path, max_n, page_size, kind)

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        with open(jsonl_path, encoding="utf-8") as jf:
            for line in jf:
                try:
                    w.writerow(json.loads(line))
                except Exception:
                    pass
    log(f"export: {len(seen):,} {kind} -> {csv_path} + {jsonl_path}")
    return len(seen), csv_path


def _crawl(rot, user, cursor, seen, jsonl_path, state_path, max_n, page_size, kind):
    jsonl = open(jsonl_path, "a", encoding="utf-8")
    pages, empty_pages = 0, 0
    try:
        while True:
            users, cursor, _ = fetch_page(rot, user["id"], cursor, page_size, kind=kind)
            pages += 1
            if pages == 1 and not users and not seen and user.get(kind):
                raise SystemExit(f"ERROR: session REJECTED — account resolved but page 1 "
                                 f"returned 0 {kind}. auth_token/ct0 are invalid or "
                                 "expired; re-copy them from a logged-in browser.")
            new_here = 0
            for raw in users:
                rec = normalize(raw)
                uid = rec["user_id"]
                if not uid or uid in seen:
                    continue
                seen.add(uid)
                jsonl.write(json.dumps(rec, ensure_ascii=False) + "\n")
                new_here += 1
            jsonl.flush()
            json.dump({"user_id": user["id"], "kind": kind, "cursor": cursor, "collected": len(seen)},
                      open(state_path, "w"))
            log(f"page {pages}: +{new_here} (total {len(seen):,}), "
                f"cursor {'END' if not cursor else 'next'}")
            if max_n and len(seen) >= max_n:
                log(f"reached --max {max_n}; stopping")
                break
            if not cursor:
                break
            if not users:
                empty_pages += 1
                if empty_pages >= 3:
                    log("3 empty pages in a row; stopping (list end or truncation)")
                    break
            else:
                empty_pages = 0
    except KeyboardInterrupt:
        log("interrupted — progress saved, rerun the same command to resume")
    finally:
        jsonl.close()


BANNER = r"""
  o\    /o                                                    _
    \  /      __  __         ___   __  __ _ __    ___   _ __ | |_
     \/       \ \/ / _____  / _ \  \ \/ /| '_ \  / _ \ | '__|| __|
     /\        >  < |_____||  __/   >  < | |_) || (_) || |   | |_
    /  \      /_/\_\        \___|  /_/\_\| .__/  \___/ |_|    \__|
  o/    \o                               |_|
"""


def _ask(prompt_text):
    try:
        return input(prompt_text).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit("\naborted.")


def parse_kind(answer, default=None):
    answer = (answer or "").strip().lower()
    if not answer:
        return default
    if answer == "1" or answer == "followers":
        return "followers"
    if answer == "2" or answer == "following":
        return "following"
    matches = [k for k in ("followers", "following") if k.startswith(answer)]
    return matches[0] if len(matches) == 1 else None


def main():
    ap = argparse.ArgumentParser(
        description="Export followers OR following of any public X account. Free: uses your browser session.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", help="handle to export, e.g. @nasa or nasa (prompted if omitted)")
    ap.add_argument("--list", dest="list_type", choices=["followers", "following"],
                    help="which list to export (prompted if omitted)")
    ap.add_argument("--cookie", help='session: "auth_token=X; ct0=Y"')
    ap.add_argument("--cookie-file", help="file with one cookie string per line (multi-account)")
    ap.add_argument("--max", type=int, default=0, help="stop after N accounts (0 = all)")
    ap.add_argument("--out", default="",
                    help="output dir (default ./followers_<handle> or ./following_<handle>)")
    ap.add_argument("--page-size", type=int, default=200, choices=[50, 100, 200])
    ap.add_argument("--probe", action="store_true", help="test session + one page, then exit")
    ap.add_argument("--no-banner", action="store_true", help="skip the startup banner")
    args = ap.parse_args()

    tty = sys.stdin.isatty()
    if tty and not args.no_banner:
        print(BANNER + "   x-export \u2014 followers & following of any X account\n"
              "   free \u00b7 pure python \u00b7 no API keys\n")

    if not args.target:
        if not tty:
            sys.exit("ERROR: --target is required in non-interactive runs.")
        args.target = _ask("X account to export (e.g. @leshipai): ")
        if not args.target:
            sys.exit("ERROR: empty target.")

    if not args.list_type:
        if not tty:
            sys.exit('ERROR: --list {followers|following} is required in non-interactive runs.')
        print('Which list do you want?\n'
              '  [1] followers \u2014 who follows the account\n'
              '  [2] following \u2014 who the account follows')
        while True:
            args.list_type = parse_kind(_ask("choice [1]: "), default="followers")
            if args.list_type:
                break
            print('please answer "1"/"followers" or "2"/"following".')

    accounts = load_accounts(args)
    rot = Rotator(accounts)
    log(f"loaded {len(accounts)} session(s): " + ", ".join(a.label for a in accounts))

    user = resolve_user(rot, args.target)
    log(f"resolved @{user['handle']} -> id {user['id']} "
        f"({user['followers']:,} followers, {user['following']:,} following)")

    kind = args.list_type

    if args.probe:
        users, cursor, _ = fetch_page(rot, user["id"], "", count=50, kind=kind)
        if not users and user.get(kind):
            sys.exit("ERROR: session REJECTED \u2014 resolved the account but got 0 "
                     f"{kind}. auth_token/ct0 are invalid or expired; re-copy them "
                     "from a logged-in browser.")
        sample = ", ".join(normalize(u)["screen_name"] for u in users[:3])
        log(f"PROBE OK: got {len(users)} {kind}/page, cursor "
            f"{'present' if cursor else 'MISSING'}; first: {sample}")
        return

    out_dir = args.out or f"{kind}_{user['handle'].lower()}"
    run_export(rot, user, out_dir, kind=kind, max_n=args.max, page_size=args.page_size)


if __name__ == "__main__":
    main()
