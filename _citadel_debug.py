from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

URLS = [
    "https://www.citadel.com/careers/open-opportunities?experience-filter=internships&selected-job-sections=388,389,387,390&current_page=1&sort_order=DESC&per_page=10&action=careers_listing_filter",
    "https://www.citadel.com/careers/open-opportunities/page/2?experience-filter=internships&selected-job-sections=388,389,387,390&current_page=2&sort_order=DESC&per_page=10&action=careers_listing_filter",
    "https://www.citadel.com/careers/open-opportunities/page/3?experience-filter=internships&selected-job-sections=388,389,387,390&current_page=3&sort_order=DESC&per_page=10&action=careers_listing_filter",
]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    for i, url in enumerate(URLS, 1):
        ctx = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
        except Exception as e:
            print(f"p{i}: goto err: {e}")
            page.close()
            continue
        try:
            page.wait_for_selector("a[href*='/careers/details/']", timeout=15000)
            print(f"p{i}: selector OK")
        except Exception as e:
            print(f"p{i}: selector timeout: {e}")
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")
        links = soup.select("a[href*='/careers/details/']")
        print(f"p{i}: found {len(links)} detail links; final URL = {page.url[:120]}")
        page.close()
        ctx.close()
    browser.close()
