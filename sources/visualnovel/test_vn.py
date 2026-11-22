"""Run: python3 sources/visualnovel/test_vn.py (a folder named code shadows the stdlib, so no pytest here)."""
import importlib, io, os, sys, tempfile, types
base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "code")
pkg = types.ModuleType("vn_code"); pkg.__path__ = [base]; sys.modules["vn_code"] = pkg
scene, story, store = (importlib.import_module(f"vn_code.{n}") for n in ("scene", "story", "store"))
assert story.split_mood("[laugh] Haha, Senpai!") == ("laugh", "Haha, Senpai!")
assert story.split_mood("[nope] I'm so sorry...")[0] == "sad"          # unknown tag falls back to keywords
assert story.split_mood("Ugh, seriously?")[0] == "annoyed"
assert story.place_from("3") == "grove" and story.place_from("the greenhouse please") == "greenhouse"
assert story.place_from("moon") is None and story.place_from("9") is None
assert "grove" in story.system_prompt("Gwen", "x", "grove", "Ann") and "[smile]" in story.system_prompt("G", "x", "bridge", "A")
assert scene.clean("**hi** _there_") == "hi there"
art_root = os.path.join(os.path.dirname(base), "..", "..", "modules", "media", "visualnovel", "assets")
if os.path.isdir(art_root):
    from PIL import Image
    art = scene.Art(art_root)
    pages = scene.paginate("word " * 200, art)
    assert len(pages) > 2
    for place in scene.PLACES:
        for mood in scene.MOODS:
            art.stage(place, mood)                                           # every combination exists
    im = Image.open(io.BytesIO(scene.screen(art, "bridge", "smile", pages[0], "Gwen", 1, len(pages), "Gwen")))
    assert im.size == (scene.W, scene.H)
    assert Image.open(io.BytesIO(scene.map_screen(art, "grove", "Where to?"))).size == (scene.W, scene.H)
st = store.Store(os.path.join(tempfile.mkdtemp(), "vn.db"))
s = st.scene("g|u", "bridge"); assert s["place"] == "bridge" and s["pages"] == []
s.update(place="grove", mood="sad", pages=["a", "b"], page=1); st.save_scene("g|u", s)
assert st.scene("g|u", "bridge") == {"place": "grove", "mood": "sad", "pages": ["a", "b"], "page": 1}
for i in range(30):
    st.add("g|u", "user", f"m{i}", keep=10)
h = st.history("g|u"); assert len(h) == 10 and h[-1]["content"] == "m29"
st.mark("123", "g|u", "chat", "u"); assert st.screen("123") == {"key": "g|u", "kind": "chat", "user": "u"}
st.forget("g|u"); assert st.history("g|u") == [] and st.scene("g|u", "path")["place"] == "path"
st.close(); print("visual novel tests ok")
