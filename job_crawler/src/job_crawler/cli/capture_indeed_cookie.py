"""Capture an authenticated Indeed session cookie for the `indeed` crawler.

Why this exists
---------------
Indeed's public search pages sit behind Cloudflare's anti-bot wall. A
fresh headless Chromium hits `Page.goto: Timeout 30000ms exceeded` on
every navigation to `sa.indeed.com/jobs?...`. The `indeed` crawler
honours an optional `JC_INDEED_COOKIE` env var carrying a real session
cookie (especially the `cf_clearance` token Cloudflare issues after a
human passes its checks), which lets the runner navigate normally.

Cookies typically stay valid for ~1-2 weeks. A weekly refresh is
recommended; if Indeed starts returning 0 listings again, re-run this
script before doing anything else.

Usage
-----
    make capture-indeed-cookie
    # or
    uv run python -m job_crawler.cli.capture_indeed_cookie

The script:
  1. Launches a visible Chromium window via Playwright.
  2. Navigates to `https://sa.indeed.com/jobs?l=Saudi+Arabia`.
  3. Operator solves any Cloudflare challenge by hand. Login is
     optional — Cloudflare clearance alone is enough for the crawler.
  4. Operator confirms a normal search page renders, then returns to
     the terminal and presses ENTER.
  5. Script reads cookies for *.indeed.com and writes them as a single
     `name=value; …` header to `<repo>/.env`'s `JC_INDEED_COOKIE` key
     (creating or updating in-place).

Idempotent: re-running overwrites the previous value cleanly.

Security note: the captured cookie includes any logged-in session as
well as the Cloudflare clearance token. Treat `.env` like any secret
store.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

from playwright.async_api import async_playwright

# `.env` next to the package root — three parents up from this file
# resolves to `<repo>/job_crawler/.env`. Override via --env-file.
_DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

_INDEED_LANDING_URL = "https://sa.indeed.com/jobs?l=Saudi+Arabia"
_INDEED_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "indeed.com",
)


async def _capture(env_file: Path) -> int:
    print(f"Opening Chromium → {_INDEED_LANDING_URL}")
    print(
        "If Cloudflare shows a 'verify you are human' challenge, complete "
        "it. Logging in is optional. Once the normal search page renders "
        "with job cards visible, return to this terminal and press ENTER."
    )
    print()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=False, args=["--start-maximized"],
        )
        try:
            ctx = await browser.new_context(viewport=None)
            page = await ctx.new_page()
            try:
                # `wait_until="domcontentloaded"` instead of `networkidle`
                # because Indeed's anti-bot wall blocks Playwright if it
                # waits for full idle — domcontentloaded lets the page
                # paint enough for the Cloudflare challenge to appear.
                await page.goto(
                    _INDEED_LANDING_URL,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
            except Exception as exc:
                print(f"warn: navigation slow / errored ({exc}); proceeding anyway")

            # Block on terminal input — operator finishes the Cloudflare
            # challenge + (optional) login flow.
            await asyncio.get_event_loop().run_in_executor(
                None, input,
                "Press ENTER once the search page is rendering with job cards... ",
            )
            cookies = await ctx.cookies()
        finally:
            await browser.close()

    indeed_cookies = [
        c for c in cookies
        if any(c["domain"].lstrip(".").endswith(suf) for suf in _INDEED_DOMAIN_SUFFIXES)
    ]
    if not indeed_cookies:
        print(
            "No Indeed cookies captured. Make sure the search page "
            "rendered (passing any Cloudflare challenge) before pressing "
            "ENTER."
        )
        return 1

    # `cf_clearance` is the most important cookie here — without it the
    # crawler hits the anti-bot wall again. Flag its absence loudly.
    if not any(c["name"] == "cf_clearance" for c in indeed_cookies):
        print(
            "warn: no `cf_clearance` cookie found. The crawler may still "
            "hit Cloudflare on its next run. Try solving the challenge "
            "more thoroughly and re-running.",
        )

    cookie_header = "; ".join(
        f"{c['name']}={c['value']}" for c in indeed_cookies
    )
    _upsert_env_var(env_file, "JC_INDEED_COOKIE", cookie_header)
    print(
        f"OK — wrote {len(indeed_cookies)} cookies "
        f"({len(cookie_header)} chars) to {env_file}\n"
        "Restart the crawler (or wait for the next hourly fire) and "
        "the `indeed` source should start returning Saudi listings."
    )
    return 0


def _upsert_env_var(env_path: Path, key: str, value: str) -> None:
    """Write `KEY=VALUE` to `env_path`, updating in-place if the key
    already exists. Preserves all other lines + comments."""
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if not env_path.exists():
        env_path.write_text(f"{key}={value}\n", encoding="utf-8")
        return
    text = env_path.read_text(encoding="utf-8")
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(f"{key}={value}", text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"{key}={value}\n"
    env_path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(prog="job_crawler.cli.capture_indeed_cookie")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=_DEFAULT_ENV_FILE,
        help=f"target .env path (default: {_DEFAULT_ENV_FILE})",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(_capture(args.env_file)))


if __name__ == "__main__":
    main()
