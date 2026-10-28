"""Repository-level features derived from contributor activity.

The functions in this module do not call the GitHub API. They turn contributor
lists, and optional primary-contributor dates, into columns that can be joined
onto a repository table for modeling.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import TypedDict

SUBSTANTIVE_COMMIT_MIN = 10
LIMITED_HISTORY_MAX_HUMANS = 2
LIMITED_HISTORY_MAX_TENURE_DAYS = 180


class RepoContributorFeatures(TypedDict):
    """One repository row of contributor features.

    ``label`` and ``y_good`` identify the study class. They are not model inputs.
    Share and tenure fields are ``None`` when the repository has no human
    contributors, or when the date lookup did not return a commit.
    """

    repo: str
    label: str
    y_good: int
    human_contributor_n: int
    contributor_list_capped: int
    substantive_contributor_n: int
    has_multiple_substantive_contributors: int
    top_human_share: float | None
    human_contribution_hhi: float | None
    human_contributor_effective_n: float | None
    median_human_contributions: float | None
    max_human_contributions: int | None
    bot_contributor_n: int
    share_human_contributors_on_other_good: float | None
    human_contributors_on_other_good_n: int | None
    other_good_repos_touched_n: int | None
    share_human_contributors_on_other_good_different_owner: float | None
    primary_human_login: str | None
    primary_human_contributions: int | None
    primary_human_tenure_days: float | None
    primary_human_days_since_last_commit: float | None
    limited_public_contributor_history: int


@dataclass(frozen=True)
class ContributorActivity:
    """Commit counts for one identifiable contributor."""

    login: str
    contributions: int
    user_type: str


def is_bot(login: str, user_type: str) -> bool:
    """Returns whether this account is automation rather than a person.

    GitHub labels some automation as ``User``. Logins ending in ``-ci-robot``
    and the Rust merge account ``bors`` are treated as automation for that reason.
    """
    lowered = login.lower()
    return user_type == "Bot" or lowered.endswith(("[bot]", "-ci-robot")) or lowered == "bors"


def human_contributors(contributors: Sequence[ContributorActivity]) -> list[ContributorActivity]:
    """Returns person accounts, ordered by commit count and then login."""
    people = [contributor for contributor in contributors if not is_bot(contributor.login, contributor.user_type)]
    return sorted(people, key=lambda contributor: (-contributor.contributions, contributor.login.lower()))


def contribution_hhi(counts: Sequence[int]) -> float | None:
    """Returns the Herfindahl index of commit shares.

    The index is 1 when one person authored every commit and approaches 0 as
    commits are split across more people. Returns ``None`` when there are no commits.
    """
    total = sum(counts)
    if total <= 0:
        return None
    return sum((count / total) ** 2 for count in counts)


def positive_rank_auc(labels: Sequence[int], scores: Sequence[float | None]) -> float | None:
    """Returns the probability that a good repository scores above an uncertain one.

    Ties count as one half. Rows with a missing score are omitted. This is a
    separation diagnostic for one column. It does not fit a model.
    """
    paired = [
        (label, score)
        for label, score in zip(labels, scores, strict=True)
        if score is not None and not (isinstance(score, float) and math.isnan(score))
    ]
    positives = [score for label, score in paired if label == 1]
    negatives = [score for label, score in paired if label == 0]
    if not positives or not negatives:
        return None
    correct = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                correct += 1
            elif positive == negative:
                correct += 0.5
    return correct / (len(positives) * len(negatives))


def _median(values: Sequence[int]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return float(ordered[midpoint])
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def _other_good_logins(
    repo: str,
    good_human_logins_by_repo: Mapping[str, set[str]],
    owners: Mapping[str, str],
    *,
    different_owner: bool,
) -> set[str]:
    repo_owner = owners.get(repo, "").lower()
    logins: set[str] = set()
    for other_repo, people in good_human_logins_by_repo.items():
        if other_repo == repo:
            continue
        if different_owner and owners.get(other_repo, "").lower() == repo_owner:
            continue
        logins.update(people)
    return logins


def _touched_good_repos(
    repo: str,
    human_logins: set[str],
    good_human_logins_by_repo: Mapping[str, set[str]],
) -> int:
    return sum(
        1 for other_repo, people in good_human_logins_by_repo.items() if other_repo != repo and human_logins & people
    )


def build_feature_row(
    repo: str,
    label: str,
    contributors: Sequence[ContributorActivity],
    *,
    good_human_logins_by_repo: Mapping[str, set[str]],
    owners: Mapping[str, str],
    list_cap: int,
    primary_human_tenure_days: float | None = None,
    primary_human_days_since_last_commit: float | None = None,
) -> RepoContributorFeatures:
    """Builds one repository-level feature row.

    Overlap with known-good repositories is leave-one-out: a good repository
    does not receive credit for its own contributors. The different-owner share
    also ignores other repositories with the same owner, so a company working
    across its own repositories is not counted as outside credibility.

    Args:
        repo: Repository in ``owner/name`` form.
        label: Study label, ``good`` or ``uncertain``.
        contributors: Contributors returned for this repository, including bots.
        good_human_logins_by_repo: Human logins observed on each known-good repository.
        owners: Repository name to owner login.
        list_cap: Page size requested from the contributors endpoint.
        primary_human_tenure_days: Days from the primary human's earliest indexed
            commit on this repository to their latest. ``None`` if the lookup was not run.
        primary_human_days_since_last_commit: Days from that latest commit to the
            study date. ``None`` if the lookup was not run.
    """
    humans = human_contributors(contributors)
    counts = [contributor.contributions for contributor in humans]
    human_logins = {contributor.login.lower() for contributor in humans}
    other_good = _other_good_logins(repo, good_human_logins_by_repo, owners, different_owner=False)
    other_good_different_owner = _other_good_logins(repo, good_human_logins_by_repo, owners, different_owner=True)
    on_other_good = human_logins & other_good
    on_other_good_different_owner = human_logins & other_good_different_owner
    hhi = contribution_hhi(counts)
    total_commits = sum(counts)
    primary = humans[0] if humans else None
    human_n = len(humans)
    substantive_n = sum(1 for count in counts if count >= SUBSTANTIVE_COMMIT_MIN)

    share_other_good = (len(on_other_good) / human_n) if human_n else None
    share_different_owner = (len(on_other_good_different_owner) / human_n) if human_n else None
    tenure = primary_human_tenure_days
    limited = int(
        human_n <= LIMITED_HISTORY_MAX_HUMANS
        and (tenure is None or tenure < LIMITED_HISTORY_MAX_TENURE_DAYS)
        and (share_other_good is None or share_other_good == 0)
    )

    return RepoContributorFeatures(
        repo=repo,
        label=label,
        y_good=int(label == "good"),
        human_contributor_n=human_n,
        contributor_list_capped=int(len(contributors) >= list_cap),
        substantive_contributor_n=substantive_n,
        has_multiple_substantive_contributors=int(substantive_n >= 2),
        top_human_share=(max(counts) / total_commits) if total_commits else None,
        human_contribution_hhi=hhi,
        human_contributor_effective_n=(1 / hhi) if hhi else None,
        median_human_contributions=_median(counts),
        max_human_contributions=max(counts) if counts else None,
        bot_contributor_n=sum(1 for contributor in contributors if is_bot(contributor.login, contributor.user_type)),
        share_human_contributors_on_other_good=share_other_good,
        human_contributors_on_other_good_n=len(on_other_good) if human_n else None,
        other_good_repos_touched_n=_touched_good_repos(repo, human_logins, good_human_logins_by_repo)
        if human_n
        else None,
        share_human_contributors_on_other_good_different_owner=share_different_owner,
        primary_human_login=primary.login if primary is not None else None,
        primary_human_contributions=primary.contributions if primary is not None else None,
        primary_human_tenure_days=tenure,
        primary_human_days_since_last_commit=primary_human_days_since_last_commit,
        limited_public_contributor_history=limited,
    )
