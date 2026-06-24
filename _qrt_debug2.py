from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(user_agent=UA)
    page = ctx.new_page()
    page.goto("https://www.qube-rt.com/careers/", wait_until="domcontentloaded", timeout=20000)
    page.wait_for_selector("body", timeout=15000)
    for s in range(3):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(800)
    page.wait_for_timeout(15000)
    # Direct DOM query
    live = page.query_selector_all("a[href*='gh_jid=']")
    print("live dom:", len(live))
    # page.content()
    html = page.content()
    soup_links = BeautifulSoup(html, "html.parser").select("a[href*='gh_jid=']")
    print("page.content+soup:", len(soup_links))
    print("html_len:", len(html))
    # Try inner_html
    body_inner = page.evaluate("document.body.innerHTML")
    bi_links = BeautifulSoup(body_inner, "html.parser").select("a[href*='gh_jid=']")
    print("body.innerHTML+soup:", len(bi_links))
    print("innerHTML len:", len(body_inner))
    browser.close()
