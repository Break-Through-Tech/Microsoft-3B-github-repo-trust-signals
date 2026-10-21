"""Read-only public GitHub collection. Saves raw responses; never runs repo code."""

import argparse
import csv
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from screening import count_cached_commits, utc

API = "https://api.github.com"


def now():
    return datetime.now(UTC).isoformat()


class Client:
    def __init__(self, folder):
        self.folder = folder
        self.folder.mkdir(parents=True, exist_ok=True)

    def get(self, url, name):
        target = self.folder / (name + ".json")
        if target.exists():
            cached = json.loads(target.read_text(encoding="utf-8"))
            if cached["status"] == 200:
                return cached["body"], cached
            raise RuntimeError("Cached failed request: " + str(cached["status"]))
        for attempt in range(3):
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "BTT-temporal-research",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=35) as response:
                    body = response.read()
                    record = {
                        "url": url,
                        "returned_url": response.url,
                        "collected_at_utc": now(),
                        "status": response.status,
                        "headers": {
                            k: response.headers.get(k)
                            for k in ("Link", "Date", "ETag", "X-RateLimit-Remaining", "X-RateLimit-Reset")
                        },
                        "body_sha256": hashlib.sha256(body).hexdigest(),
                        "body": json.loads(body),
                    }
                target.write_text(json.dumps(record, indent=2), encoding="utf-8")
                return record["body"], record
            except urllib.error.HTTPError as error:
                record = {
                    "url": url,
                    "collected_at_utc": now(),
                    "status": error.code,
                    "error": error.read().decode("utf-8", errors="replace")[:2000],
                }
                target.write_text(json.dumps(record, indent=2), encoding="utf-8")
                if error.code in (429, 502, 503, 504) and attempt < 2:
                    time.sleep(min(int(error.headers.get("Retry-After", "2")), 10))
                    continue
                raise RuntimeError("HTTP " + str(error.code)) from None
            except urllib.error.URLError:
                if attempt == 2:
                    raise
                time.sleep(2)


def main(args):
    folder = args.output.resolve()
    config_file = folder / "collection_config.json"
    if args.resume:
        config = json.loads(config_file.read_text())
        reference = config["reference_time_utc"]
        args.max_pages = config["max_pages"]
    else:
        folder.mkdir(parents=True, exist_ok=False)
        reference = now()
        config = {
            "reference_time_utc": reference,
            "window_days": 90,
            "max_pages": args.max_pages,
            "method": "default-branch head SHA; committer UTC; roots included; merges excluded",
            "coverage_note": "Filtered API pagination is separate from exhaustive reachable-history validation. Low-count cases require exhaustive validation.",
        }
        config_file.write_text(json.dumps(config, indent=2))
    start = utc(reference) - timedelta(days=90)
    rows = list(csv.DictReader(args.queue.open(encoding="utf-8")))
    results = []
    for row in rows:
        name = row["full_name"]
        client = Client(folder / name.replace("/", "_"))
        result: dict[str, Any] = {
            "requested_full_name": name,
            "reference_time_utc": reference,
            "nonmerge_commits_90d": None,
            "observed_lower_bound": None,
            "coverage": "missing",
            "screen_status": "insufficient_evidence",
            "overlap_frozen_snapshot": True,
        }
        try:
            meta, record = client.get(API + "/repos/" + name, "metadata")
            canonical = meta["full_name"]
            branch = meta["default_branch"]
            head, _ = client.get(
                API + "/repos/" + canonical + "/commits/" + urllib.parse.quote(branch, safe=""), "branch_head"
            )
            result.update(
                repo_id=meta["id"],
                canonical_full_name=canonical,
                default_branch=branch,
                head_sha=head["sha"],
                created_at=meta["created_at"],
                pushed_at=meta["pushed_at"],
                archived=meta["archived"],
                fork=meta["fork"],
                age_days=(utc(reference) - utc(meta["created_at"])).total_seconds() / 86400,
                metadata_collected_at_utc=record["collected_at_utc"],
            )
            commits = []
            filtered_complete = False
            for page in range(1, args.max_pages + 1):
                params = urllib.parse.urlencode(
                    {"sha": head["sha"], "since": start.isoformat(), "until": reference, "per_page": 100, "page": page}
                )
                payload, response = client.get(
                    API + "/repos/" + canonical + "/commits?" + params, "window_page_" + str(page)
                )
                if not isinstance(payload, list):
                    raise ValueError("Expected commit array")
                commits.extend(payload)
                if 'rel="next"' not in (response["headers"].get("Link") or ""):
                    filtered_complete = True
                    break
            measured = count_cached_commits(commits, reference, False)
            result.update(measured)
            result["filtered_api_pages_complete"] = filtered_complete
            result["filtered_api_observed_count"] = measured["observed_lower_bound"]
            result["coverage"] = "filtered_api_complete" if filtered_complete else "partial_pages"
            result["screen_status"] = (
                "fails_low_activity_screen" if measured["observed_lower_bound"] > 5 else "needs_exhaustive_validation"
            )
            if measured["observed_lower_bound"] <= 5 and filtered_complete:
                full = []
                exhaustive = False
                for page in range(1, args.max_pages + 1):
                    params = urllib.parse.urlencode({"sha": head["sha"], "per_page": 100, "page": page})
                    payload, response = client.get(
                        API + "/repos/" + canonical + "/commits?" + params, "full_history_page_" + str(page)
                    )
                    full.extend(payload)
                    if 'rel="next"' not in (response["headers"].get("Link") or ""):
                        exhaustive = True
                        break
                validated = count_cached_commits(full, reference, exhaustive)
                result.update(validated)
                if exhaustive:
                    result["coverage"] = "complete_reachable_history"
                    result["filtered_vs_full_agree"] = (
                        validated["nonmerge_commits_90d"] == measured["observed_lower_bound"]
                    )
                    result["screen_status"] = (
                        "passes_activity_only"
                        if validated["nonmerge_commits_90d"] <= 5 and float(result["age_days"]) >= 1826.25
                        else "fails_screen"
                    )
                else:
                    result["coverage"] = "full_history_page_cap"
                    result["screen_status"] = (
                        "insufficient_evidence"
                        if validated["observed_lower_bound"] <= 5
                        else "fails_low_activity_screen"
                    )
            result["independent_adoption_review"] = "pending"
        except Exception as error:
            result["collection_error"] = str(error)
        results.append(result)
        (folder / "activity_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(name, result["screen_status"], result["coverage"], result["observed_lower_bound"], flush=True)
    print("Saved:", folder, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--queue", type=Path, default=Path(__file__).parents[0] / "run_20261014T020000Z/screening_queue.csv"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument("--resume", action="store_true")
    main(parser.parse_args())
