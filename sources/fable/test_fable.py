"""Run: python3 sources/fable/test_fable.py (a folder named code shadows the stdlib, so no pytest here)."""
import importlib.util, os, random, sys, tempfile, types
base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "code")
pkg = types.ModuleType("fable_code"); pkg.__path__ = [base]; sys.modules["fable_code"] = pkg
def load(n):
    s = importlib.util.spec_from_file_location(f"fable_code.{n}", f"{base}/{n}.py"); m = importlib.util.module_from_spec(s)
    sys.modules[s.name] = m; s.loader.exec_module(m); return m
engine, store = load("engine"), load("store")
rng = random.Random(1)
cat = engine.Catalog()
assert len(cat.chars) >= 2000 and all(cat.by_stars[s] for s in range(1, 6))
n = 20000; cnt = {s: 0 for s in range(1, 6)}
for _ in range(n): cnt[cat.roll_stars(rng)] += 1
for s, p in engine.ODDS.items(): assert abs(cnt[s] / n * 100 - p) < 1.5, (s, cnt[s] / n)
assert all(cat.roll_stars(rng, 4) >= 4 for _ in range(500))
assert cat.find("naruto uzumaki") and "naruto" in cat.find("naruto uzumaki")[0].name.lower()
assert engine.steal_chance(1, 0) == 50 and engine.steal_chance(5, 0) == 1 and engine.steal_chance(1, 8) == 75
assert engine.steal_chance(1, 40) == 90 and engine.steal_chance(3, 15) == 65
assert engine.window(100, 0)[0] and not engine.window(100, 50)[0] and engine.window(4000, 100)[0]
assert engine.wait(3700) == "1h 01m"
ones = cat.by_stars[1][:6]
g = engine.merge_group(ones, 2); assert g and len(g) == 5
assert engine.merge_group(ones[:4], 2) is None and engine.merge_group(ones[:5], 2, {ones[0].id}) is None
d = tempfile.mkdtemp(); s = store.Store(os.path.join(d, "f.db"))
a, b = ones[0].id, ones[1].id
assert s.claim("g", a, "u1") and not s.claim("g", a, "u2") and s.owner("g", a) == "u1" and s.owner("h", a) is None
s.transfer("g", a, "u2"); assert s.owned_by("g", "u2") == [a] and s.owned_by("g", "u1") == []
s.release("g", a); assert s.owner("g", a) is None
assert s.add_coins("g", "u1", 50) == 50 and s.add_coins("g", "u1", -20) == 30
s.update("g", "u1", rolls_used=3, name="Ann"); p = s.player("g", "u1"); assert p["rolls_used"] == 3 and p["name"] == "Ann"
s.wish("g", "u1", b, True); assert s.wishers("g", b) == ["u1"] and s.wishes("g", "u1") == [b]; s.wish("g", "u1", b, False); assert not s.wishes("g", "u1")
s.claim("g", b, "u1"); s.set_party("g", "u1", 2, b); assert s.party("g", "u1") == {2: b}; s.set_party("g", "u1", 2, None); assert s.party("g", "u1") == {}
s.add_roll("m1", "g", "c1", b, "u1"); assert s.roll("m1")["char_id"] == b and s.latest_roll("c1")["message_id"] == "m1"
assert s.mark_claimed("m1", "u2") and not s.mark_claimed("m1", "u3")
s.log("g", "u1", "claim", b); assert s.stats("g")["claims"] >= 0 and s.recent()
s.close(); print("fable tests ok")
