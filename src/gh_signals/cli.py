"""Terminal interface for the shared pipeline and assessment library."""

import argparse
import asyncio
import csv
import importlib
import json
from pathlib import Path
import sys
import time
from typing import cast

from gh_signals.assessment import Assessor, assess_repository, read_feature_row
from gh_signals.consolidation import canonical_repo, consolidate
from gh_signals.github_client import GitHubClient, GitHubError
from gh_signals.temporal import integrate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    consolidation = commands.add_parser("consolidate", help="Validate and merge supplied feature exports")
    consolidation.add_argument("--config", required=True, type=Path)
    consolidation.add_argument("--input-dir", required=True, type=Path)
    consolidation.add_argument("--output-dir", type=Path, default=Path("runs"))
    temporal = commands.add_parser("temporal", help="Validate and append Ethan's frozen temporal handoff")
    temporal.add_argument("--base", required=True, type=Path)
    temporal.add_argument("--handoff-dir", required=True, type=Path)
    temporal.add_argument("--output-dir", required=True, type=Path)
    temporal.add_argument("--key-column", default="repo_id")
    temporal.add_argument("--scope", default="selected_base")
    assessment = commands.add_parser("assess", help="Assess one repository with the selected model adapter")
    assessment.add_argument("repo", help="GitHub owner/name or repository URL")
    source = assessment.add_mutually_exclusive_group(required=True)
    source.add_argument("--features", type=Path, help="Existing repository-level CSV")
    source.add_argument("--live", action="store_true", help="Fetch only current star and fork counts")
    assessment.add_argument("--key-column", default="repo_id")
    assessment.add_argument("--assessor", help="Trusted installed module:object exposing contract and score")
    assessment.add_argument("--cache-dir", type=Path, default=Path(".cache/github"))
    assessment.add_argument("--output", type=Path, help="Write JSON; defaults to stdout only")
    return parser


def _load_assessor(reference: str | None) -> Assessor | None:
    if reference is None:
        return None
    module, separator, attribute = reference.partition(":")
    if not separator or not module or not attribute or ":" in attribute:
        raise ValueError("Use --assessor trusted_package.module:object")
    obj = getattr(importlib.import_module(module), attribute)
    if not hasattr(obj, "contract") or not callable(getattr(obj, "score", None)):
        raise ValueError("The adapter must be an object exposing contract and score(features)")
    return cast(Assessor, obj)


async def _live(repo: str, cache_dir: Path) -> tuple[dict[str, int], dict[str, int | float]]:
    async with GitHubClient(cache_dir=cache_dir) as client:
        metadata = await client.get_repo(repo)
        return {"github__stars": metadata.stargazers_count, "github__forks": metadata.forks_count}, client.usage()


def main(argv: list[str] | None = None) -> int:
    """Return 0 on success, 1 on validation failure, 2 on usage errors, 3 when unscored."""
    parser = _parser()
    args = parser.parse_args(argv)
    start = time.perf_counter()
    try:
        if args.command == "consolidate":
            config = json.loads(args.config.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError("Consolidation config must be a JSON object")
            consolidation_result = consolidate(config, args.input_dir, args.output_dir)
            payload = {
                "run_dir": consolidation_result["run_dir"],
                "archive": consolidation_result["archive"],
                **consolidation_result["summary"],
            }
            code = 1 if consolidation_result["summary"]["status"] == "FAILED" else 0
        elif args.command == "temporal":
            payload = integrate(args.base, args.handoff_dir, args.output_dir, args.key_column, args.scope)
            code = 0
        else:
            key = canonical_repo(args.repo)
            usage: dict[str, int | float] = {"requests": 0, "cache_hits": 0, "wait_seconds": 0.0}
            if args.live:
                features, usage = asyncio.run(_live(key, args.cache_dir))
            else:
                features = read_feature_row(args.features, key, args.key_column)
            assessment_result = assess_repository(key, features, _load_assessor(args.assessor))
            payload = assessment_result.model_dump(mode="json")
            payload["api_usage"] = usage
            code = 0 if assessment_result.status == "scored" else 3
        payload["runtime_seconds"] = round(time.perf_counter() - start, 6)
        if args.command != "assess":
            payload["api_usage"] = {"requests": 0, "cache_hits": 0, "wait_seconds": 0.0}
        text = json.dumps(payload, indent=2, allow_nan=False) + "\n"
        if args.command == "assess" and args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        print(text, end="")
        return code
    except (ValueError, OSError, KeyError, ImportError, AttributeError, csv.Error, GitHubError, TimeoutError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
