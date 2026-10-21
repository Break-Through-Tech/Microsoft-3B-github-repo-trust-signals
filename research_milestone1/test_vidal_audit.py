import unittest

from audit_vidal_handoff import duplicates, key, missing


class VidalAuditTests(unittest.TestCase):
    def test_name_normalization(self):
        assert key(" HTTPS://GITHUB.COM/Owner/Repo.git/ ") == "owner/repo"

    def test_duplicates_report_original_csv_lines(self):
        r = duplicates([{"full_name": "A/B"}, {"full_name": "c/d"}, {"full_name": " a/b "}])
        assert r == [{"canonical_name_key": "a/b", "csv_lines": [2, 4]}]

    def test_zero_and_false_are_not_missing(self):
        assert not missing(0)
        assert not missing(False)
        assert not missing("0")

    def test_missing_tokens(self):
        for value in [None, "", " NaN ", "null"]:
            assert missing(value)


if __name__ == "__main__":
    unittest.main()
