"""Capture an authenticated LinkedIn session cookie for the `linkedin` crawler.

Why this exists
---------------
LinkedIn's anonymous guest API silently ignores `geoId` / `location` /
`keywords` filters and returns MENA-wide listings — typically 100%
Egypt for our query. The runner's GCC geo gate then rejects every
fetched detail page, yielding zero LinkedIn postings in the DB.

The crawler honours an optional `JC_LINKEDIN_COOKIE` env var. With a
real session cookie, LinkedIn applies geo + keyword filters server-side
and returns actual Saudi jobs.

Cookies typically stay valid for ~2-4 weeks. A weekly refresh is
recommended.

Usage
-----
    make capture-linkedin-cookie
    # or
    uv run python -m job_crawler.cli.capture_linkedin_cookie

The script:
  1. Launches a visible Chromium window via Playwright.
  2. Navigates to linkedin.com/login.
  3. Operator logs in by hand (with a burner account, ideally — LinkedIn
     ToS forbids automated session use on personal accounts).
  4. Operator navigates to the Saudi jobs feed to confirm geo works.
  5. Returns to the terminal and presses ENTER.
  6. Script reads cookies for *.linkedin.com and writes them as a
     single `name=value; …` header to `<repo>/.env`'s
     `JC_LINKEDIN_COOKIE` key (creating or updating in-place).

Idempotent: re-running overwrites the previous value cleanly.

Security note: the captured cookie grants full session-level access to
the logged-in LinkedIn account. Treat `.env` like any secret store.
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

_LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
_LINKEDIN_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "linkedin.com",
)


async def _capture(env_file: Path) -> int:
    print(f"Opening Chromium → {_LINKEDIN_LOGIN_URL}")
    print(
        "Log in, navigate to https://www.linkedin.com/jobs/search?location=Saudi+Arabia "
        "to confirm Saudi jobs are visible, then come back to this "
        "terminal and press ENTER to capture the cookie."
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
                await page.goto(_LINKEDIN_LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
            except Exception as exc:
                print(f"warn: navigation slow / errored ({exc}); proceeding anyway")

            # Block on terminal input — operator finishes the login flow.
            await asyncio.get_event_loop().run_in_executor(
                None, input,
                "Press ENTER once logged in and Saudi jobs are visible... ",
            )
            cookies = await ctx.cookies()
        finally:
            await browser.close()

    linkedin_cookies = [
        c for c in cookies
        if any(c["domain"].lstrip(".").endswith(suf) for suf in _LINKEDIN_DOMAIN_SUFFIXES)
    ]
    if not linkedin_cookies:
        print(
            "No LinkedIn cookies captured. Make sure you completed the "
            "login flow before pressing ENTER."
        )
        return 1

    cookie_header = "; ".join(
        f"{c['name']}={c['value']}" for c in linkedin_cookies
    )
    _upsert_env_var(env_file, "JC_LINKEDIN_COOKIE", cookie_header)
    print(
        f"OK — wrote {len(linkedin_cookies)} cookies "
        f"({len(cookie_header)} chars) to {env_file}\n"
        "Restart the crawler (or wait for the next hourly fire) and "
        "the `linkedin` source should start returning Saudi listings."
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
    parser = argparse.ArgumentParser(prog="job_crawler.cli.capture_linkedin_cookie")
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
