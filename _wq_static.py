import requests
from bs4 import BeautifulSoup

r = requests.get(
    "https://www.worldquant.com/career-listing/",
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    },
    timeout=20,
)
print("status:", r.status_code, "len:", len(r.text))
soup = BeautifulSoup(r.text, "html.parser")
jobs = soup.select("a[href*='career-listing/?id=']")
print("found:", len(jobs))
for a in jobs[:5]:
    print(" -", (a.get_text(" ", strip=True) or "")[:80], "|", a.get("href"))
