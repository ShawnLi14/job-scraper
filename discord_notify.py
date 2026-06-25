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
    location = (job.location or "").strip() or "—"
    company = (job.firm or "").strip() or "—"
    embed = {
        "title": _truncate(job.title or "Untitled role", DISCORD_TITLE_LIMIT),
        "color": 0x2ECC71,
        "fields": [
            {"name": "Company", "value": _truncate(company, DISCORD_FIELD_VALUE_LIMIT), "inline": True},
            {"name": "Location", "value": _truncate(location, DISCORD_FIELD_VALUE_LIMIT), "inline": True},
        ],
    }
    if job.department:
        embed["fields"].append({
            "name": "Team",
            "value": _truncate(job.department.strip(), DISCORD_FIELD_VALUE_LIMIT),
            "inline": False,
        })
    url = (job.url or "").strip()
    if url.startswith(("http://", "https://")):
        embed["url"] = url
    return embed


def _post_webhook(webhook_url: str, payload: dict) -> None:
    resp = requests.post(webhook_url, json=payload, timeout=30)
    if not resp.ok:
        detail = resp.text.strip()[:500]
        raise RuntimeError(
            f"Discord webhook failed ({resp.status_code})"
            + (f": {detail}" if detail else "")
        )


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

    batches_sent = 0
    for i in range(0, len(jobs), DISCORD_EMBED_LIMIT):
        batch = jobs[i : i + DISCORD_EMBED_LIMIT]
        payload: dict = {"embeds": [_job_embed(job) for job in batch]}
        if i == 0 and mention_role_id:
            payload["content"] = f"<@&{mention_role_id}>"

        try:
            _post_webhook(webhook_url, payload)
        except RuntimeError:
            # Role mentions often cause 400s when the webhook cannot ping the role.
            if i == 0 and mention_role_id and payload.get("content"):
                retry_payload = dict(payload)
                retry_payload.pop("content", None)
                _post_webhook(webhook_url, retry_payload)
            else:
                raise
        batches_sent += 1

        if i + DISCORD_EMBED_LIMIT < len(jobs):
            time.sleep(pause_seconds)

    return batches_sent
