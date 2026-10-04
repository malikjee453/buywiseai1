from buywise.utils.relevance import is_accessory, is_price_outlier_low, median_price


def test_accessory_detection():
    assert is_accessory("Silicone Back Cover for Samsung A55", "Samsung A55")
    assert is_accessory("Tempered Glass Screen Protector A55", "Samsung A55")
    assert not is_accessory("Samsung Galaxy A55 5G 8GB/256GB", "Samsung A55")
    assert not is_accessory("iPhone 15 Case Black", "iphone 15 case")      # user asked for a case
    assert not is_accessory("Showcase LED TV 43 inch", "led tv")           # 'case' inside a word


def test_price_outlier():
    prices = [90000, 92000, 95000, 88000, 20000]
    med = median_price(prices)
    assert med == 90000
    assert is_price_outlier_low(20000, med, len(prices))
    assert not is_price_outlier_low(88000, med, len(prices))
    assert not is_price_outlier_low(20000, med, 3)    # too few items to judge


def test_model_tokens():
    from buywise.utils.relevance import model_tokens
    assert model_tokens("Samsung Galaxy A55 128GB") == ["a55"]
    assert model_tokens("iPhone 15 128GB") == ["15"]
    assert model_tokens("Haier 1.5 ton inverter AC") == []
    assert model_tokens("Galaxy S24 Ultra") == ["s24"]


def test_wrong_models_rejected():
    from buywise.utils.relevance import title_matches_model as m
    q = "Samsung Galaxy A55 128GB"
    assert m("Samsung Galaxy A55 5G 8GB/256GB", "https://shophive.com/x", q)
    assert not m("Samsung Galaxy A57 5G Dual Sim", "https://telemart.pk/samsung-galaxy-a57", q)
    assert not m("Samsung Galaxy A54 Price in Pakistan", "https://shophive.com/a54", q)
    assert not m("Samsung Galaxy A35 8GB 256GB", "https://shophive.com/a35", q)
    assert not m("Samsung Galaxy Watch 8 Classic 46mm", "https://telemart.pk/watch-8", q)
    assert m("Buy Samsung Mobile", "https://shophive.com/samsung-galaxy-a55-8gb", q)   # model in URL
    assert m("Anything", "https://x.com/y", "wireless earbuds")                          # no model => no filter


def test_charger_is_accessory_but_with_charger_is_not():
    assert is_accessory("Acefast A55 Fast Charge Wall Charger PD30W", "Samsung Galaxy A55")
    assert not is_accessory("Samsung Galaxy A55 5G PTA Approved with Charger", "Samsung Galaxy A55")
    assert not is_accessory("Samsung 25W Charger", "samsung charger")


def test_gender_conflict():
    from buywise.utils.relevance import gender_conflict as g
    q = "shalwar kameez for girls"
    assert g("Men's Shalwar Kameez Online in Pakistan", "https://gulahmedshop.com/mens-shalwar-kameez", q)
    assert not g("Women's Shalwar Kameez", "https://gulahmedshop.com/womens", q)
    assert not g("Girls Embroidered Shalwar Kameez", "https://x.com/y", q)
    assert not g("Shalwar Kameez Unstitched", "https://x.com/y", q)           # neutral listing is fine
    assert not g("Men's Shalwar Kameez", "https://x.com/y", "shalwar kameez")  # no gender in query
    assert g("Girls Frock", "https://x.com/y", "boys kurta")


def test_lexical_match_rescues_south_asian_clothing_titles():
    from buywise.utils.relevance import lexical_match
    assert lexical_match("Kids Fitt Girls Black Hand Embroidered Khaddar 2 Piece Suit – Farshi Shalwar", "", "", "shalwar kameez")
    assert lexical_match("RTW - KAMEEZ & SHALWAR", "", "", "shalwar kameez")
    assert not lexical_match("Embellished Raglan Blouse", "https://x.pk/products/blouse", "", "shalwar kameez")
    assert not lexical_match("Toddler Girl Blue Trouser", "", "", "shalwar kameez")


def test_judge_query_restates_audience_instead_of_girls():
    from buywise.utils.relevance import judge_query
    q = judge_query("shalwar kameez for girls")
    assert q.startswith("shalwar kameez (audience: female, any age")
    assert judge_query("iphone 15 128gb") == "iphone 15 128gb"
    assert judge_query("kids shoes").endswith("(audience: children)")
