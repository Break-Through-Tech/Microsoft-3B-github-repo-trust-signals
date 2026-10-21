"""Read-only public engagement pilot. Search totals are indexed counts, not census."""

import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import time
from typing import Any
import urllib.parse

from collect_candidates import API, Client
from screening import utc

SETTINGS = {
    "openclaw/openclaw": ("2026-01-25", "2026-10-07T01:00:55.102345Z"),
    "deepseek-ai/DeepSeek-R1": ("2025-01-26", "2026-10-07T01:09:11.838599Z"),
    "morluto/rea": ("2026-10-04", "2026-10-13T23:05:20.483700Z"),
}


def periods(peak, reference):
    p = utc(peak + "T00:00:00Z")
    ref = utc(reference)
    values = [
        ("pre_4w", p - timedelta(weeks=4), p, 4),
        ("peak_1w", p, p + timedelta(weeks=1), 1),
        ("post_8w", p + timedelta(weeks=1), p + timedelta(weeks=9), 8),
    ]
    return [
        {
            "period": name,
            "start_utc": start.isoformat(),
            "end_exclusive_utc": end.isoformat(),
            "nominal_weeks": weeks,
            "complete_at_original_reference": end <= ref,
        }
        for name, start, end, weeks in values
    ]


def search_query(repo, kind, start, end):
    # GitHub timestamps have second resolution; inclusive range implements [start,end).
    s = utc(start).strftime("%Y-%m-%dT%H:%M:%SZ")
    e = (utc(end) - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"repo:{repo} is:{kind} created:{s}..{e}"


def main(args):
    out = args.output
    if not args.resume:
        out.mkdir(parents=True, exist_ok=False)
        (out / "config.json").write_text(
            json.dumps(
                {
                    "collection_reference_utc": datetime.now(UTC).isoformat(),
                    "release_page_cap": args.max_pages,
                    "fork_page_cap": args.fork_pages,
                    "search_semantics": "Current GitHub index totals by created_at; not historical census or record-level validation",
                    "fork_semantics": "Currently visible API-listed forks only; deleted/private historical forks not recovered",
                },
                indent=2,
            )
        )
    configs: list[dict[str, Any]] = []
    for repo, (peak, ref) in SETTINGS.items():
        client = Client(out / repo.replace("/", "_"))
        meta, resp = client.get(API + "/repos/" + repo, "metadata")
        configs.append(
            {
                "repository": meta["full_name"],
                "repo_id": meta["id"],
                "created_at": meta["created_at"],
                "metadata_collected_at": resp["collected_at_utc"],
                "periods": periods(peak, ref),
                "original_reference": ref,
            }
        )
    (out / "repositories.json").write_text(json.dumps(configs, indent=2))
    stream_results = []
    # Core API streams before the separately rate-limited search endpoint.
    for repo in configs:
        name = repo["repository"]
        client = Client(out / name.replace("/", "_"))
        for kind, cap, params in [("releases", args.max_pages, {}), ("forks", args.fork_pages, {"sort": "oldest"})]:
            result = {"repository": name, "stream": kind, "coverage": "missing", "records": [], "pages": 0}
            try:
                exhausted = False
                covered_end = False
                latest_required = max(
                    utc(p["end_exclusive_utc"]) for p in repo["periods"] if p["complete_at_original_reference"]
                )
                for page in range(1, cap + 1):
                    query = urllib.parse.urlencode(dict(params, per_page=100, page=page))
                    payload, response = client.get(
                        API + "/repos/" + name + "/" + kind + "?" + query, kind + "_page_" + str(page)
                    )
                    if not isinstance(payload, list):
                        raise ValueError("Expected array")
                    result["records"].extend(payload)
                    result["pages"] = page
                    if 'rel="next"' not in (response["headers"].get("Link") or ""):
                        exhausted = True
                        break
                    if kind == "forks" and payload:
                        stamps = [utc(r["created_at"]) for r in result["records"]]
                        if stamps != sorted(stamps):
                            raise ValueError("Fork order not monotonic")
                        if stamps[-1] >= latest_required:
                            covered_end = True
                            break
                result["coverage"] = (
                    "all_current_public_records"
                    if exhausted
                    else "visible_forks_through_window_end"
                    if covered_end
                    else "page_cap_lower_bound"
                )
            except Exception as error:
                result["error"] = str(error)
            stream_results.append(result)
            (out / "streams.json").write_text(json.dumps(stream_results, indent=2))
            print(name, kind, result["coverage"], len(result["records"]), flush=True)
    search_results = []
    for repo in configs:
        name = repo["repository"]
        client = Client(out / name.replace("/", "_"))
        for period in repo["periods"]:
            for kind in ["issue", "pr"]:
                row = {
                    "repository": name,
                    "event_kind": kind,
                    **period,
                    "search_reported_count": None,
                    "coverage": "unobserved_period",
                }
                if period["complete_at_original_reference"]:
                    query = search_query(name, kind, period["start_utc"], period["end_exclusive_utc"])
                    row["query"] = query
                    try:
                        payload, response = client.get(
                            API + "/search/issues?" + urllib.parse.urlencode({"q": query, "per_page": 1}),
                            "search_" + period["period"] + "_" + kind,
                        )
                        if "total_count" not in payload:
                            raise ValueError("Missing search count")
                        row.update(
                            search_reported_count=payload["total_count"],
                            incomplete_results=payload.get("incomplete_results", True),
                            collected_at_utc=response["collected_at_utc"],
                            coverage="indexed_count_complete_response"
                            if payload.get("incomplete_results") is False
                            else "incomplete_search_response",
                        )
                    except Exception as error:
                        row.update(coverage="collection_error", error=str(error))
                    print(name, period["period"], kind, row["search_reported_count"], row["coverage"], flush=True)
                    time.sleep(6.5)  # Public search permits only a small number per minute.
                search_results.append(row)
                (out / "search_counts.json").write_text(json.dumps(search_results, indent=2))
    print("Saved:", out, flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-pages", type=int, default=5)
    p.add_argument("--fork-pages", type=int, default=3)
    main(p.parse_args())
