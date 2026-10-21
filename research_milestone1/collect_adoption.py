"""Preserve immutable downstream manifests and candidate context, read only."""

import argparse
import base64
import json
import urllib.parse

from collect_candidates import API, Client

SOURCES = [
    ("python-hyper/h11", "encode/httpcore", "pyproject.toml", "h11", "independent_runtime_dependency"),
    ("python-hyper/h11", "encode/uvicorn", "pyproject.toml", "h11", "independent_runtime_dependency"),
    ("Textualize/rich", "fastapi/typer", "pyproject.toml", "rich", "independent_runtime_dependency"),
    ("rust-lang/regex", "BurntSushi/ripgrep", "crates/regex/Cargo.toml", "regex", "independent_runtime_dependency"),
    ("BurntSushi/ripgrep", "microsoft/vscode", "package.json", "ripgrep", "independent_integration_via_wrapper"),
    ("pallets/flask", "apache/superset", "pyproject.toml", "flask", "independent_runtime_dependency"),
]


def main(folder):
    results = json.loads((folder / "activity_results.json").read_text())
    reference = results[0]["reference_time_utc"]
    evidence = []
    for candidate, repo, path, term, kind in SOURCES:
        client = Client(folder / "adoption" / repo.replace("/", "_"))
        row = {"candidate": candidate, "source_repository_requested": repo, "file_path": path, "evidence_kind": kind}
        try:
            query = urllib.parse.urlencode({"path": path, "until": reference, "per_page": 1})
            latest, _ = client.get(API + "/repos/" + repo + "/commits?" + query, "file_revision")
            if not latest:
                raise ValueError("No file history at reference")
            sha = latest[0]["sha"]
            payload, record = client.get(API + "/repos/" + repo + "/contents/" + path + "?ref=" + sha, "file_content")
            text = base64.b64decode(payload["content"]).decode("utf-8")
            (client.folder / "manifest.txt").write_text(text, encoding="utf-8")
            matches = [
                {"line": i, "text": line.strip()}
                for i, line in enumerate(text.splitlines(), 1)
                if term.lower() in line.lower()
            ]
            row.update(
                source_sha=sha,
                source_commit_date=latest[0]["commit"]["committer"]["date"],
                source_url=payload["html_url"],
                collected_at_utc=record["collected_at_utc"],
                matching_lines=matches,
                review_status="needs_manual_context_review",
                limitations="Declared dependency/integration only; not deployment volume, safety certification or ecosystem-wide prevalence.",
            )
        except Exception as error:
            row["error"] = str(error)
        evidence.append(row)
        print(candidate, repo, len(row.get("matching_lines", [])), row.get("error", ""), flush=True)
    for result in results:
        repo = result.get("canonical_full_name")
        if not repo:
            continue
        client = Client(folder / repo.replace("/", "_"))
        try:
            readme, _ = client.get(API + "/repos/" + repo + "/readme?ref=" + result["head_sha"], "readme_at_head")
            (client.folder / "README_at_head.txt").write_text(
                base64.b64decode(readme["content"]).decode("utf-8"), encoding="utf-8"
            )
        except Exception as error:
            print(repo, "readme:", error, flush=True)
    client = Client(folder / "python-hyper_h11")
    for path, name in [("CONTRIBUTING.md", "contributing"), ("docs/source/changes.rst", "changes")]:
        try:
            head = next(r["head_sha"] for r in results if r["requested_full_name"] == "python-hyper/h11")
            payload, _ = client.get(API + "/repos/python-hyper/h11/contents/" + path + "?ref=" + head, name)
            (client.folder / (name + ".txt")).write_text(
                base64.b64decode(payload["content"]).decode("utf-8"), encoding="utf-8"
            )
        except Exception as error:
            print(name, error, flush=True)
    try:
        client.get(API + "/repos/python-hyper/h11/security-advisories/GHSA-vqfr-h8mv-ghfj", "security_advisory")
    except Exception as error:
        print("advisory", error, flush=True)
    (folder / "adoption_evidence.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")


if __name__ == "__main__":
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--collection", type=Path, required=True)
    main(parser.parse_args().collection)
