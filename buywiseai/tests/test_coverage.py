from types import SimpleNamespace as NS

from buywise.coverage import coverage_status, next_step, select_results


def mk(n, platforms):
    return [NS(source=platforms[i % len(platforms)], score=float(n - i)) for i in range(n)]


def test_cap_per_platform():
    pool = [NS(source="Daraz", score=10 - i) for i in range(5)] + [NS(source="PriceOye", score=1)]
    out = select_results(pool, target=10, cap=2)
    assert sum(1 for l in out if l.source == "Daraz") == 2
    assert len(out) == 3


def test_target_limit_and_order():
    out = select_results(mk(30, list("ABCDEFGH")), target=10, cap=2)
    assert len(out) == 10
    assert [l.score for l in out] == sorted([l.score for l in out], reverse=True)


def test_coverage_ok_and_not_ok():
    good = select_results(mk(30, list("ABCDEFGH")), 10, 2)
    assert coverage_status(good, 10, 6)["ok"]
    few_platforms = [NS(source="A", score=1), NS(source="A", score=2), NS(source="B", score=3)]
    st = coverage_status(few_platforms, 10, 6)
    assert not st["ok"] and st["platforms"] == 2 and st["count"] == 3


def test_next_step_loops_until_max_rounds():
    bad = {"ok": False, "count": 3, "platforms": 2}
    assert next_step(bad, 1, 3) == "search"
    assert next_step(bad, 2, 3) == "search"
    assert next_step(bad, 3, 3) == "recommend"
    assert next_step({"ok": True}, 1, 3) == "recommend"
