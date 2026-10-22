"""Regression tests built from a real 44-second search trace (Galaxy A06)."""
import time
from dataclasses import asdict
from types import SimpleNamespace as NS

from buywise import graph as g
from buywise.agents import judge as judge_mod
from buywise.agents.verify import verify_listings
from buywise.config import RunSettings, load_platforms
from buywise.coverage import select_results
from buywise.llm import LLMError
from buywise.schemas import Listing, QueryPlan
from buywise.utils.url_utils import is_product_url


def L(i, source="Alkaram Studio", domain="alkaramstudio.com", **kw):
    base = dict(title=f"Girls SK {i}", url=f"https://{domain}/products/g-{i}", domain=domain, source=source,
                price=5000, price_pkr=5000, relevance=1.0, score=1.0, snippet="")
    base.update(kw)
    return Listing(**base)


PLAN = QueryPlan(original="girls shalwar kameez", product="shalwar kameez")


# ---- per-platform caps (WhatMobile took 3 of 10 slots)
def test_platform_cap_only_lowers_the_default():
    pool = [NS(source="WhatMobile", score=10 - i) for i in range(3)] + [NS(source="Daraz", score=1 + i * 0.1) for i in range(3)]
    out = select_results(pool, target=10, cap=2, caps={"WhatMobile": 1})
    assert sum(1 for l in out if l.source == "WhatMobile") == 1
    assert sum(1 for l in out if l.source == "Daraz") == 2
    assert select_results(pool, 10, 3, caps={"Daraz": 9}).__len__() == 6      # a cap never raises the default


def test_whatmobile_limited_in_platforms_yaml():
    wm = [p for p in load_platforms() if p.name == "WhatMobile"][0]
    assert wm.max_results == 1
    assert g._caps().get("WhatMobile") == 1


# ---- article / picture / compare pages are not products (URLs from the trace)
def test_whatmobile_non_product_pages():
    for url in ("https://www.whatmobile.com.pk/samsung-galaxy-a06-design-remains-unchanged-leaked-images-confirm-news-5293",
                "https://www.whatmobile.com.pk/gateway.php?view=2&url=Samsung_Galaxy-A06-128GB_Pictures",
                "https://x.whatmobile.com.pk/Samsung_Galaxy-A06-128GB_Pictures",
                "https://www.whatmobile.com.pk/Samsung_Galaxy-A06-vs-"):
        assert not is_product_url(url), url
    assert is_product_url("https://www.whatmobile.com.pk/Samsung_Galaxy-A06")
    assert is_product_url("https://www.shophive.com/samsung-galaxy-a06-6gb-128gb/")
    assert is_product_url("https://www.daraz.pk/products/samsung-galaxy-a06-i1.html")


# ---- Google redirect links are not store URLs
def test_google_shopping_links_dropped_unless_allowed():
    l = L(1, domain="google.com", source="Daraz", url="https://www.google.com/search?ibp=oshop&q=Galaxy+A06",
          flags=["shopping_link"])
    valid, drops, _ = verify_listings([l], RunSettings(), PLAN)
    assert valid == [] and drops == {"google_link_not_store_url": 1}
    valid, _, _ = verify_listings([L(1, domain="google.com", source="Daraz", url="https://www.google.com/search?q=a",
                                     flags=["shopping_link"])], RunSettings(allow_shopping_links=True), PLAN)
    assert len(valid) == 1


# ---- judge explains its rejections
class FakeLLM:
    def available(self):
        return True

    def chat_json(self, *a, **k):
        assert k.get("timeout")                       # judge calls must be time-limited
        return {"items": [{"id": 0, "match": True}, {"id": 1, "match": False, "why": "screen panel, not a phone"}]}


def test_judge_reports_reason_for_rejection():
    ls = [L(0, title="Samsung Galaxy A06 6GB", source="Shophive"), L(1, title="Samsung Galaxy A06 Panel", source="Daraz")]
    ls[0].score, ls[1].score = 2.0, 1.0
    kept, dropped = judge_mod.judge_relevance(ls, "reason-test-query", FakeLLM())
    assert dropped == 1 and [l.title for l in kept] == ["Samsung Galaxy A06 6GB"]
    assert judge_mod.judge_relevance.last_dropped == ["Samsung Galaxy A06 Panel (Daraz): screen panel, not a phone"]


# ---- enrichment gives up on a site that never returns a price
def _state(pool, **extra):
    return {"plan": PLAN.model_dump(), "settings": asdict(RunSettings()), "pool": [l.model_dump() for l in pool], **extra}


def test_enrichment_stops_after_two_failures_on_one_site():
    calls = []

    def fake_page(url, image_only=False):
        calls.append(url)
        if "shophive" in url:
            return {"meta": (31999.0, "PKR"), "image": None, "reason": "ok"}
        return {"meta": None, "image": None, "reason": "no_price_in_page"}

    pool = [L(i, source="WhatMobile", domain="whatmobile.com.pk", price=None, price_pkr=None,
              url=f"https://www.whatmobile.com.pk/Samsung_Galaxy-A06-{i}") for i in range(5)]
    pool += [L(10, source="Shophive", domain="shophive.com", price=None, price_pkr=None, url="https://www.shophive.com/a06-4gb")]
    orig, g.fetch_product_page = g.fetch_product_page, fake_page
    try:
        out = g.n_enrich(_state(pool))
        assert sum("whatmobile" in u for u in calls) == 2 and sum("shophive" in u for u in calls) == 1
        assert out["lookup_stats"]["whatmobile.com.pk"] == {"ok": 0, "fail": 2}
        calls.clear()                                                    # next round: dead site is not retried at all
        g.n_enrich(_state(pool, lookup_stats=out["lookup_stats"]))
        assert not any("whatmobile" in u for u in calls)
    finally:
        g.fetch_product_page = orig


def test_site_that_sometimes_works_keeps_being_used():
    def fake_page(url, image_only=False):
        ok = url.endswith("-2")
        return {"meta": (1000.0, "PKR") if ok else None, "image": None, "reason": "ok" if ok else "no_price_in_page"}

    pool = [L(i, price=None, price_pkr=None, url=f"https://alkaramstudio.com/products/p-{i}") for i in range(4)]
    orig, g.fetch_product_page = g.fetch_product_page, fake_page
    try:
        out = g.n_enrich(_state(pool, lookup_stats={"alkaramstudio.com": {"ok": 1, "fail": 5}}))
        assert out["lookup_stats"]["alkaramstudio.com"]["ok"] >= 2          # had a success before: never declared dead
    finally:
        g.fetch_product_page = orig


# ---- time budget ends the search loop
def test_time_budget_stops_further_rounds_and_relaxes_cap():
    pool = [L(i, source="Alkaram Studio", domain="alkaramstudio.com", price=5000 + i * 100, price_pkr=5000 + i * 100)
            for i in range(3)]
    base = _state(pool, round=1, last_count=-1)
    r = g.n_verify({**base, "started": time.time() - 100})              # far past the 30 s budget
    assert r["stop_reason"] == "time budget"
    assert g.route({**base, **r}) == "recommend"
    assert len(r["selected"]) == 3                                      # cap relaxed 2 -> 3 so the target is approached
    r = g.n_verify({**base, "started": time.time()})
    assert r["stop_reason"] == "" and g.route({**base, **r}) == "search"


# ---- new platforms from the user's list
def test_new_platforms_are_whitelisted():
    from buywise.config import match_platform
    assert match_platform("markaz.app").name == "Markaz"
    assert match_platform("www.chasevalue.pk".replace("www.", "")).name == "Chase Value"
    assert match_platform("bagallery.com").category == "beauty"
    assert match_platform("amazon.com") is None


def test_beauty_queries_are_categorised_and_prioritised():
    from buywise.agents.query import _heuristic
    from buywise.agents.search import prioritised_domains
    plan = _heuristic("vitamin c serum for face")
    assert "beauty" in plan.categories
    ordered = [p.domain for p in prioritised_domains(plan, list(load_platforms()))]
    assert ordered.index("bagallery.com") < ordered.index("khaadi.com")      # beauty store before unrelated fashion


# ---- from the "panty" trace
def test_far_above_median_snippet_price_is_dropped():
    """AliExpress 'Rs 276,780' for a panty came from a $1000 read out of snippet text."""
    plan = QueryPlan(original="panty", product="panty")
    doms = ["shophive.com", "telemart.pk", "czone.com.pk", "priceoye.pk", "markaz.app", "chasevalue.pk"]
    ls = [L(i, price=800 + i * 50, price_pkr=800 + i * 50, price_origin="page-meta",
            source=f"Store{i}", domain=d, url=f"https://{d}/products/p-{i}") for i, d in enumerate(doms)]
    bad = L(9, title="Women panty set", price=1000.0, price_pkr=280000.0, currency="USD", price_origin="text",
            source="AliExpress", domain="aliexpress.com", url="https://www.aliexpress.com/item/1005007170363843.html")
    ok_expensive = L(8, title="Women panty luxury set", price=9000.0, price_pkr=9000.0, price_origin="page-meta",
                     source="Daraz", domain="daraz.pk", url="https://www.daraz.pk/products/lux-i1.html")
    for l in ls + [bad, ok_expensive]:
        l.relevance = 1.0
    valid, drops, _ = verify_listings(ls + [bad, ok_expensive], RunSettings(), plan)
    assert bad not in valid and ok_expensive in valid          # only the unconfirmed snippet price is removed
    assert drops.get("unverified_price_outlier") == 1
    # a page-confirmed expensive price is never dropped, even if far above the median
    bad.price_origin = "page-meta"
    valid, _, _ = verify_listings(ls + [bad], RunSettings(), plan)
    assert bad in valid


def test_budget_prediction_stops_before_a_round_that_would_overshoot():
    pool = [L(i, source=f"S{i}", domain=f"s{i}.pk", price=1000 + i, price_pkr=1000 + i,
              url=f"https://s{i}.pk/products/p-{i}") for i in range(3)]
    now = time.time()
    # 29 s elapsed and the first round itself took 28 s: another round would end near 57 s > 30 s * 1.25
    r = g.n_verify(_state(pool, round=1, last_count=-1, started=now - 29, round_started=now - 28))
    assert r["stop_reason"] == "time budget" and g.route(_state(pool, round=1, **r)) == "recommend"
    # a fast first round (7 s of 8 s elapsed) keeps searching
    r = g.n_verify(_state(pool, round=1, last_count=-1, started=now - 8, round_started=now - 7))
    assert r["stop_reason"] == ""


def test_search_round_does_not_wait_for_stragglers():
    """Real trace: 21 of 22 calls came back in ~2 s but the round still waited the full 15 s for one slow call."""
    import buywise.agents.search as sa
    from buywise.schemas import RawResult

    plats = list(load_platforms())[:10]
    slow_domain = plats[0].domain

    class OneSlowDomain:
        name, env_key, supports_shopping = "engine", None, False

        def search(self, q, d, n):
            if d == slow_domain:
                time.sleep(6)
            return [RawResult(title="t", url=f"https://{d}/products/a-i1.html")]

    t = time.time()
    orig, sa.GRACE_AFTER_80PCT_S = sa.GRACE_AFTER_80PCT_S, 0.5
    try:
        raws, trace = sa.run_search_round("q", plats, [OneSlowDomain()], RunSettings(providers_per_domain=1), deadline=20.0)
    finally:
        sa.GRACE_AFTER_80PCT_S = orig
    took = time.time() - t
    assert took < 3, took                                           # did not wait for the 6 s straggler
    assert len(raws) == 9                                           # kept everything that arrived
    assert any("1 slow call" in x and "engine" in x for x in trace), trace


# ---- from the "shalwar kameez for girls" trace
def test_fashion_query_searches_all_fashion_stores_in_round_one():
    """7 general stores used to crowd out 4 of the 7 fashion stores, and the time budget then skipped round 2."""
    from buywise.agents.search import pick_round_domains, prioritised_domains
    from buywise.agents.query import _heuristic
    plan = _heuristic("shalwar kameez for girls")
    assert "fashion" in plan.categories
    ordered = prioritised_domains(plan, list(load_platforms()))
    round1 = {p.domain for p in pick_round_domains(ordered, 1, 10)}
    fashion = {p.domain for p in load_platforms() if p.category == "fashion"}
    assert fashion <= round1, fashion - round1                      # every fashion store is searched in round 1
    assert {"daraz.pk", "aliexpress.com", "olx.com.pk"} <= round1   # anchors always included
    assert {"chasevalue.pk", "markaz.app"} <= round1                # general stores that sell clothes too
    assert len(round1) <= 13                                        # not a bigger (slower) round than before


def test_electronics_query_does_not_pull_in_fashion_stores():
    from buywise.agents.search import pick_round_domains, prioritised_domains
    from buywise.agents.query import _heuristic
    ordered = prioritised_domains(_heuristic("samsung galaxy a06"), list(load_platforms()))
    round1 = {p.domain for p in pick_round_domains(ordered, 1, 10)}
    assert {"priceoye.pk", "telemart.pk", "shophive.com", "czone.com.pk"} <= round1
    assert "khaadi.com" not in round1


def test_same_price_different_products_are_not_merged():
    """A store feed lists many different suits at the same price; only near-identical titles are one offer."""
    plan = QueryPlan(original="shalwar kameez for girls", product="shalwar kameez")
    titles = ["Girls Embroidered Lawn Suit Pink", "Kids Printed Cotton Kameez Blue", "Girls Chiffon Party Frock Maroon",
              "Girls Khaddar Winter Shalwar Kameez Grey"]
    ls = [L(i, title=t, price=1999.0, price_pkr=1999.0, url=f"https://chasevalue.pk/products/p-{i}",
            domain="chasevalue.pk", source="Chase Value") for i, t in enumerate(titles)]
    twin = L(9, title="Girls Embroidered Lawn Suit Pink", price=1999.0, price_pkr=1999.0,
             url="https://chasevalue.pk/products/p-9-copy", domain="chasevalue.pk", source="Chase Value")
    for l in ls + [twin]:
        l.relevance = 1.0
    valid, drops, _ = verify_listings(ls + [twin], RunSettings(), plan)
    assert len(valid) == 4 and drops.get("duplicate_offer") == 1     # the twin is merged, the 4 distinct products are kept


def test_enrichment_lookups_are_capped_per_site():
    calls = []

    def fake_page(url, image_only=False):
        calls.append(url)
        return {"meta": (1000.0, "PKR"), "image": None, "reason": "ok"}

    pool = [L(i, source="Markaz", domain="markaz.app", price=None, price_pkr=None,
              url=f"https://www.markaz.app/shop/product/girls-shalwar-kameez-{i}") for i in range(8)]
    pool += [L(20 + i, source="Chase Value", domain="chasevalue.pk", price=None, price_pkr=None,
               url=f"https://chasevalue.pk/products/girls-shalwar-kameez-{i}") for i in range(2)]
    orig, g.fetch_product_page = g.fetch_product_page, fake_page
    try:
        g.n_enrich(_state(pool))
        assert sum("markaz" in u for u in calls) == RunSettings().per_platform_cap + 2     # 4, not 8
        assert sum("chasevalue" in u for u in calls) == 2                                 # the other site still gets its turn
    finally:
        g.fetch_product_page = orig
