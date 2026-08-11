"""bisect_regression.classify_search — a search that never saw a `bad` probe is inconclusive
and exits non-zero (the silent-echo-of-input-endpoint bug this replaces; see BISECTION_AUDIT.md)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from bisect_regression import classify_search  # noqa: E402


def test_converged_when_a_bad_probe_is_seen():
    assert classify_search(True, ["good", "bad", "good"]) == ("converged", 0)


def test_all_good_is_inconclusive_no_bad():
    # the #16215 case: 9 good probes, 0 bad -> must NOT echo the input --bad as the answer
    status, code = classify_search(False, ["good"] * 9)
    assert status == "inconclusive_no_bad"
    assert code != 0


def test_all_skip_is_inconclusive_all_skip():
    # the #14603 case: all six probes were build failures -> no information
    status, code = classify_search(False, ["skip"] * 6)
    assert status == "inconclusive_all_skip"
    assert code != 0


def test_mixed_good_and_skip_without_bad_is_inconclusive():
    status, code = classify_search(False, ["good", "skip", "good"])
    assert status == "inconclusive_no_bad"
    assert code != 0
