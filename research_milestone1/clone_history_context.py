"""Pin early README context without inferring publication from commit time."""

import argparse
import base64
import json
from pathlib import Path
import urllib.parse

from collect_candidates import API, Client


def main(folder):
    sources = []
    for repo, before in [("HKUDS/nanobot", "2026-02-04T00:00:00Z"), ("zeroclaw-labs/zeroclaw", "2026-02-16T00:00:00Z")]:
        client = Client(folder / repo.replace("/", "_") / "early_context")
        row = {"requested_repo": repo, "commit_date_cutoff": before}
        try:
            query = urllib.parse.urlencode({"path": "README.md", "until": before, "per_page": 1})
            commits, _ = client.get(API + "/repos/" + repo + "/commits?" + query, "revision")
            if not commits:
                raise ValueError("No README commit found before cutoff")
            sha = commits[0]["sha"]
            content, record = client.get(API + "/repos/" + repo + "/contents/README.md?ref=" + sha, "content")
            text = base64.b64decode(content["content"]).decode("utf-8", errors="replace")
            (client.folder / "README.md").write_text(text, encoding="utf-8")
            row.update(
                sha=sha,
                source_url=content["html_url"],
                collected_at_utc=record["collected_at_utc"],
                relationship_passages=[
                    {"line": i, "text": line.strip()[:700]}
                    for i, line in enumerate(text.splitlines(), 1)
                    if "openclaw" in line.lower() or "inspired" in line.lower()
                ],
                limitation="Commit date does not prove the README was publicly visible at that time.",
            )
        except Exception as error:
            row["error"] = str(error)
        sources.append(row)
    (folder / "early_context.json").write_text(json.dumps(sources, indent=2), encoding="utf-8")
    print(json.dumps(sources, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", type=Path, required=True)
    main(parser.parse_args().collection)
