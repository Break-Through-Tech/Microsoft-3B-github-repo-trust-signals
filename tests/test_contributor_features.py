"""Tests for contributor feature definitions."""

from gh_signals.contributor_features import (
    ContributorActivity,
    build_feature_row,
    contribution_hhi,
    human_contributors,
    is_bot,
    positive_rank_auc,
)


def _person(login: str, contributions: int) -> ContributorActivity:
    return ContributorActivity(login=login, contributions=contributions, user_type="User")


def test_bot_accounts_are_excluded_from_human_features() -> None:
    contributors = [
        _person("ada", 30),
        ContributorActivity("dependabot[bot]", 100, "Bot"),
        _person("grace", 10),
    ]

    assert is_bot("dependabot[bot]", "Bot")
    assert [contributor.login for contributor in human_contributors(contributors)] == ["ada", "grace"]

    row = build_feature_row(
        "example/project",
        "uncertain",
        contributors,
        good_human_logins_by_repo={},
        owners={"example/project": "example"},
        list_cap=100,
    )

    assert row["human_contributor_n"] == 2
    assert row["bot_contributor_n"] == 1
    assert row["substantive_contributor_n"] == 2
    assert row["top_human_share"] == 0.75
    assert row["max_human_contributions"] == 30


def test_hhi_is_one_for_a_single_author_and_half_for_an_even_split() -> None:
    assert contribution_hhi([5]) == 1
    assert contribution_hhi([5, 5]) == 0.5
    assert contribution_hhi([]) is None


def test_known_good_overlap_is_leave_one_out_and_owner_aware() -> None:
    good_logins = {
        "microsoft/vscode": {"sam", "ada"},
        "microsoft/typescript": {"sam"},
        "django/django": {"ada"},
    }
    owners = {
        "microsoft/vscode": "microsoft",
        "microsoft/typescript": "microsoft",
        "django/django": "django",
        "new/project": "new",
    }
    vscode = [
        _person("sam", 50),
        _person("ada", 20),
        _person("newcomer", 1),
    ]

    row = build_feature_row(
        "microsoft/vscode",
        "good",
        vscode,
        good_human_logins_by_repo=good_logins,
        owners=owners,
        list_cap=100,
    )

    assert row["human_contributors_on_other_good_n"] == 2
    assert row["share_human_contributors_on_other_good"] == 2 / 3
    assert row["human_contributors_on_other_good_n"] != 3
    assert row["share_human_contributors_on_other_good_different_owner"] == 1 / 3
    assert row["other_good_repos_touched_n"] == 2

    uncertain = build_feature_row(
        "new/project",
        "uncertain",
        [_person("ada", 4)],
        good_human_logins_by_repo=good_logins,
        owners=owners,
        list_cap=100,
    )
    assert uncertain["share_human_contributors_on_other_good"] == 1
    assert uncertain["substantive_contributor_n"] == 0
    assert uncertain["share_human_contributors_on_other_good"] is not None


def test_empty_human_history_does_not_become_a_zero_share() -> None:
    row = build_feature_row(
        "solo/empty",
        "uncertain",
        [ContributorActivity("renovate[bot]", 3, "Bot")],
        good_human_logins_by_repo={"django/django": {"ada"}},
        owners={"solo/empty": "solo", "django/django": "django"},
        list_cap=100,
    )

    assert row["human_contributor_n"] == 0
    assert row["share_human_contributors_on_other_good"] is None
    assert row["top_human_share"] is None
    assert row["limited_public_contributor_history"] == 1
    assert row["contributor_list_capped"] == 0


def test_rank_auc_handles_separation_and_ties() -> None:
    assert positive_rank_auc([1, 0], [2.0, 1.0]) == 1
    assert positive_rank_auc([1, 0], [1.0, 2.0]) == 0
    assert positive_rank_auc([1, 0], [1.0, 1.0]) == 0.5
    assert positive_rank_auc([1, 0], [None, 1.0]) is None
    assert positive_rank_auc([1, 1, 0], [float("nan"), 3.0, 1.0]) == 1


def test_automation_accounts_labeled_as_users_are_not_people() -> None:
    assert is_bot("k8s-ci-robot", "User")
    assert is_bot("bors", "User")
    assert not is_bot("bpasero", "User")
