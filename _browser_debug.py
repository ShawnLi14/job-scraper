"""Quick debug: run the real scrape_browser on selected firms and print results."""
import sys
from playwright.sync_api import sync_playwright

sys.path.insert(0, ".")
from scrape_quant_jobs import FIRMS, scrape_browser

targets = sys.argv[1:] or ["Citadel", "Citadel Securities", "Qube Research & Technologies", "WorldQuant"]

firms = [f for f in FIRMS if f.name in targets]
with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    for firm in firms:
        print(f"\n=== {firm.name} ===")
        try:
            jobs = scrape_browser(firm, browser=browser)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue
        print(f"  got {len(jobs)} jobs")
        for j in jobs[:8]:
            t = j.title[:80]
            try:
                print(f"   - {t} | {j.url}")
            except UnicodeEncodeError:
                print(f"   - (non-ascii title) | {j.url}")
    browser.close()
