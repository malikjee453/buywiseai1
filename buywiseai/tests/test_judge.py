from types import SimpleNamespace as NS

from buywise.agents.judge import judge_relevance
from buywise.llm import LLMError


class FakeLLM:
    def __init__(self, reply=None, fail=False, avail=True):
        self.reply, self.fail, self.avail = reply, fail, avail

    def available(self):
        return self.avail

    def chat_json(self, *a, **k):
        if self.fail:
            raise LLMError("boom")
        return self.reply


def L(title, score, url="https://x.pk/products/a"):
    return NS(title=title, source="S", url=url, score=score)


ITEMS = lambda: [L("Girls Lawn Suit", 3), L("Sun Kundan Jhumka", 2), L("Embroidered 2pc", 1)]


def test_drops_wrong_product_type():
    llm = FakeLLM({"items": [{"id": 0, "match": True}, {"id": 1, "match": False}, {"id": 2, "match": "true"}]})
    kept, dropped = judge_relevance(ITEMS(), "shalwar kameez for girls", llm)
    assert [l.title for l in kept] == ["Girls Lawn Suit", "Embroidered 2pc"] and dropped == 1


def test_missing_ids_are_kept():
    kept, dropped = judge_relevance(ITEMS(), "q", FakeLLM({"items": [{"id": 1, "match": False}]}))
    assert len(kept) == 2 and dropped == 1


def test_fails_open():
    assert judge_relevance(ITEMS(), "q", FakeLLM(fail=True))[1] == 0
    assert judge_relevance(ITEMS(), "q", FakeLLM(avail=False))[1] == 0
    assert judge_relevance(ITEMS(), "q", FakeLLM({"garbage": 1}))[1] == 0
    assert len(judge_relevance(ITEMS(), "q", FakeLLM({"items": [{"id": "x"}]}))[0]) == 3
