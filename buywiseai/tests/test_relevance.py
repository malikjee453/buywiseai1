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
