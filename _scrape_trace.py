"""Run scrape_browser for QRT with traces to see why it fails."""
import sys
sys.path.insert(0, ".")
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
from bs4 import BeautifulSoup

from scrape_quant_jobs import FIRMS, BROWSER_USER_AGENT, _extract_jobs_from_html

firm = next(f for f in FIRMS if f.name == "Qube Research & Technologies")
print("config:", firm.config)

cfg = firm.config
urls = cfg.get("urls") or [cfg["url"]]
wait_for = cfg.get("wait_for", "body")
link_selector = cfg["link_selector"]
extra_wait_ms = int(cfg.get("extra_wait_ms", 0))
scroll_count = int(cfg.get("scroll_count", 0))

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    for url in urls:
        context = browser.new_context(user_agent=BROWSER_USER_AGENT)
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        print("goto done")
        try:
            page.wait_for_selector(wait_for, timeout=15000)
            print(f"wait_for {wait_for!r}: OK")
        except PWTimeoutError as e:
            print(f"wait_for {wait_for!r}: TIMEOUT")
        for i in range(scroll_count):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(800)
            print(f"scroll {i + 1}/{scroll_count}")
        print(f"extra_wait {extra_wait_ms}ms")
        page.wait_for_timeout(extra_wait_ms)
        html = page.content()
        print(f"html_len={len(html)}")
        jobs = _extract_jobs_from_html(firm.name, html, url, link_selector)
        print(f"extracted jobs: {len(jobs)}")
        # check live DOM too
        live = page.query_selector_all(link_selector)
        print(f"live DOM: {len(live)}")
        page.close()
        context.close()
    browser.close()
