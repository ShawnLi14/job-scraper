from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    )
    page = ctx.new_page()

    requests_log = []

    def on_request(request):
        if request.resource_type in ("xhr", "fetch", "document") and "worldquant" in request.url:
            requests_log.append(f"{request.method} {request.url[:200]}")

    page.on("request", on_request)
    page.goto("https://www.worldquant.com/career-listing/", wait_until="networkidle", timeout=40000)
    page.wait_for_timeout(5000)

    for r in requests_log[:40]:
        print(r)
    print("---")
    print("career-listing matches:", len(page.query_selector_all("a[href*='career-listing/?id=']")))
    browser.close()
