"""Collect metadata and commit objects only. Never check out or run project code."""

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import shutil
import subprocess
import urllib.parse

from collect_candidates import API, Client

DEFAULT_GIT = Path(shutil.which("git") or "git")
REPOS = ["openclaw/openclaw", "deepseek-ai/DeepSeek-R1", "morluto/rea"]


def main(args):
    folder = args.output
    if not args.resume:
        folder.mkdir(parents=True, exist_ok=False)
        (folder / "config.json").write_text(
            json.dumps(
                {
                    "reference_time_utc": datetime.now(UTC).isoformat(),
                    "method": "all commits reachable from frozen default-branch head; non-merges by UTC committer date; Sunday 00:00 UTC weeks",
                    "scope": "new historical recount; does not recreate original collection branch state",
                    "repositories": REPOS,
                },
                indent=2,
            )
        )
    results = []
    for repo in REPOS:
        client = Client(folder / repo.replace("/", "_"))
        row = {"requested_full_name": repo}
        try:
            meta, response = client.get(API + "/repos/" + repo, "metadata")
            row.update(
                repo_id=meta["id"],
                canonical_full_name=meta["full_name"],
                created_at=meta["created_at"],
                default_branch=meta["default_branch"],
                metadata_collected_at_utc=response["collected_at_utc"],
            )
            head, record = client.get(
                API + "/repos/" + meta["full_name"] + "/commits/" + urllib.parse.quote(meta["default_branch"], safe=""),
                "head",
            )
            row.update(head_sha=head["sha"], head_collected_at_utc=record["collected_at_utc"])
            bare = client.folder / "history.git"
            if not bare.exists():
                print("Collecting commit history:", repo, flush=True)
                subprocess.run(
                    [
                        str(args.git),
                        "clone",
                        "--bare",
                        "--filter=blob:none",
                        "--single-branch",
                        "--branch",
                        meta["default_branch"],
                        "--",
                        meta["clone_url"],
                        str(bare),
                    ],
                    check=True,
                    timeout=600,
                )
            shallow = subprocess.check_output(
                [str(args.git), "--git-dir=" + str(bare), "rev-parse", "--is-shallow-repository"], text=True
            ).strip()
            if shallow != "false":
                raise ValueError("Shallow history cannot establish full coverage")
            log = subprocess.check_output(
                [
                    str(args.git),
                    "--git-dir=" + str(bare),
                    "log",
                    "--no-show-signature",
                    head["sha"],
                    "--format=%H%x09%P%x09%aI%x09%cI",
                ],
                text=True,
            )
            (client.folder / "all_reachable_commits.tsv").write_text(log, encoding="utf-8")
            row.update(
                coverage="complete_reachable_history",
                reachable_commits=len(log.splitlines()),
                log_saved_at_utc=datetime.now(UTC).isoformat(),
            )
            print(repo, row["reachable_commits"], "commits; complete", flush=True)
        except Exception as error:
            row.update(coverage="missing_or_incomplete", error=str(error))
            print(repo, "collection failed:", str(error), flush=True)
        results.append(row)
        (folder / "history_manifest.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--git", type=Path, default=DEFAULT_GIT if DEFAULT_GIT.exists() else shutil.which("git"))
    args = p.parse_args()
    if args.git is None:
        p.error("Supply --git executable")
    main(args)
