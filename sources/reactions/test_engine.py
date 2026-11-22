"""python3 sources/reactions/test_engine.py  (not via pytest: the code/ folder would shadow the standard library)"""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "code"))
import engine as e  # noqa: E402


def m(rules="", **kw):
    kw.setdefault("rng", random.Random(1))
    return e.Matcher(rules, **kw)


def test_words_whole_word_and_phrase():
    x = m("happy: yay, good news", mode="words", chance=100)
    assert x.pick("Yay!").category == "happy"
    assert x.pick("that's GOOD   news").why == "good news"
    assert x.pick("yayyy") is None
    assert m("happy: yay", mode="words", chance=100, whole_words=False).pick("yayyy")


def test_per_line_chance_and_any():
    x = m("sad@0: rip\nany@100: lol", mode="words", chance=100)
    assert x.pick("rip") is None
    assert x.pick("lol").category in e.CATEGORIES


def test_category_mode_and_allowed():
    x = m("", mode="category", category_chance=100)
    assert x.pick("I am so sad today").category == "sad"
    assert x.pick("hmm let me think").category == "thinking"
    assert m("", mode="category", category_chance=100, categories=["happy"]).pick("so sad") is None
    assert m("happy: zorp", mode="category", category_chance=100).pick("zorp") is None   # words are off


def test_both_prefers_words():
    x = m("smug: sad", mode="both", chance=100, category_chance=100)
    assert x.pick("sad").category == "smug"


def test_probability_is_respected():
    x = m("happy: yay", mode="words", chance=30, rng=random.Random(7))
    hits = sum(bool(x.pick("yay")) for _ in range(2000))
    assert 450 < hits < 750


def test_problems_and_edit_helpers():
    rules, problems = e.parse_rules("nope: x\nhappy yay\n# sad: off\nhappy@50: a, b")
    assert len(problems) == 2 and len(rules) == 1 and rules[0].chance == 50
    t = e.add_phrase("happy: yay", "happy", "hooray")
    assert t == "happy: yay, hooray"
    assert e.add_phrase(t, "sad", "rip").splitlines()[-1] == "sad: rip"
    t2, ok = e.remove_phrase(t, "happy", "yay")
    assert ok and t2 == "happy: hooray"
    assert e.remove_phrase(t2, "happy", "hooray") == ("", True)
    assert e.resolve_category("emb") == "embarrassed-nervous" and e.resolve_category("calm down") == "calm-down"


def test_choose_file_avoids_recent():
    names = ["a", "b", "c"]
    assert e.choose_file("x", ["a", "b"], names=names) == "c"
    assert e.choose_file("x", ["a", "b", "c"], names=names) in names


if __name__ == "__main__":
    for k, v in list(globals().items()):
        if k.startswith("test_"):
            v()
    print("ok")
