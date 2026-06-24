import requests
for start in (0, 10, 50):
    r = requests.get(
        "https://mlp.eightfold.ai/api/apply/v2/jobs",
        params={"domain": "mlp.com", "start": start, "num": 50, "sort_by": "relevance"},
        headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
        timeout=20,
    )
    d = r.json()
    print(f"start={start}: positions={len(d.get('positions', []))} count={d.get('count')} total={d.get('total')}")
