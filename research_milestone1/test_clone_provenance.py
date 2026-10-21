import unittest

from build_clone_findings import provenance_kind
from collect_clone_candidates import last_page


class ProvenanceTests(unittest.TestCase):
    def test_last_pagination_page(self):
        assert (
            last_page(
                '<https://api.github.com/x?page=2>; rel="next", <https://api.github.com/x?per_page=1&page=45>; rel="last"'
            )
            == 45
        )

    def test_missing_parent_remains_unresolved(self):
        assert provenance_kind(True, None, True) == "fork_parent_unresolved"

    def test_nonfork_does_not_mean_independent_implementation(self):
        assert provenance_kind(False, None, True) == "documented_alternative_not_github_fork"
        assert provenance_kind(False, None, False) == "relationship_unresolved"

    def test_recorded_parent(self):
        assert provenance_kind(True, "HKUDS/nanobot", False) == "github_recorded_fork"


if __name__ == "__main__":
    unittest.main()
