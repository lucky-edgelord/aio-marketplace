"""Run: python3 sources/piston/test_piston.py (a folder named code shadows the stdlib, so no pytest here).
With PISTON_TEST_URL set (a Piston server or a stand-in), also runs code end to end through the cog."""
import asyncio, importlib, os, sys, types
base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "code")
pkg = types.ModuleType("pst"); pkg.__path__ = [base]; sys.modules["pst"] = pkg
parse = importlib.import_module("pst.parse"); swap = importlib.import_module("pst.codeswap")
B = "```"
j = parse.parse(f"python\n{B}py\nprint(1)\n{B}")
assert (j.language, j.source.strip(), j.args, j.stdin) == ("python", "print(1)", [], "")
j = parse.parse(f"\n{B}js\nconsole.log(1)\n{B}")
assert j.language == "js"
j = parse.parse(f"py -> diff\nfirst arg\nsecond arg\n{B}\nimport sys\n{B}\nline one\nline two")
assert j.output_syntax == "diff" and j.args == ["first arg", "second arg"] and j.stdin == "line one\nline two"
j = parse.parse(f"py {B}print(2){B}")
assert j.language == "py" and j.source == "print(2)"
j = parse.parse("", ("hello.rs", "fn main(){}"))
assert j.language == "rs" and j.source == "fn main(){}"
for bad in ("python", f"{B}\nprint(1)\n{B}", f"py\n{B}\n\n{B}"):
    try:
        parse.parse(bad); raise SystemExit(f"should fail: {bad!r}")
    except parse.RunError:
        pass
kind, out = parse.format_output({"run": {"stdout": "x\n" * 100, "stderr": "", "output": "x\n" * 100, "code": 0}}, "py")
assert kind == "ok" and out.endswith("[...]") and out.count("\n") <= 31
kind, out = parse.format_output({"run": {"stdout": "", "stderr": "boom", "output": "boom", "code": 1}}, "py")
assert kind == "stderr" and out == "boom"
kind, _ = parse.format_output({"compile": {"stderr": "err", "code": 1}, "run": {"output": "", "stdout": ""}}, "c")
assert kind == "compile"
assert parse.format_output({"run": {"output": "", "stdout": ""}}, "py")[0] == "empty"
assert "```" not in parse.format_output({"run": {"stdout": "a```b", "output": "a```b", "code": 0}}, "py")[1]
assert "int main()" in swap.add_boilerplate("c", 'printf("hi");')
assert swap.add_boilerplate("python", "print(1)") == "print(1)"

url = os.environ.get("PISTON_TEST_URL")
if url:
    cogm = importlib.import_module("pst.cog")
    cfg = types.SimpleNamespace(get=lambda k, d=None: {"piston": {"piston_url": url, "runs_per_minute": 100}}.get(k, d), prefix="!")
    cog = cogm.Piston(types.SimpleNamespace(config=cfg))
    async def go():
        e = await cog.execute(f"py\nhello\n{B}\nimport sys\nprint(sys.argv[1], input())\n{B}\nworld")
        assert "hello world" in e.description and e.title.startswith("▶️ python"), (e.title, e.description)
        e = await cog.execute(f"py\n{B}\nraise SystemExit('nope')\n{B}")
        assert "errors" in e.title and "nope" in e.description and "exit 1" in e.footer.text
        e = await cog.execute(f"python\n{B}\nwhile True: pass\n{B}")
        assert "killed" in e.footer.text, e.footer.text
        e = await cog.execute(f"sh\n{B}\necho $((6*7))\n{B}")
        assert "42" in e.description
        try:
            await cog.execute(f"cobol\n{B}\nx\n{B}"); raise SystemExit("unknown language passed")
        except parse.RunError as err:
            assert "cobol" in str(err)
    asyncio.run(go())
    print("end-to-end ok")
print("piston tests ok")
