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
