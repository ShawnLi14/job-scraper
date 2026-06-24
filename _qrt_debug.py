from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    for attempt in range(2):
        ctx = browser.new_context(user_agent=UA)
        page = ctx.new_page()
        page.goto("https://www.qube-rt.com/careers/", wait_until="domcontentloaded", timeout=20000)
        page.wait_for_selector("body", timeout=15000)
        for s in range(2):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(800)
        page.wait_for_timeout(12000)
        html = page.content()
        links = BeautifulSoup(html, "html.parser").select("a[href*='/careers/job?gh_jid=']")
        print(f"attempt {attempt}: html_len={len(html)} links={len(links)}")
        page.close()
        ctx.close()
    browser.close()
