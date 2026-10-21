import unittest

from build_temporal_bundle import definition, guarded_join, unique
import pytest


class TemporalBundleTests(unittest.TestCase):
    def test_preserves_base_labels_order_and_zero(self):
        base = [
            {"full_name": "A/One", "label": "0", "dataset_source": "comparison"},
            {"full_name": "B/Two", "label": "1", "dataset_source": "good"},
        ]
        wide = [
            {"repo_id": "a/one", "temporal__nonmerge_commits_90d": 0},
            {"repo_id": "outside/three", "temporal__nonmerge_commits_90d": 99},
        ]
        result = guarded_join(base, wide)
        assert [r["repo_id"] for r in result] == ["a/one", "b/two"]
        assert result[0]["snapshot_label"] == "0"
        assert result[0]["temporal__nonmerge_commits_90d"] == 0
        assert "temporal__nonmerge_commits_90d" not in result[1]

    def test_duplicate_join_key_rejected(self):
        with pytest.raises(ValueError, match=r"(?i)duplicate"):
            unique([{"repo_id": "A/B"}, {"repo_id": " a/b "}], "repo_id")

    def test_label_overwrite_rejected(self):
        with pytest.raises(ValueError, match=r"(?i)label"):
            guarded_join(
                [{"full_name": "a/b", "label": "0", "dataset_source": "x"}], [{"repo_id": "a/b", "label": "1"}]
            )

    def test_definition_preserves_scope(self):
        assert "not merges" in definition("temporal__pr_opened_post_8w_count")
        assert "null" in definition("temporal__nonmerge_commits_90d")


if __name__ == "__main__":
    unittest.main()
