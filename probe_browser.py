"""
Throwaway diagnostic harness for discovering selectors on JS-rendered
career sites. Not imported by the main scraper.

Usage:
    python probe_browser.py URL --wait "CSS_SELECTOR" --links "CSS_SELECTOR"

Examples:
    python probe_browser.py https://www.citadel.com/careers/students/ \
        --wait "a[href*='job']" --links "a[href*='job']"

Flags:
    --headless       Run Chromium headless (default: visible, so you can watch)
    --wait-ms MS     Extra ms to sleep after wait-selector fires (default 1500)
    --scroll N       Scroll to bottom N times to trigger lazy-loads (default 0)
    --dump FILE      Write the post-render HTML to FILE for offline inspection
    --limit N        Max links to print (default 25)
"""

import argparse
import sys
import time
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError


def _safe_print(s: str) -> None:
    """Print, stripping characters that Windows cp1252 can't encode."""
    try:
        print(s)
    except UnicodeEncodeError:
        enc = sys.stdout.encoding or "ascii"
        print(s.encode(enc, errors="replace").decode(enc, errors="replace"))


REAL_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def probe(
    url: str,
    wait_selector: str | None,
    link_selector: str,
    headless: bool = False,
    extra_wait_ms: int = 1500,
    scroll_count: int = 0,
    dump_path: str | None = None,
    limit: int = 25,
) -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(user_agent=REAL_UA)
        page = context.new_page()
        print(f"[probe] goto {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PWTimeoutError as e:
            print(f"[probe] goto timed out: {e}")
            browser.close()
            return 2

        print(f"[probe] title: {page.title()!r}")

        if wait_selector:
            print(f"[probe] waiting for selector: {wait_selector!r}")
            try:
                page.wait_for_selector(wait_selector, timeout=15000)
                print("[probe]   -> selector appeared")
            except PWTimeoutError:
                print("[probe]   -> TIMEOUT (selector never appeared)")

        for i in range(scroll_count):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(800)
            print(f"[probe] scrolled {i + 1}/{scroll_count}")

        if extra_wait_ms:
            page.wait_for_timeout(extra_wait_ms)

        html = page.content()
        if dump_path:
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"[probe] dumped HTML to {dump_path} ({len(html)} chars)")

        print(f"[probe] querying links: {link_selector!r}")
        handles = page.query_selector_all(link_selector)
        print(f"[probe] matched {len(handles)} elements")

        shown = 0
        for h in handles:
            if shown >= limit:
                break
            try:
                text = (h.inner_text() or "").strip().replace("\n", " ")
                href = h.get_attribute("href") or ""
            except Exception:
                continue
            if not text:
                continue
            if href and not href.startswith(("http://", "https://")):
                href = urljoin(url, href)
            _safe_print(f"  - {text[:90]!r:95}  {href}")
            shown += 1

        browser.close()
        return 0 if handles else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--wait", dest="wait_selector", default=None, help="CSS selector to wait for before reading HTML")
    ap.add_argument("--links", dest="link_selector", required=True, help="CSS selector to query for job links")
    ap.add_argument("--headless", action="store_true", help="Run Chromium headless (default: visible)")
    ap.add_argument("--wait-ms", type=int, default=1500, help="Extra ms to wait after selector fires")
    ap.add_argument("--scroll", type=int, default=0, help="Scroll to bottom N times to trigger lazy loads")
    ap.add_argument("--dump", default=None, help="Write post-render HTML to this file")
    ap.add_argument("--limit", type=int, default=25, help="Max matched links to print")
    args = ap.parse_args()

    return probe(
        url=args.url,
        wait_selector=args.wait_selector,
        link_selector=args.link_selector,
        headless=args.headless,
        extra_wait_ms=args.wait_ms,
        scroll_count=args.scroll,
        dump_path=args.dump,
        limit=args.limit,
    )


if __name__ == "__main__":
    sys.exit(main())
