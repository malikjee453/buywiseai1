import pytest

from buywise.utils.price_parser import find_price, parse_price

CASES = [
    ("Rs. 1,29,999", 129999, "PKR"),
    ("PKR 45999", 45999, "PKR"),
    ("Rs 45,999/-", 45999, "PKR"),
    ("₨45,999", 45999, "PKR"),
    ("Price: Rs.999", 999, "PKR"),
    ("Rs. 1,299.50", 1299.5, "PKR"),
    ("45,999 PKR", 45999, "PKR"),
    ("Rs. 45,999 - Rs. 52,000", 45999, "PKR"),
    ("US $129.99", 129.99, "USD"),
    ("$12.50", 12.5, "USD"),
    ("USD 12.5", 12.5, "USD"),
    ("Samsung A55 Rs 89,999 (US $320)", 89999, "PKR"),
    ("US $320 | Rs 89,999", 320, "USD"),
]


@pytest.mark.parametrize("text,amount,cur", CASES)
def test_parse(text, amount, cur):
    p = parse_price(text)
    assert p is not None
    assert p.amount == pytest.approx(amount)
    assert p.currency == cur


@pytest.mark.parametrize("text", ["Samsung A55 8GB 256GB", "1.5 Ton AC inverter", "", None, "Rs", "free shipping"])
def test_no_price(text):
    assert parse_price(text) is None


def test_bare_number_with_default_currency():
    p = parse_price("45999", default_currency="PKR")
    assert p and p.amount == 45999 and p.currency == "PKR"


def test_find_price_falls_through_texts():
    p = find_price(None, "no price", "now Rs 1,000")
    assert p and p.amount == 1000


def test_model_number_not_mistaken_for_price():
    assert parse_price("Galaxy A55 PKR") is None
    p = parse_price("Galaxy A55 PKR 89,999")
    assert p and p.amount == 89999


def test_range_bounds_are_not_prices():
    # Real Mega.pk snippet that produced a fake "Rs 100,000" listing
    assert parse_price("Mobile Prices above 100,000 PKR") is None
    assert parse_price("Phones under Rs. 50,000") is None
    p = parse_price("Prices above 100,000 PKR. Galaxy A55 Rs. 109,999")
    assert p and p.amount == 109999


def test_count_prices_detects_list_pages():
    from buywise.utils.price_parser import count_prices
    assert count_prices("A55 Rs 109,999") == 1
    assert count_prices("A55 Rs 109,999 | A35 Rs 85,499 | A15 Rs 52,999") == 3
    assert count_prices("Rs. 45,999/-") == 1          # two patterns match one number
