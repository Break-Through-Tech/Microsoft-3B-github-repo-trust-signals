"""Bounded, read-only provenance pilot. Does not execute downloaded code."""

import argparse
import base64
import csv
from datetime import UTC, datetime
import json
from pathlib import Path
import re
import urllib.parse

from collect_candidates import API, Client
from screening import utc

REPOSITORIES = [
    "openclaw/openclaw",
    "HKUDS/nanobot",
    "qwibitai/nanoclaw",
    "zeroclaw-labs/zeroclaw",
    "Maxmount/hkuds-nanobot",
]


def last_page(link):
    for part in (link or "").split(","):
        if 'rel="last"' in part:
            match = re.search(r"<([^>]+)>", part)
            if match is None:
                raise ValueError("Malformed pagination link")
            url = match.group(1)
            return int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["page"][0])
    return 1


def main(output, resume):
    if not resume:
        output.mkdir(parents=True, exist_ok=False)
        config = {
            "reference_time_utc": datetime.now(UTC).isoformat(),
            "selection": "OpenClaw reference, three named alternatives discovered through search, one apparent fork control",
            "repositories_requested": REPOSITORIES,
            "anchor_peak_week_utc": "2026-01-25T00:00:00+00:00",
            "anchor_basis": "Preserved OpenClaw pilot peak, not first public release or onset of virality",
        }
        (output / "config.json").write_text(json.dumps(config, indent=2))
    config = json.loads((output / "config.json").read_text())
    snapshot = next(Path.cwd().glob("local_evidence_*/snapshots-*/snapshots/*/repositories.csv"))
    with snapshot.open(encoding="utf-8-sig") as f:
        names = {r["full_name"].strip().lower() for r in csv.DictReader(f)}
    results = []
    for requested in REPOSITORIES:
        client = Client(output / requested.replace("/", "_"))
        row = {
            "requested_full_name": requested,
            "reference_time_utc": config["reference_time_utc"],
            "candidate_label": "not_assigned",
            "review_status": "pending_manual_provenance_review",
        }
        try:
            meta, response = client.get(API + "/repos/" + requested, "metadata")
            canonical = meta["full_name"]
            row.update(
                canonical_full_name=canonical,
                repo_id=meta["id"],
                created_at=meta["created_at"],
                fork=meta["fork"],
                parent=(meta.get("parent") or {}).get("full_name"),
                source=(meta.get("source") or {}).get("full_name"),
                parent_id=(meta.get("parent") or {}).get("id"),
                source_id=(meta.get("source") or {}).get("id"),
                default_branch=meta["default_branch"],
                archived=meta["archived"],
                metadata_collected_at_utc=response["collected_at_utc"],
                returned_api_url=response["returned_url"],
                name_changed_or_redirected=requested.lower() != canonical.lower(),
                overlap_frozen_snapshot=canonical.lower() in names,
                days_created_after_openclaw_peak=(
                    utc(meta["created_at"]) - utc(config["anchor_peak_week_utc"])
                ).total_seconds()
                / 86400,
            )
            head, _ = client.get(
                API + "/repos/" + canonical + "/commits/" + urllib.parse.quote(meta["default_branch"], safe=""), "head"
            )
            row["head_sha"] = head["sha"]
            readme, record = client.get(API + "/repos/" + canonical + "/readme?ref=" + head["sha"], "readme")
            text = base64.b64decode(readme["content"]).decode("utf-8", errors="replace")
            (client.folder / "README_at_head.md").write_text(text, encoding="utf-8")
            row["readme_url"] = readme["html_url"]
            row["readme_collected_at_utc"] = record["collected_at_utc"]
            row["relationship_passages"] = [
                {"line": i, "text": line.strip()[:650]}
                for i, line in enumerate(text.splitlines(), 1)
                if re.search(r"openclaw|inspir|fork|reimplement|clone|original|official", line, re.I)
            ][:30]
            row["security_claims_unverified"] = [
                {"line": i, "text": line.strip()[:400]}
                for i, line in enumerate(text.splitlines(), 1)
                if re.search(r"secur|safe|isola", line, re.I)
            ][:8]
        except Exception as error:
            row["collection_error"] = str(error)
        results.append(row)
        (output / "provenance_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(
            requested,
            row.get("canonical_full_name"),
            "fork=",
            row.get("fork"),
            row.get("collection_error", ""),
            flush=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    main(args.output, args.resume)
