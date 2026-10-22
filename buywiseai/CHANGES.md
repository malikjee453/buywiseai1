# Changes in this update (from a real 44-second Galaxy A06 trace)

Speed
- graph.py: `time_budget_s` (default 30 s, sidebar slider): no new search round starts after it; the per-platform cap is
  relaxed on that last pass so the result target is still approached.
- graph.py `n_enrich`: circuit breaker. A site whose first 2 page lookups fail with no success is not looked up again
  (state key `lookup_stats`). Sites that work at least once are never switched off.
- llm.py / extract.py / judge.py: optional per-call `timeout` (extraction 12 s, judge 25 s, no retries) so one slow
  Groq call can't add ~10 s to a round.

Quality
- config/platforms.yaml + config.py + coverage.py: per-platform `max_results` (WhatMobile = 1; it is a spec site).
- config/settings.yaml + url_utils.py: `non_product_url_patterns` reject news articles, picture galleries, `-vs-`
  comparisons and `gateway.php` redirects as product pages.
- verify.py / graph.py: Google Shopping redirect links (google.com/search?ibp=oshop...) are dropped unless
  "Allow Google Shopping links" is on (default off). They are not store URLs.
- judge.py: the judge now returns a short reason for each rejection; it shows in the trace
  (`e.g. llm_wrong_product_type: <title> (<store>): <reason>`).
- providers/ddg.py removed (unused).

New settings: RunSettings.time_budget_s, RunSettings.allow_shopping_links, Platform.max_results.
Tests: tests/test_speed_and_quality.py (8 new tests).

# Added platforms (from the user's list)
- Markaz (markaz.app) and Chase Value (chasevalue.pk): category `general`, trust 3. Searched every round, so each adds a few API calls.
- Bagallery (bagallery.com): new category `beauty` (CATEGORIES, query-agent keywords), trust 4.
- Not added: GrocerApp and Krave Mart (delivery apps; domains not verified), Telemart's telex.pk link (telemart.pk is already listed).
- trust_score values are editorial guesses: edit config/platforms.yaml.

# Fixes from the "panty" trace
- search.py: a round no longer waits out the full 15 s deadline for a few slow calls. Once 80% of calls are back and
  4 s have passed it stops waiting (GRACE_AFTER_80PCT_S); the trace now names the slow engines.
  (Both rounds hit 15.0 s in the trace: that was most of the ~58 s total.)
- graph.py: a new search round is not started if one more round of the same length would overshoot the time
  budget by more than 25% (`round_started` in state). Previously a round could start at 28 s of a 30 s budget.
- verify.py / relevance.py: a snippet- or LLM-derived price more than 8x the median is dropped
  (`unverified_price_outlier`). Fixes "AliExpress Rs 276,780 for a panty" (a '$1000' read from text).
  Prices confirmed on the product page or via API are never dropped by this rule.
- Tests: 3 new regression tests in tests/test_speed_and_quality.py.

# Fixes from the "shalwar kameez for girls" trace
- search.py + platforms.yaml + config.py: store ordering. Round 1 searched all 7 general stores but only 3 of the 7
  fashion stores (adding Markaz/Chase Value made it worse), and the time budget then skipped round 2.
  Now: anchors (Daraz, AliExpress, OLX: `anchor: true`) are searched every round, and stores relevant to the query's
  category come first (`category` or the new `also:` list, e.g. Markaz/Chase Value also count for fashion/beauty/home).
  Round 1 = 3 anchors + the best 9 others (12 stores).
- verify.py: `duplicate_offer` no longer merges every product that shares a store and a price (92 were merged
  in one run). Only near-identical titles (word overlap >= 60%) count as one offer.
- graph.py `n_enrich`: at most `per_platform_cap + 2` page lookups per store per round (Markaz took 6 of 13 lookups
  and most of the 19.3 s), since results are capped per store anyway.
- Tests: 4 new regression tests (tests/test_speed_and_quality.py).
