#!/usr/bin/env python3
"""
refresh-template — capture a fresh `x-client-transaction-id` + cookie
jar from the server-resident Chrome and persist them for the Go scraper
to consume.

Invoked by tweetsd's auth-refresh loop (hourly, plus on demand when
the scraper returns 401/403/404). Exits non-zero on any failure so
the caller can log/retry.

Wire:
  1. /json/list on the local Chrome's DevTools port → find the
     x.com page (or open one if none exists).
  2. CDP Page.navigate to https://x.com/search?q=test&src=typed_query
     so a SearchTimeline GraphQL call fires.
  3. Capture the request URL + headers from Network.requestWillBeSent.
  4. Network.getAllCookies → full jar (incl. HttpOnly).
  5. Write /srv/tweets/cookies.json and /srv/tweets/search-template.json
     atomically via tempfile + os.replace.

The atomic replace is important: the Go scraper polls these files;
a half-written file would cause silent breakage.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

import websocket  # type: ignore


def find_or_open_x_page(devtools_url: str, timeout: float) -> dict:
    """Return a Page target on x.com, creating one if none exists."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            targets = json.loads(urlopen(f"{devtools_url}/json/list", timeout=5).read())
        except Exception as e:
            time.sleep(0.5)
            continue
        for t in targets:
            if t.get("type") == "page" and "x.com" in t.get("url", ""):
                return t
        # No x.com tab yet — ask DevTools to open one.
        try:
            new = json.loads(
                urlopen(
                    f"{devtools_url}/json/new?https://x.com/explore",
                    timeout=5,
                ).read()
            )
            return new
        except Exception:
            time.sleep(0.5)
    raise SystemExit("no x.com page found in DevTools target list")


class CDP:
    """Minimal CDP client: send id-tagged messages, drain async events."""

    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=30)
        self._next_id = 1
        self._buffered: list[dict] = []

    def call(self, method: str, params: dict | None = None) -> dict:
        rid = self._next_id
        self._next_id += 1
        msg = {"id": rid, "method": method}
        if params is not None:
            msg["params"] = params
        self.ws.send(json.dumps(msg))
        while True:
            obj = json.loads(self.ws.recv())
            if obj.get("id") == rid:
                if "error" in obj:
                    raise RuntimeError(f"{method} failed: {obj['error']}")
                return obj.get("result", {})
            self._buffered.append(obj)

    def collect_until(self, predicate, max_seconds: float) -> dict | None:
        # Drain replayed events first.
        for ev in list(self._buffered):
            if predicate(ev):
                self._buffered.remove(ev)
                return ev
        deadline = time.time() + max_seconds
        while time.time() < deadline:
            self.ws.settimeout(max(0.1, deadline - time.time()))
            try:
                obj = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                continue
            if predicate(obj):
                return obj
        return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--devtools", default="http://127.0.0.1:9222")
    p.add_argument("--cookies-out", default="/srv/tweets/cookies.json")
    p.add_argument("--template-out", default="/srv/tweets/search-template.json")
    p.add_argument("--timeout", type=float, default=25.0)
    args = p.parse_args()

    page = find_or_open_x_page(args.devtools, timeout=args.timeout)
    print(f"target: {page['url']}", file=sys.stderr)
    cdp = CDP(page["webSocketDebuggerUrl"])
    cdp.call("Network.enable")
    cdp.call("Page.enable")

    # Force a search navigation — guaranteed SearchTimeline call.
    # Picking a stable trivial query (no quotes, no script characters)
    # so X's input sanitiser doesn't reroute us anywhere unexpected.
    cdp.call("Page.navigate", {"url": "https://x.com/search?q=hello&src=typed_query"})

    def is_search_timeline(ev) -> bool:
        if ev.get("method") != "Network.requestWillBeSent":
            return False
        req = ev.get("params", {}).get("request", {})
        url = req.get("url", "")
        return "/i/api/graphql/" in url and "/SearchTimeline" in url

    ev = cdp.collect_until(is_search_timeline, max_seconds=args.timeout)
    if ev is None:
        print("ERROR: no SearchTimeline request observed in time", file=sys.stderr)
        sys.exit(2)

    req = ev["params"]["request"]
    url = req["url"]
    headers = dict(req.get("headers", {}))
    m = re.search(r"/graphql/([^/]+)/SearchTimeline", url)
    query_id = m.group(1) if m else ""

    # Full jar including HttpOnly.
    ck_result = cdp.call("Network.getAllCookies")
    cookies = ck_result.get("cookies", [])
    keep_domains = (".x.com", "x.com", ".twitter.com", "twitter.com")
    x_cookies = [
        {"name": c["name"], "value": c["value"], "domain": c["domain"]}
        for c in cookies
        if any(c["domain"].endswith(d) for d in keep_domains)
    ]
    by_name = {c["name"]: c["value"] for c in x_cookies}
    if not by_name.get("auth_token") or not by_name.get("ct0"):
        present = sorted(by_name.keys())
        print(
            f"ERROR: auth_token/ct0 missing after refresh; present={present}",
            file=sys.stderr,
        )
        sys.exit(3)

    # Drop request-specific or cookie-bound headers; the scraper rebuilds
    # those from cookies.json at request time. Keep x-client-transaction-id
    # explicitly — that's the whole point of this refresh.
    drop = {"cookie", "x-csrf-token", "content-length"}
    safe_headers = {
        k: v
        for k, v in headers.items()
        if k.lower() not in drop and not k.lower().startswith(":")
    }

    cookies_out = {
        "auth_token": by_name["auth_token"],
        "ct0": by_name["ct0"],
        "all": x_cookies,
    }
    template_out = {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "url": url,
        "query_id": query_id,
        "method": req.get("method", "GET"),
        "headers": safe_headers,
        "user_id": by_name.get("twid", "").replace("u%3D", "").replace("u=", ""),
    }

    write_atomic(Path(args.cookies_out), cookies_out)
    write_atomic(Path(args.template_out), template_out)
    print(
        f"OK query_id={query_id} cookies={len(x_cookies)} "
        f"tid={safe_headers.get('x-client-transaction-id','')[:16]}…",
        file=sys.stderr,
    )


def write_atomic(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Same directory so os.replace() is atomic on POSIX.
    with tempfile.NamedTemporaryFile(
        "w", dir=path.parent, delete=False, suffix=".tmp"
    ) as tmp:
        json.dump(data, tmp, indent=2)
        tmp_path = Path(tmp.name)
    os.chmod(tmp_path, 0o600)
    os.replace(tmp_path, path)


if __name__ == "__main__":
    main()
