"""
Scrapes career pages of major quant firms for US-based early-career
opportunities — internships, insight programs, spring weeks, and
new-graduate / full-time campus hire roles.
"""

import re
import json
import argparse
from pathlib import Path
from urllib.parse import urljoin
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}

REQUEST_TIMEOUT = 15

# Keywords that tag a role as an internship / early-career / insight program.
INTERN_KEYWORDS = [
    r"\bintern\b",
    r"\binternship\b",
    r"\binsight\b",
    r"\bspring week\b",
    r"\bspring insight\b",
    r"\bundergrad",
    r"\bearly career",
    r"\bearly talent",
    r"\bplacement\b",
    r"\bco-op\b",
    r"\bsummer analyst\b",
    r"\bsummer associate\b",
    r"\bexploration\b",
    r"\bdiscovery\b",
    r"\bacademy\b",
]

# Keywords that tag a role as a full-time new-grad / graduate / campus hire.
NEW_GRAD_KEYWORDS = [
    r"\bnew\s*grad(?:uate)?s?\b",
    r"\brecent\s+graduate",
    r"\bgraduate\s+program(?:me)?",
    r"\bgraduate\s+(?:analyst|trader|engineer|developer|researcher|software|quant|quantitative|associate|scientist)",
    r"\bcampus\s+(?:hire|recruit(?:ing)?|program)",
    r"\bclass\s+of\s+20\d\d\b",
    r"\brotational\s+program",
    r"\banalyst\s+program\b",
    r"\bassociate\s+program\b",
    r"\bfull[-\s]?time\b",
    r"\bfulltime\b",
    r"\bfull[-\s]?time\s+(?:analyst|associate|engineer|developer|researcher|scientist|trader|new\s*grad|graduate|campus|role|position)",
]

UNDERGRAD_KEYWORDS = INTERN_KEYWORDS + NEW_GRAD_KEYWORDS
UNDERGRAD_PATTERN = re.compile("|".join(UNDERGRAD_KEYWORDS), re.IGNORECASE)

EXCLUDE_TITLE_PATTERNS = re.compile(
    r"\brecruit\w*\b"          # recruiter, recruiting, recruitment coordinator, etc.
    r"|\bph\.?\s*d\.?\b"       # PhD / Ph.D. / Ph D — doctoral-only roles
    r"|\bdoctoral\b"
    r"|\bpost[-\s]?doc(?:toral)?\b",
    re.IGNORECASE,
)

# Catch "Summer 2026" in any word order: "Summer Intern 2026", "2026 Summer Internship", etc.
STALE_PATTERN = re.compile(r"\bsummer\b.*\b2026\b|\b2026\b.*\bsummer\b", re.IGNORECASE)

US_LOCATION_HINTS = [
    "united states", "new york", "chicago", "san francisco", "boston",
    "seattle", "los angeles", "miami", "houston", "austin", "denver",
    "philadelphia", "atlanta", "dallas", "greenwich", "stamford",
    "washington", "florida", "california", "illinois", "texas",
    "massachusetts", "connecticut", "new jersey", "colorado",
    "virginia", "maryland", "minnesota", "ohio", "pennsylvania",
    "north carolina", "oregon", "arizona", "michigan",
    "boulder", "carteret", "bellevue", "charlotte", "portland",
    "san diego", "pittsburgh", "detroit", "indianapolis", "nashville",
    "raleigh", "tampa", "st. louis", "kansas city", "columbus",
    "salt lake", "milwaukee", "sacramento",
]

US_STATE_ABBREVS = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

_US_ABBREV_PATTERN = re.compile(
    r",\s*(" + "|".join(US_STATE_ABBREVS) + r")(?:\s*,|\s*$|\s+\d)",
)

NON_US_LOCATION_HINTS = [
    "london", "hong kong", "singapore", "sydney", "tokyo", "paris",
    "dublin", "mumbai", "shanghai", "gurgaon", "amsterdam", "warsaw",
    "montreal", "toronto", "são paulo", "sao paulo", "tel aviv",
    "geneva", "zurich", "zürich", "milan", "frankfurt", "berlin",
    "madrid", "barcelona", "stockholm", "copenhagen", "oslo", "helsinki",
    "brussels", "luxembourg", "lisbon", "athens", "vienna",
    "taipei", "seoul", "beijing", "shenzhen", "bangkok", "manila",
    "jakarta", "kuala lumpur", "ho chi minh", "hanoi", "bengaluru",
    "bangalore", "hyderabad", "chennai", "pune", "delhi", "new delhi",
    "dubai", "abu dhabi", "riyadh", "doha",
    "mexico city", "buenos aires", "bogotá", "bogota", "lima", "santiago",
    "melbourne", "perth", "auckland",
    "united kingdom", " uk ", " uk,", "(uk)", "u.k.",
    "europe", "emea", "apac", "mena", "latam",
]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Job:
    firm: str
    title: str
    location: str = ""
    url: str = ""
    department: str = ""


@dataclass
class Firm:
    name: str
    scrape_fn: str  # name of the scraper function to call
    config: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Firm definitions
# ---------------------------------------------------------------------------

FIRMS: list[Firm] = [
    # ---- Greenhouse API firms (verified board tokens) ----
    Firm("Jane Street", "greenhouse", {"board": "janestreet"}),
    Firm("Jump Trading", "greenhouse", {"board": "jumptrading"}),
    Firm("Hudson River Trading", "greenhouse", {"board": "wehrtyou"}),
    Firm("IMC Trading", "greenhouse", {"board": "imc"}),
    Firm("Akuna Capital", "greenhouse", {"board": "akunacapital"}),
    Firm("Five Rings", "greenhouse", {"board": "fiveringsllc"}),
    Firm("Point72 / Cubist", "greenhouse", {"board": "point72"}),
    Firm("Schonfeld", "greenhouse", {"board": "schonfeld"}),
    Firm("Squarepoint Capital", "greenhouse", {"board": "squarepointcapital"}),
    Firm("Radix Trading", "greenhouse_multi", {
        "boards": ["radixexperienced", "radixuniversity"],
    }),
    Firm("Old Mission", "greenhouse", {"board": "oldmissioncapital"}),
    Firm("Tower Research Capital", "greenhouse", {"board": "towerresearchcapital"}),
    Firm("DRW", "greenhouse", {"board": "drweng"}),
    Firm("Optiver", "greenhouse", {"board": "optiverus"}),
    Firm("Man Group", "greenhouse", {"board": "mangroup"}),
    Firm("Bridgewater Associates", "greenhouse", {"board": "bridgewater89"}),
    Firm("XTX Markets", "greenhouse", {"board": "xtxmarketstechnologies"}),
    Firm("Walleye Capital", "greenhouse", {"board": "walleyecapital-external-students"}),
    Firm("Virtu Financial", "greenhouse", {"board": "virtu"}),
    Firm("PDT Partners", "greenhouse", {"board": "pdtpartners"}),
    Firm("Flow Traders", "greenhouse", {"board": "flowtraders"}),
    Firm("DV Trading", "greenhouse", {"board": "dvtrading"}),
    Firm("Eclipse Trading", "greenhouse", {"board": "eclipsetrading"}),
    Firm("Winton", "greenhouse", {"board": "winton"}),
    Firm("ExodusPoint", "greenhouse", {"board": "exoduspoint"}),
    Firm("Gelber Group", "greenhouse", {"board": "gelbergroup"}),
    Firm("Maven Securities", "ashby", {"board": "maven"}),

    # ---- Tier 1 prop / quant (verified boards) ----
    Firm("Chicago Trading Company", "greenhouse", {"board": "chicagotrading"}),
    Firm("Belvedere Trading", "lever", {"company": "belvederetrading"}),
    Firm("TransMarket Group", "greenhouse", {"board": "transmarketgroup"}),
    Firm("Geneva Trading", "greenhouse", {"board": "genevatrading"}),
    Firm("Wolverine Trading", "wolve", {}),
    Firm("Paradigm", "ashby", {"board": "paradigm"}),
    Firm("WorldQuant", "greenhouse", {"board": "worldquant"}),
    Firm("Marshall Wace", "greenhouse", {"board": "marshallwace"}),
    Firm("Engineers Gate", "greenhouse", {"board": "engineersgate"}),

    # ---- NYC high-TC ($200k+ new grad) — crypto / fintech ----
    Firm("Gemini", "greenhouse", {"board": "gemini"}),
    Firm("Paxos", "ashby", {"board": "paxos"}),
    Firm("Socure", "ashby", {"board": "socure"}),
    Firm("Alloy", "greenhouse", {"board": "alloy"}),

    # ---- Tech unicorns / high-signal companies (Greenhouse) ----
    Firm("Databricks", "greenhouse", {"board": "databricks"}),
    Firm("Stripe", "greenhouse", {"board": "stripe"}),
    Firm("Snowflake", "ashby", {"board": "snowflake"}),
    Firm("OpenAI", "ashby", {"board": "openai"}),
    Firm("Anthropic", "greenhouse", {"board": "anthropic"}),
    Firm("MongoDB", "greenhouse", {"board": "mongodb"}),
    Firm("Datadog", "greenhouse", {"board": "datadog"}),
    Firm("Anduril", "greenhouse", {"board": "andurilindustries"}),
    Firm("Scale AI", "greenhouse", {"board": "scaleai"}),
    Firm("Figma", "greenhouse", {"board": "figma"}),
    Firm("Notion", "ashby", {"board": "notion"}),
    Firm("Ramp", "ashby", {"board": "ramp"}),
    Firm("Plaid", "ashby", {"board": "plaid"}),
    Firm("Coinbase", "greenhouse", {"board": "coinbase"}),
    Firm("Robinhood", "greenhouse", {"board": "robinhood"}),
    Firm("Cloudflare", "greenhouse", {"board": "cloudflare"}),
    Firm("Waymo", "greenhouse", {"board": "waymo"}),
    Firm("Block", "greenhouse", {"board": "block"}),
    Firm("Airbnb", "greenhouse", {"board": "airbnb"}),
    Firm("Palantir", "lever", {"company": "palantir"}),
    Firm("Instacart", "greenhouse", {"board": "instacart"}),
    Firm("Discord", "greenhouse", {"board": "discord"}),
    Firm("Brex", "greenhouse", {"board": "brex"}),
    Firm("Vercel", "greenhouse", {"board": "vercel"}),
    Firm("Cohere", "ashby", {"board": "cohere"}),
    Firm("Perplexity", "ashby", {"board": "perplexity"}),
    Firm("Mistral", "lever", {"company": "mistral"}),
    Firm("Confluent", "ashby", {"board": "confluent"}),
    Firm("Linear", "ashby", {"board": "linear"}),
    Firm("Samsara", "greenhouse", {"board": "samsara"}),
    Firm("Lyft", "greenhouse", {"board": "lyft"}),
    Firm("Twilio", "greenhouse", {"board": "twilio"}),
    Firm("SpaceX", "greenhouse", {"board": "spacex"}),
    Firm("DoorDash", "greenhouse", {"board": "doordashusa"}),
    Firm("xAI", "greenhouse", {"board": "xai"}),
    Firm("CoreWeave", "greenhouse", {"board": "coreweave"}),
    Firm("Together AI", "greenhouse", {"board": "togetherai"}),
    Firm("Fal", "greenhouse", {"board": "fal"}),
    Firm("Lovable", "greenhouse", {"board": "lovable"}),
    Firm("Nuro", "greenhouse", {"board": "nuro"}),
    Firm("Cursor", "ashby", {"board": "cursor"}),
    Firm("Harvey", "ashby", {"board": "harvey"}),
    Firm("ElevenLabs", "ashby", {"board": "elevenlabs"}),
    Firm("Sierra", "ashby", {"board": "sierra"}),
    Firm("Decagon", "ashby", {"board": "decagon"}),
    Firm("Mercor", "ashby", {"board": "mercor"}),
    Firm("OpenEvidence", "ashby", {"board": "openevidence"}),
    Firm("Kalshi", "ashby", {"board": "kalshi"}),
    Firm("Reddit", "greenhouse", {"board": "reddit"}),
    Firm("Flexport", "greenhouse", {"board": "flexport"}),
    Firm("Fivetran", "greenhouse", {"board": "fivetran"}),
    Firm("Spotify", "lever", {"company": "spotify"}),
    Firm("Supabase", "ashby", {"board": "supabase"}),
    Firm("Replit", "ashby", {"board": "replit"}),
    Firm("LangChain", "ashby", {"board": "langchain"}),
    Firm("Modal", "ashby", {"board": "modal"}),
    Firm("Cognition", "ashby", {"board": "cognition"}),
    Firm("Character", "ashby", {"board": "character"}),
    Firm("Warp", "ashby", {"board": "warp"}),
    Firm("Polymarket", "ashby", {"board": "polymarket"}),
    Firm("Zapier", "ashby", {"board": "zapier"}),
    Firm("Runway", "ashby", {"board": "runway"}),

    # ---- AI labs (frontier research) ----
    Firm("Thinking Machines Lab", "greenhouse", {"board": "thinkingmachines"}),
    Firm("Reflection AI", "ashby", {"board": "reflectionai"}),
    Firm("Magic", "ashby", {"board": "magic.dev"}),
    Firm("Imbue", "greenhouse", {"board": "imbue"}),
    Firm("World Labs", "greenhouse", {"board": "worldlabs"}),
    Firm("Lila Sciences", "greenhouse", {"board": "lilasciences"}),
    Firm("Isomorphic Labs", "greenhouse", {"board": "isomorphiclabs"}),
    Firm("DeepMind", "greenhouse", {"board": "deepmind"}),
    Firm("Stability AI", "greenhouse", {"board": "stabilityai"}),

    # ---- AI infra / applied research unicorns ----
    Firm("Cerebras", "ashby", {"board": "cerebras"}),
    Firm("Tenstorrent", "greenhouse", {"board": "tenstorrent"}),
    Firm("Etched", "ashby", {"board": "etched"}),
    Firm("MatX", "greenhouse", {"board": "matx"}),
    Firm("Baseten", "ashby", {"board": "baseten"}),
    Firm("Fireworks AI", "ashby", {"board": "fireworksai"}),
    Firm("OpenRouter", "ashby", {"board": "openrouter"}),
    Firm("Poolside", "ashby", {"board": "poolside"}),
    Firm("Writer", "ashby", {"board": "writer"}),
    Firm("Typeface", "greenhouse", {"board": "typeface"}),
    Firm("Ideogram", "ashby", {"board": "ideogram"}),
    Firm("Pika", "ashby", {"board": "pika"}),
    Firm("Continue", "ashby", {"board": "continue"}),

    # ---- Robotics / embodied AI ----
    Firm("Figure AI", "greenhouse", {"board": "figureai"}),
    Firm("Physical Intelligence", "ashby", {"board": "physicalintelligence"}),
    Firm("Sanctuary AI", "ashby", {"board": "sanctuary"}),
    Firm("Wayve", "greenhouse", {"board": "wayve"}),

    # ---- Unicorns (fintech / productivity / other) ----
    Firm("Affirm", "greenhouse", {"board": "affirm"}),
    Firm("Chime", "greenhouse", {"board": "chime"}),
    Firm("SoFi", "greenhouse", {"board": "sofi"}),
    Firm("Marqeta", "greenhouse", {"board": "marqeta"}),
    Firm("Airtable", "greenhouse", {"board": "airtable"}),
    Firm("Webflow", "greenhouse", {"board": "webflow"}),
    Firm("Gusto", "greenhouse", {"board": "gusto"}),
    Firm("Relativity Space", "greenhouse", {"board": "relativity"}),
    Firm("Motional", "greenhouse", {"board": "motional"}),
    Firm("Skydio", "ashby", {"board": "skydio"}),

    # ---- Additional high-TC (verified boards) ----
    Firm("Wiz", "greenhouse", {"board": "wizinc"}),
    Firm("Rubrik", "greenhouse", {"board": "rubrik"}),
    Firm("StubHub", "greenhouse", {"board": "stubhubinc"}),
    Firm("Coupang", "greenhouse", {"board": "coupang"}),
    Firm("Roblox", "greenhouse", {"board": "roblox"}),
    Firm("Pinterest", "greenhouse", {"board": "pinterest"}),
    Firm("Elastic", "greenhouse", {"board": "elastic"}),
    Firm("Mercury", "greenhouse", {"board": "mercury"}),
    Firm("Monzo", "greenhouse", {"board": "monzo"}),
    Firm("IEX", "greenhouse", {"board": "iex"}),
    Firm("Synthesia", "ashby", {"board": "synthesia"}),
    Firm("Lambda", "ashby", {"board": "lambda"}),
    Firm("Sentry", "ashby", {"board": "sentry"}),
    Firm("Vanta", "ashby", {"board": "vanta"}),
    Firm("Normal Computing", "ashby", {"board": "normalcomputing"}),
    Firm("Ashby", "ashby", {"board": "ashby"}),

    # ---- Workday API firms ----
    Firm("G-Research", "workday", {
        "tenant": "gresearch",
        "site": "G-Research",
        "instance": "wd103",
    }),
    Firm("Nvidia", "workday", {
        "tenant": "nvidia",
        "site": "NVIDIAExternalCareerSite",
        "instance": "wd5",
        "page_size": 20,
    }),
    Firm("Salesforce", "workday", {
        "tenant": "salesforce",
        "site": "External_Career_Site",
        "instance": "wd12",
        "page_size": 20,
    }),
    Firm("Intel", "workday", {
        "tenant": "intel",
        "site": "External",
        "instance": "wd1",
        "page_size": 20,
    }),

    # ---- Custom / API scrapers (verified working) ----
    Firm("Google", "google", {"max_pages": 50}),
    Firm("Bloomberg", "bloomberg", {}),
    Firm("Meta", "meta", {}),
    Firm("Uber", "uber", {}),
    Firm("Two Sigma", "twosigma", {}),
    Firm("DE Shaw", "deshaw", {}),

    # ---- Headless-browser scrapers (JS-rendered career sites) ----
    Firm("Citadel", "browser", {
        # Citadel paginates campus roles at 10/page; walk a few pages.
        # Include both internships and new-graduate full-time postings.
        "urls": [
            (
                "https://www.citadel.com/careers/open-opportunities"
                "?experience-filter=internships,new-graduates"
                "&selected-job-sections=388,389,387,390"
                "&current_page=1&sort_order=DESC&per_page=10"
                "&action=careers_listing_filter"
            ),
            (
                "https://www.citadel.com/careers/open-opportunities/page/2"
                "?experience-filter=internships,new-graduates"
                "&selected-job-sections=388,389,387,390"
                "&current_page=2&sort_order=DESC&per_page=10"
                "&action=careers_listing_filter"
            ),
            (
                "https://www.citadel.com/careers/open-opportunities/page/3"
                "?experience-filter=internships,new-graduates"
                "&selected-job-sections=388,389,387,390"
                "&current_page=3&sort_order=DESC&per_page=10"
                "&action=careers_listing_filter"
            ),
            (
                "https://www.citadel.com/careers/open-opportunities/page/4"
                "?experience-filter=internships,new-graduates"
                "&selected-job-sections=388,389,387,390"
                "&current_page=4&sort_order=DESC&per_page=10"
                "&action=careers_listing_filter"
            ),
        ],
        "wait_for": "a[href*='/careers/details/']",
        "link_selector": "a[href*='/careers/details/']",
        "wait_until": "networkidle",
        "extra_wait_ms": 5000,
        "nav_timeout_ms": 60000,
    }),
    Firm("Citadel Securities", "browser", {
        "urls": [
            "https://www.citadelsecurities.com/careers/open-opportunities/students/",
            (
                "https://www.citadelsecurities.com/careers/open-opportunities/page/2"
                "?experience-filter=internships,new-graduates"
                "&selected-job-sections=323,325,324,326"
                "&current_page=2&sort_order=DESC&per_page=10"
                "&action=careers_listing_filter"
            ),
            (
                "https://www.citadelsecurities.com/careers/open-opportunities/page/3"
                "?experience-filter=internships,new-graduates"
                "&selected-job-sections=323,325,324,326"
                "&current_page=3&sort_order=DESC&per_page=10"
                "&action=careers_listing_filter"
            ),
        ],
        "wait_for": "a[href*='/careers/details/']",
        "link_selector": "a[href*='/careers/details/']",
        "wait_until": "networkidle",
        "extra_wait_ms": 5000,
        "nav_timeout_ms": 60000,
    }),
    Firm("SIG (Susquehanna)", "sig", {}),
    Firm("AQR Capital", "browser", {
        "url": "https://careers.aqr.com/jobs/category/university-jobs",
        # Listing page renders an empty state when no roles are open — treat
        # the body as the ready signal so we don't time out on empty pages.
        "wait_for": "body",
        "extra_wait_ms": 3000,
        # Job detail slugs live at /jobs/<slug>; exclude the /category/ pages.
        "link_selector": "a[href*='/jobs/']:not([href*='/category/'])",
    }),
    Firm("Voleon", "ashby", {"board": "voleon"}),
    Firm("Millennium", "eightfold", {
        "domain": "mlp.com",
        "api_host": "mlp.eightfold.ai",
    }),
    Firm("Qube Research & Technologies", "browser", {
        "url": "https://www.qube-rt.com/careers/",
        # QRT lazy-loads the job list well after domcontentloaded. Waiting
        # for the link selector directly often fires before any jobs exist
        # in the DOM; wait for body + scroll + generous sleep instead.
        "wait_for": "body",
        "extra_wait_ms": 15000,
        "scroll_count": 3,
        # Links in the rendered DOM are relative ("job?gh_jid=NNN"), so
        # match on the Greenhouse id query param instead of an absolute
        # /careers/job?... prefix (which never matches).
        "link_selector": "a[href*='gh_jid=']",
    }),
    Firm("Headlands Technologies", "browser", {
        "url": "https://www.headlandstech.com/",
        "wait_for": "body",
        # Headlands does not publish individual job postings; this will
        # almost always return 0. Kept for visibility in --diagnose.
        "link_selector": "a[href*='career'], a[href*='job']",
    }),
]

# De-duplicate firms sharing the same board (e.g. Point72/Cubist)
_seen: set[str] = set()
_deduped: list[Firm] = []
for _f in FIRMS:
    _key = f"{_f.scrape_fn}:{json.dumps(_f.config, sort_keys=True)}"
    if _key not in _seen:
        _seen.add(_key)
        _deduped.append(_f)
FIRMS = _deduped


# ---------------------------------------------------------------------------
# Scrapers
# ---------------------------------------------------------------------------

def _parse_greenhouse_jobs(firm_name: str, data: dict) -> list[Job]:
    jobs = []
    for j in data.get("jobs", []):
        location = j.get("location", {}).get("name", "")
        job_url = j.get("absolute_url", "")
        title = j.get("title", "")
        departments = ", ".join(d.get("name", "") for d in j.get("departments", []))
        jobs.append(Job(
            firm=firm_name,
            title=title,
            location=location,
            url=job_url,
            department=departments,
        ))
    return jobs


def scrape_greenhouse(firm: Firm) -> list[Job]:
    board = firm.config["board"]
    url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return _parse_greenhouse_jobs(firm.name, resp.json())


def scrape_greenhouse_multi(firm: Firm) -> list[Job]:
    """Scrape multiple Greenhouse boards for a single firm."""
    jobs = []
    for board in firm.config["boards"]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            jobs.extend(_parse_greenhouse_jobs(firm.name, resp.json()))
        except Exception:
            pass
    return jobs


def scrape_lever(firm: Firm) -> list[Job]:
    company = firm.config["company"]
    url = f"https://api.lever.co/v0/postings/{company}"
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    jobs = []
    for j in data:
        location = j.get("categories", {}).get("location", "")
        title = j.get("text", "")
        job_url = j.get("hostedUrl", "")
        team = j.get("categories", {}).get("team", "")
        jobs.append(Job(
            firm=firm.name,
            title=title,
            location=location,
            url=job_url,
            department=team,
        ))
    return jobs


def scrape_wolve(firm: Firm) -> list[Job]:
    """Scrape Wolverine Trading's public careers JSON feed."""
    resp = requests.get(
        "https://careers.wolve.com/postings",
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    jobs: list[Job] = []
    for posting in resp.json().get("data", []):
        title = posting.get("title") or ""
        url = posting.get("url") or ""
        loc = posting.get("location") or {}
        location = loc.get("name") or ""
        if title:
            jobs.append(Job(
                firm=firm.name,
                title=title,
                location=location,
                url=url,
            ))
    return jobs


def scrape_deshaw(firm: Firm) -> list[Job]:
    """Scrape DE Shaw's campus recruiting page which has real internship links."""
    jobs = []
    for url in [
        "https://campus.deshaw.com/internships",
        "https://www.deshaw.com/careers/internships",
    ]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a[href*='/careers/'][href*='intern'], a[href*='/careers/'][href*='summer']"):
                title = link.get_text(strip=True)
                href = link.get("href", "")
                if title and 10 < len(title) < 200:
                    if not href.startswith("http"):
                        href = f"https://www.deshaw.com{href}"
                    jobs.append(Job(firm=firm.name, title=title, url=href))
        except Exception:
            pass
    seen = set()
    deduped = []
    for j in jobs:
        key = (j.title, j.url)
        if key not in seen:
            seen.add(key)
            deduped.append(j)
    return deduped



def scrape_twosigma(firm: Firm) -> list[Job]:
    """Two Sigma uses their own career site at careers.twosigma.com."""
    jobs = []
    for url in [
        "https://careers.twosigma.com/careers/InternshipsAndEarlyCareers",
        "https://careers.twosigma.com/careers/SearchJobs",
    ]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.select("a[href*='JobDetail']"):
                title = link.get_text(strip=True)
                href = link.get("href", "")
                if title and 5 < len(title) < 200:
                    if not href.startswith("http"):
                        href = f"https://careers.twosigma.com{href}"
                    jobs.append(Job(firm=firm.name, title=title, url=href))
        except Exception:
            pass
    seen = set()
    deduped = []
    for j in jobs:
        key = (j.title, j.url)
        if key not in seen:
            seen.add(key)
            deduped.append(j)
    return deduped


def scrape_workday(firm: Firm) -> list[Job]:
    """Scrape jobs from a Workday ATS instance (JSON API)."""
    tenant = firm.config["tenant"]
    site = firm.config["site"]
    instance = firm.config.get("instance", "wd5")
    base = f"https://{tenant}.{instance}.myworkdayjobs.com"
    api_url = f"{base}/wday/cxs/{tenant}/{site}/jobs"

    jobs = []
    offset = 0
    page_size = int(firm.config.get("page_size", 20))
    while True:
        payload = {"appliedFacets": {}, "limit": page_size, "offset": offset, "searchText": ""}
        resp = requests.post(
            api_url,
            json=payload,
            headers={**HEADERS, "Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("jobPostings", [])
        if not postings:
            break
        for p in postings:
            title = p.get("title", "")
            location = p.get("locationsText", "")
            path = p.get("externalPath", "")
            job_url = f"{base}/en-US{path}" if path else ""
            jobs.append(Job(firm=firm.name, title=title, location=location, url=job_url))
        offset += len(postings)
        total = data.get("total") or 0
        if total and offset >= total:
            break
    return jobs


def scrape_ashby(firm: Firm) -> list[Job]:
    """Scrape an Ashby-hosted job board via its public posting API."""
    board = firm.config["board"]
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    jobs = []
    for j in resp.json().get("jobs", []):
        title = j.get("title", "")
        if not title:
            continue
        location = j.get("location", "")
        department = j.get("team", "") or j.get("department", "")
        job_url = j.get("jobUrl", "")
        jobs.append(Job(
            firm=firm.name,
            title=title,
            location=location,
            url=job_url,
            department=department,
        ))
    return jobs


def scrape_sig(firm: Firm) -> list[Job]:
    """Scrape SIG's iCIMS career site via its public JSON API."""
    api_url = firm.config.get("api_url", "https://careers.sig.com/api/jobs")
    page_size = int(firm.config.get("page_size", 10))
    max_pages = int(firm.config.get("max_pages", 30))
    jobs: list[Job] = []
    seen_ids: set[str] = set()

    for page in range(1, max_pages + 1):
        resp = requests.get(
            api_url,
            params={
                "page": page,
                "sortBy": "relevance",
                "descending": "false",
                "internal": "false",
            },
            headers={**HEADERS, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        postings = data.get("jobs", []) or []
        if not postings:
            break

        new_on_page = 0
        for posting in postings:
            row = posting.get("data", posting)
            req_id = str(row.get("req_id") or row.get("slug") or "")
            if not req_id or req_id in seen_ids:
                continue
            seen_ids.add(req_id)
            new_on_page += 1

            title = row.get("title", "")
            if not title:
                continue
            location = (
                row.get("full_location")
                or row.get("location_name")
                or ", ".join(
                    x for x in (row.get("city"), row.get("state"), row.get("country")) if x
                )
            )
            slug = row.get("slug") or req_id
            lang = row.get("language", "en-us")
            job_url = f"https://careers.sig.com/jobs/{slug}?lang={lang}"
            department = row.get("department", "") or row.get("category", "")
            jobs.append(Job(
                firm=firm.name,
                title=title,
                location=location,
                url=job_url,
                department=department,
            ))

        total = data.get("totalCount") or data.get("count") or 0
        if total and page * page_size >= total:
            break
        if new_on_page == 0:
            break

    return jobs


def _uber_format_location(raw) -> str:
    if not raw:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        parts = [raw.get("name"), raw.get("city"), raw.get("state"), raw.get("country")]
        return ", ".join(p for p in parts if p)
    if isinstance(raw, list):
        return "; ".join(_uber_format_location(x) for x in raw if x)
    return str(raw)


def scrape_uber(firm: Firm) -> list[Job]:
    """Scrape Uber's careers site via its CSRF-protected search API."""
    import json
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

    list_url = firm.config.get("list_url", "https://www.uber.com/us/en/careers/list/")
    page_size = int(firm.config.get("page_size", 50))
    max_pages = int(firm.config.get("max_pages", 80))
    api_url = firm.config.get(
        "api_url",
        "https://www.uber.com/api/loadSearchJobsResults?localeCode=en",
    )
    jobs: list[Job] = []
    seen_ids: set[int] = set()

    with sync_playwright() as pw:
        browser = _launch_playwright_browser(pw)
        context = browser.new_context(user_agent=BROWSER_USER_AGENT)
        page = context.new_page()
        api_headers = {"Content-Type": "application/json", "x-csrf-token": "x"}

        def on_request(req):
            if "loadSearchJobsResults" in req.url:
                api_headers.clear()
                api_headers.update({
                    k: v for k, v in req.headers.items()
                    if k.lower() in ("content-type", "x-csrf-token", "accept")
                })

        page.on("request", on_request)
        try:
            page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
        except PWTimeoutError:
            pass
        page.wait_for_timeout(5000)

        for page_num in range(max_pages):
            body = json.dumps({
                "limit": page_size,
                "page": page_num,
                "params": {
                    "department": [],
                    "lineOfBusinessName": [],
                    "location": [],
                    "programAndPlatform": [],
                    "team": [],
                },
            })
            resp = context.request.post(api_url, headers=api_headers, data=body)
            if not resp.ok:
                break
            payload = resp.json()
            if payload.get("status") != "success":
                break
            data = payload.get("data") or {}
            results = data.get("results") or []
            if not results:
                break

            new_on_page = 0
            for row in results:
                jid = row.get("id")
                if jid is None or jid in seen_ids:
                    continue
                seen_ids.add(jid)
                new_on_page += 1
                title = row.get("title", "")
                if not title:
                    continue
                location = _uber_format_location(row.get("location"))
                if not location:
                    location = _uber_format_location(row.get("allLocations"))
                department = row.get("department") or row.get("team") or ""
                job_url = f"https://www.uber.com/us/en/careers/list/{jid}/"
                jobs.append(Job(
                    firm=firm.name,
                    title=title,
                    location=location,
                    url=job_url,
                    department=str(department),
                ))

            total = data.get("totalResults")
            if isinstance(total, (int, float)) and (page_num + 1) * page_size >= total:
                break
            if new_on_page == 0:
                break

        browser.close()
    return jobs


def _launch_playwright_browser(pw, channels: tuple[str | None, ...] = ("chrome", "msedge", None)):
    """Launch Chromium, preferring a real Chrome/Edge install when available."""
    launch_args = ["--disable-blink-features=AutomationControlled"]
    last_error: Exception | None = None
    for channel in channels:
        kwargs = {"headless": True, "args": launch_args}
        if channel:
            kwargs["channel"] = channel
        try:
            return pw.chromium.launch(**kwargs)
        except Exception as e:
            last_error = e
    if last_error:
        raise last_error
    raise RuntimeError("Failed to launch Playwright browser")


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def _extract_jobs_from_html(firm_name: str, html: str, page_url: str, selector: str) -> list[Job]:
    """Parse jobs out of a rendered HTML page using a link CSS selector."""
    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for a in soup.select(selector):
        title = a.get_text(" ", strip=True)
        href = a.get("href", "") or ""
        if not title or not (5 < len(title) < 200):
            continue
        if href and not href.startswith(("http://", "https://")):
            href = urljoin(page_url, href)
        jobs.append(Job(firm=firm_name, title=title, url=href))
    return jobs


def scrape_browser(firm: Firm, browser=None) -> list[Job]:
    """Generic Playwright scraper. Loads a page (or list of pages), waits for
    the configured selector, then extracts job links via BeautifulSoup.

    ``browser`` may be a pre-launched Playwright Browser — if ``None`` we
    launch our own, useful for ad-hoc testing.
    """
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

    cfg = firm.config
    urls = cfg.get("urls") or [cfg["url"]]
    wait_for = cfg.get("wait_for", "body")
    link_selector = cfg["link_selector"]
    extra_wait_ms = int(cfg.get("extra_wait_ms", 0))
    scroll_count = int(cfg.get("scroll_count", 0))
    wait_until = cfg.get("wait_until", "domcontentloaded")
    nav_timeout = int(cfg.get("nav_timeout_ms", 20000))
    wait_timeout = int(cfg.get("wait_timeout_ms", 15000))

    owns_browser = browser is None
    pw = None
    jobs: list[Job] = []
    try:
        if owns_browser:
            pw = sync_playwright().start()
            browser = _launch_playwright_browser(pw)
        # Use a fresh context per URL: some sites (e.g. Citadel) stop
        # rendering listing content on subsequent requests from the same
        # session, presumably anti-bot throttling.
        for url in urls:
            context = browser.new_context(user_agent=BROWSER_USER_AGENT)
            try:
                page = context.new_page()
                try:
                    try:
                        page.goto(url, wait_until=wait_until, timeout=nav_timeout)
                    except PWTimeoutError:
                        continue
                    try:
                        page.wait_for_selector(wait_for, timeout=wait_timeout)
                    except PWTimeoutError:
                        pass
                    for _ in range(scroll_count):
                        try:
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        except Exception:
                            break
                        page.wait_for_timeout(800)
                    if extra_wait_ms:
                        page.wait_for_timeout(extra_wait_ms)
                    html = page.content()
                    jobs.extend(_extract_jobs_from_html(firm.name, html, url, link_selector))
                finally:
                    page.close()
            finally:
                context.close()
    finally:
        if owns_browser:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass
            if pw is not None:
                pw.stop()

    seen = set()
    deduped = []
    for j in jobs:
        key = (j.title, j.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(j)
    return deduped


def scrape_eightfold(firm: Firm) -> list[Job]:
    """Scrape an Eightfold-hosted career site via its public JSON API.

    Used for firms (e.g. Millennium) where the Eightfold UI is client-side
    rendered in a way headless Chromium cannot see, but the underlying API
    returns the same listings with a plain HTTP GET.
    """
    api_host = firm.config.get("api_host")
    domain = firm.config["domain"]
    base = f"https://{api_host}" if api_host else f"https://{domain}"
    api_url = f"{base}/api/apply/v2/jobs"

    jobs: list[Job] = []
    seen_ids: set = set()
    start = 0
    page_size = int(firm.config.get("page_size", 10))
    max_pages = int(firm.config.get("max_pages", 30))
    for _ in range(max_pages):
        params = {
            "domain": domain,
            "start": start,
            "num": page_size,
            "sort_by": "relevance",
        }
        resp = requests.get(
            api_url,
            params=params,
            headers={**HEADERS, "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        positions = data.get("positions", []) or []
        if not positions:
            break
        new_on_page = 0
        for p in positions:
            pid = p.get("id")
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            new_on_page += 1
            title = p.get("name") or p.get("posting_name") or ""
            locs = p.get("locations") or ([p["location"]] if p.get("location") else [])
            location = "; ".join(locs)
            url = p.get("canonicalPositionUrl") or ""
            if not url and pid:
                url = f"{base}/careers/job/{pid}"
            department = p.get("department", "") or ""
            if title:
                jobs.append(Job(
                    firm=firm.name,
                    title=title,
                    location=location,
                    url=url,
                    department=department,
                ))
        start += len(positions)
        total = data.get("count") or data.get("total") or 0
        # Eightfold often ignores `num` and returns a fixed page size; we rely
        # on the reported count and stop once we've seen every ID or the
        # server stops returning new ones.
        if total and start >= total:
            break
        if new_on_page == 0:
            break
    return jobs


_GOOGLE_DS1_RE = re.compile(
    r"AF_initDataCallback\(\{key: 'ds:1', hash: '[^']+', data:(.*?), sideChannel:",
    re.S,
)


def _google_format_locations(loc_field) -> str:
    locs: list[str] = []
    if isinstance(loc_field, list):
        for item in loc_field:
            if isinstance(item, list) and item and isinstance(item[0], str):
                locs.append(item[0])
    return "; ".join(locs)


def _fetch_google_jobs_page(page_num: int, location: str = "") -> list[list]:
    """Return raw job card arrays from a Google careers results page."""
    from urllib.parse import quote

    params = f"distance=50&page={page_num}&q=&sort_by=date"
    if location:
        params += f"&location={quote(location)}"
    url = (
        "https://www.google.com/about/careers/applications/jobs/results/"
        f"?{params}"
    )
    resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    match = _GOOGLE_DS1_RE.search(resp.text)
    if not match:
        return []
    data = json.loads(match.group(1))
    if not data or not isinstance(data[0], list):
        return []
    return data[0]


def scrape_google(firm: Firm) -> list[Job]:
    """Scrape Google careers via embedded AF_initDataCallback payloads."""
    max_pages = int(firm.config.get("max_pages", 50))
    location = firm.config.get("location", "")
    jobs: list[Job] = []
    seen_ids: set[str] = set()

    for page_num in range(1, max_pages + 1):
        cards = _fetch_google_jobs_page(page_num, location=location)
        if not cards:
            break
        new_on_page = 0
        for card in cards:
            if not isinstance(card, list) or not card:
                continue
            jid = str(card[0]) if card[0] is not None else ""
            if not jid or jid in seen_ids:
                continue
            seen_ids.add(jid)
            new_on_page += 1
            title = str(card[1]) if len(card) > 1 and card[1] is not None else ""
            loc_field = card[9] if len(card) > 9 else None
            location_text = _google_format_locations(loc_field)
            job_url = (
                "https://www.google.com/about/careers/applications/"
                f"jobs/results/{jid}"
            )
            if title:
                jobs.append(Job(
                    firm=firm.name,
                    title=title,
                    location=location_text,
                    url=job_url,
                ))
        if new_on_page == 0:
            break
    return jobs


def _parse_bloomberg_html(firm_name: str, html: str) -> list[Job]:
    soup = BeautifulSoup(html, "html.parser")
    jobs: list[Job] = []
    for article in soup.select("article.article--result"):
        link = article.select_one("a.link[href*='JobDetail']")
        if not link:
            continue
        title = link.get_text(" ", strip=True)
        href = link.get("href", "") or ""
        if href and not href.startswith(("http://", "https://")):
            href = urljoin("https://bloomberg.avature.net", href)
        loc_el = article.select_one(".article__header__text__subtitle")
        location = loc_el.get_text(" ", strip=True) if loc_el else ""
        if title:
            jobs.append(Job(firm=firm_name, title=title, location=location, url=href))
    return jobs


def scrape_bloomberg(firm: Firm) -> list[Job]:
    """Scrape Bloomberg's Avature-hosted careers site."""
    base = firm.config.get(
        "base_url",
        "https://bloomberg.avature.net/careers/SearchJobs",
    )
    page_size = int(firm.config.get("page_size", 24))
    max_pages = int(firm.config.get("max_pages", 30))
    jobs: list[Job] = []
    seen_urls: set[str] = set()
    offset = 0

    for _ in range(max_pages):
        if offset == 0:
            resp = requests.get(base, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        else:
            resp = requests.post(
                base,
                data={
                    "jobRecordsPerPage": str(page_size),
                    "jobOffset": str(offset),
                    "sortBy": "date",
                },
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )
        resp.raise_for_status()
        page_jobs = _parse_bloomberg_html(firm.name, resp.text)
        if not page_jobs:
            break
        new_on_page = 0
        for job in page_jobs:
            key = job.url or (job.title, job.location)
            if key in seen_urls:
                continue
            seen_urls.add(key)
            new_on_page += 1
            jobs.append(job)
        if new_on_page == 0:
            break
        offset += page_size
    return jobs


def scrape_meta(firm: Firm) -> list[Job]:
    """Scrape Meta careers via GraphQL responses captured in Playwright."""
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

    list_url = firm.config.get("list_url", "https://www.metacareers.com/jobs")
    wait_ms = int(firm.config.get("extra_wait_ms", 10000))
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    captured: list[dict] = []

    def on_response(resp):
        if "metacareers.com/graphql" not in resp.url:
            return
        try:
            text = resp.text()
            if text.startswith("for (;;);"):
                text = text[9:]
            data = json.loads(text)
            block = data.get("data", {}).get("job_search_with_featured_jobs_v2")
            if block and block.get("all_jobs"):
                captured.extend(block["all_jobs"])
        except Exception:
            pass

    with sync_playwright() as pw:
        browser = _launch_playwright_browser(pw)
        context = browser.new_context(user_agent=BROWSER_USER_AGENT, locale="en-US")
        page = context.new_page()
        page.on("response", on_response)
        try:
            page.goto(list_url, wait_until="domcontentloaded", timeout=60000)
        except PWTimeoutError:
            pass
        page.wait_for_timeout(wait_ms)
        browser.close()

    for row in captured:
        jid = str(row.get("id", ""))
        if not jid or jid in seen_ids:
            continue
        seen_ids.add(jid)
        title = row.get("title", "") or ""
        locations = row.get("locations") or []
        if isinstance(locations, list):
            location = "; ".join(str(x) for x in locations if x)
        else:
            location = str(locations)
        teams = row.get("teams") or []
        department = ", ".join(str(x) for x in teams) if isinstance(teams, list) else str(teams)
        job_url = f"https://www.metacareers.com/jobs/{jid}"
        if title:
            jobs.append(Job(
                firm=firm.name,
                title=title,
                location=location,
                url=job_url,
                department=department,
            ))
    return jobs


SCRAPER_MAP = {
    "greenhouse": scrape_greenhouse,
    "greenhouse_multi": scrape_greenhouse_multi,
    "workday": scrape_workday,
    "lever": scrape_lever,
    "wolve": scrape_wolve,
    "twosigma": scrape_twosigma,
    "deshaw": scrape_deshaw,
    "browser": scrape_browser,
    "eightfold": scrape_eightfold,
    "ashby": scrape_ashby,
    "sig": scrape_sig,
    "uber": scrape_uber,
    "google": scrape_google,
    "bloomberg": scrape_bloomberg,
    "meta": scrape_meta,
}


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def _has_us_signal(text: str) -> bool:
    lower = text.lower()
    if any(hint in lower for hint in US_LOCATION_HINTS):
        return True
    if _US_ABBREV_PATTERN.search(text):
        return True
    if "usa" in lower.split():
        return True
    return False


def _is_us_location(job: Job) -> bool:
    loc = job.location
    title = job.title
    url = job.url or ""
    # Job posting URLs frequently encode the city/region in the path
    # (e.g. ".../london/...", ".../hong-kong/..."). Including the URL
    # in the scan helps reject non-US roles when the location field is
    # empty (common for browser-scraped firms that only return a title).
    combined = f"{loc} {title} {url}"
    combined_lower = combined.lower()

    has_non_us = any(hint in combined_lower for hint in NON_US_LOCATION_HINTS)
    has_us = _has_us_signal(combined)

    if has_non_us and not has_us:
        return False

    if loc and loc != "—":
        return _has_us_signal(loc)

    return True


def is_undergrad_opportunity(job: Job) -> bool:
    text = f"{job.title} {job.department}".lower()
    if not UNDERGRAD_PATTERN.search(text):
        return False
    if EXCLUDE_TITLE_PATTERNS.search(job.title):
        return False
    if STALE_PATTERN.search(job.title):
        return False
    if not _is_us_location(job):
        return False
    return True


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

@dataclass
class FirmResult:
    name: str
    total_scraped: int = 0
    matched: list = field(default_factory=list)
    error: str | None = None


@dataclass
class RunResult:
    new_jobs: list[Job]
    returning_jobs: list[Job]
    all_jobs: list[Job]
    firm_results: dict[str, FirmResult]

    @property
    def errors(self) -> dict[str, str]:
        return {
            name: res.error
            for name, res in self.firm_results.items()
            if res.error
        }


def scrape_firm(firm: Firm) -> FirmResult:
    fn = SCRAPER_MAP.get(firm.scrape_fn)
    if fn is None:
        return FirmResult(firm.name, error=f"No scraper registered for '{firm.scrape_fn}'")
    try:
        all_jobs = fn(firm)
        relevant = [j for j in all_jobs if is_undergrad_opportunity(j)]
        return FirmResult(firm.name, total_scraped=len(all_jobs), matched=relevant)
    except Exception as e:
        return FirmResult(firm.name, error=str(e))


def _scrape_browser_firms(browser_firms: list[Firm]) -> dict[str, FirmResult]:
    """Run browser-backed scrapers sequentially with a single shared Chromium
    instance. Playwright's sync API is not thread-safe, so we keep this out of
    the main ThreadPoolExecutor.
    """
    results: dict[str, FirmResult] = {}
    if not browser_firms:
        return results
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        for firm in browser_firms:
            results[firm.name] = FirmResult(
                firm.name,
                error="playwright not installed (pip install playwright && python -m playwright install chromium)",
            )
        return results

    with sync_playwright() as pw:
        browser = _launch_playwright_browser(pw)
        try:
            for firm in browser_firms:
                try:
                    jobs = scrape_browser(firm, browser=browser)
                    relevant = [j for j in jobs if is_undergrad_opportunity(j)]
                    results[firm.name] = FirmResult(
                        firm.name,
                        total_scraped=len(jobs),
                        matched=relevant,
                    )
                except Exception as e:
                    results[firm.name] = FirmResult(firm.name, error=str(e))
        finally:
            browser.close()
    return results


HISTORY_FILE = Path(__file__).parent / "seen_jobs.json"


def _job_key(job: Job) -> str:
    """Stable identity for a posting so we can detect new vs. already-seen."""
    return f"{job.firm}||{job.title}||{job.url}"


def _load_seen() -> dict:
    """Load previously seen jobs. Returns {key: job_dict, ...}."""
    if HISTORY_FILE.exists():
        try:
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            return {entry["_key"]: entry for entry in data}
        except (json.JSONDecodeError, KeyError):
            return {}
    return {}


def _save_seen(seen: dict):
    HISTORY_FILE.write_text(
        json.dumps(list(seen.values()), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def run(workers: int = 8, diagnose: bool = False, *, persist_history: bool = True) -> RunResult | None:
    console.print(
        Panel(
            "[bold]Quant & Tech Early-Career Opportunity Scraper[/bold]\n"
            f"Checking {len(FIRMS)} firms for US internships, insight programs,\n"
            "and new-graduate / full-time campus roles …",
            style="cyan",
        )
    )

    firm_results: dict[str, FirmResult] = {}

    PLAYWRIGHT_BACKED = frozenset({"browser", "uber", "meta"})
    http_firms = [f for f in FIRMS if f.scrape_fn not in PLAYWRIGHT_BACKED]
    browser_firms = [f for f in FIRMS if f.scrape_fn == "browser"]
    uber_firms = [f for f in FIRMS if f.scrape_fn == "uber"]
    meta_firms = [f for f in FIRMS if f.scrape_fn == "meta"]

    with console.status("[bold green]Scraping career pages…", spinner="dots"):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(scrape_firm, f): f for f in http_firms}
            for fut in as_completed(futures):
                res = fut.result()
                firm_results[res.name] = res

    if browser_firms:
        with console.status(
            f"[bold green]Rendering {len(browser_firms)} JS-heavy career pages in Chromium…",
            spinner="dots",
        ):
            firm_results.update(_scrape_browser_firms(browser_firms))

    if uber_firms:
        with console.status(
            f"[bold green]Fetching {len(uber_firms)} Uber API career page(s) in Chromium…",
            spinner="dots",
        ):
            for firm in uber_firms:
                firm_results[firm.name] = scrape_firm(firm)

    if meta_firms:
        with console.status(
            f"[bold green]Fetching {len(meta_firms)} Meta GraphQL career page(s) in Chromium…",
            spinner="dots",
        ):
            for firm in meta_firms:
                firm_results[firm.name] = scrape_firm(firm)

    # ---- Diagnose mode: show per-firm scraper health ----
    if diagnose:
        diag = Table(
            title="Scraper Diagnostics (per firm)",
            box=box.ROUNDED,
            show_lines=True,
            title_style="bold yellow",
        )
        diag.add_column("Firm", style="bold cyan", min_width=22)
        diag.add_column("Method", style="dim", min_width=12)
        diag.add_column("Total Jobs\nScraped", justify="right", min_width=8)
        diag.add_column("Matched\n(US early-career)", justify="right", min_width=8)
        diag.add_column("Status", min_width=20)

        for firm in FIRMS:
            res = firm_results.get(firm.name, FirmResult(firm.name))
            method = firm.scrape_fn
            total = res.total_scraped
            matched = len(res.matched)

            if res.error:
                status = f"[red]ERROR: {res.error[:60]}[/red]"
            elif total == 0:
                status = "[yellow]0 jobs returned — check selectors or site state[/yellow]"
            elif matched == 0:
                status = f"[green]OK[/green] [dim](no US early-career roles found)[/dim]"
            else:
                status = f"[bold green]OK — {matched} US early-career roles[/bold green]"

            diag.add_row(firm.name, method, str(total), str(matched), status)

        console.print()
        console.print(diag)
        return None

    # Flatten all jobs and figure out which are new
    all_jobs: list[Job] = []
    for firm in FIRMS:
        res = firm_results.get(firm.name)
        if res:
            all_jobs.extend(res.matched)

    prev_seen = _load_seen()
    new_jobs: list[Job] = []
    returning_jobs: list[Job] = []

    for job in all_jobs:
        if _job_key(job) in prev_seen:
            returning_jobs.append(job)
        else:
            new_jobs.append(job)

    # Update the history file with everything we see this run
    if persist_history:
        updated_seen = dict(prev_seen)
        for job in all_jobs:
            key = _job_key(job)
            if key not in updated_seen:
                updated_seen[key] = {
                    "_key": key,
                    "firm": job.firm,
                    "title": job.title,
                    "location": job.location,
                    "url": job.url,
                    "department": job.department,
                }
        _save_seen(updated_seen)

    # ---- NEW postings table ----
    if new_jobs:
        new_table = Table(
            title="NEW Postings (not seen in previous runs)",
            box=box.ROUNDED,
            show_lines=True,
            title_style="bold green",
        )
        new_table.add_column("Firm", style="bold cyan", min_width=20)
        new_table.add_column("Role", style="bold white", min_width=30)
        new_table.add_column("Location", style="green")
        new_table.add_column("Link", style="blue", overflow="fold")

        for job in new_jobs:
            new_table.add_row(job.firm, job.title, job.location or "—", job.url or "—")

        console.print()
        console.print(new_table)
    else:
        console.print("\n[dim]No new postings since last run.[/dim]")

    # ---- Previously seen table ----
    if returning_jobs:
        old_table = Table(
            title="Previously Seen (still open)",
            box=box.SIMPLE,
            show_lines=False,
            title_style="dim",
        )
        old_table.add_column("Firm", style="dim cyan", min_width=20)
        old_table.add_column("Role", style="dim", min_width=30)
        old_table.add_column("Location", style="dim green")
        old_table.add_column("Link", style="dim blue", overflow="fold")

        for job in returning_jobs:
            old_table.add_row(job.firm, job.title, job.location or "—", job.url or "—")

        console.print()
        console.print(old_table)

    # ---- Summary ----
    console.print()
    firms_with_hits = sum(1 for r in firm_results.values() if r.matched)
    summary_parts = [
        f"[bold green]{len(new_jobs)}[/bold green] new",
        f"[dim]{len(returning_jobs)} previously seen[/dim]",
        f"[bold]{len(all_jobs)}[/bold] total across "
        f"[bold]{firms_with_hits}[/bold] / {len(FIRMS)} firms",
    ]
    console.print(Panel(" · ".join(summary_parts), title="Summary", style="green"))
    if persist_history:
        console.print(f"[dim]History saved to {HISTORY_FILE}[/dim]")
    else:
        console.print("[dim]History not saved (persist_history=False).[/dim]")

    errors = {r.name: r.error for r in firm_results.values() if r.error}
    if errors:
        console.print()
        err_table = Table(title="Firms with scrape issues", box=box.SIMPLE, title_style="yellow")
        err_table.add_column("Firm", style="yellow")
        err_table.add_column("Error", style="dim")
        for name, msg in sorted(errors.items()):
            err_table.add_row(name, msg[:120])
        console.print(err_table)

    return RunResult(
        new_jobs=new_jobs,
        returning_jobs=returning_jobs,
        all_jobs=all_jobs,
        firm_results=firm_results,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape quant firm career pages for undergrad opportunities.")
    parser.add_argument("--workers", type=int, default=8, help="Number of parallel scraping threads (default: 8)")
    parser.add_argument("--reset", action="store_true", help="Clear history and treat all postings as new")
    parser.add_argument("--diagnose", action="store_true", help="Show per-firm scraper health instead of job listings")
    args = parser.parse_args()
    if args.reset and HISTORY_FILE.exists():
        HISTORY_FILE.unlink()
        console.print("[yellow]History cleared — all postings will appear as new.[/yellow]")
    run(workers=args.workers, diagnose=args.diagnose)
