"""Post new job postings to a Discord channel via webhook."""

import time
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from scrape_quant_jobs import Job

DISCORD_EMBED_LIMIT = 10
DISCORD_FIELD_VALUE_LIMIT = 1024
DISCORD_TITLE_LIMIT = 256


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _job_embed(job: "Job") -> dict:
    location = job.location.strip() if job.location else "—"
    embed = {
        "title": _truncate(job.title, DISCORD_TITLE_LIMIT),
        "color": 0x2ECC71,
        "fields": [
            {"name": "Company", "value": _truncate(job.firm, DISCORD_FIELD_VALUE_LIMIT), "inline": True},
            {"name": "Location", "value": _truncate(location, DISCORD_FIELD_VALUE_LIMIT), "inline": True},
        ],
    }
    if job.department:
        embed["fields"].append({
            "name": "Team",
            "value": _truncate(job.department, DISCORD_FIELD_VALUE_LIMIT),
            "inline": False,
        })
    if job.url:
        embed["url"] = job.url
    return embed


def post_new_jobs(
    jobs: list["Job"],
    webhook_url: str,
    *,
    mention_role_id: str | None = None,
    pause_seconds: float = 0.6,
) -> int:
    """Post job embeds to Discord. Returns number of webhook requests sent."""
    if not jobs or not webhook_url:
        return 0

    content = None
    if mention_role_id:
        content = f"<@&{mention_role_id}>"

    batches_sent = 0
    for i in range(0, len(jobs), DISCORD_EMBED_LIMIT):
        batch = jobs[i : i + DISCORD_EMBED_LIMIT]
        payload: dict = {"embeds": [_job_embed(job) for job in batch]}
        if i == 0 and content:
            payload["content"] = content

        resp = requests.post(webhook_url, json=payload, timeout=30)
        resp.raise_for_status()
        batches_sent += 1

        if i + DISCORD_EMBED_LIMIT < len(jobs):
            time.sleep(pause_seconds)

    return batches_sent
