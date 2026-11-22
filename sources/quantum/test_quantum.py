"""Run: python3 sources/quantum/test_quantum.py (a folder named code shadows the stdlib, so no pytest here)."""
import importlib, io, os, sys, types
here = os.path.dirname(os.path.abspath(__file__))
pkg = types.ModuleType("qtest"); pkg.__path__ = [os.path.join(here, "code")]; sys.modules["qtest"] = pkg
mq, qt, sp, rd, cog = (importlib.import_module(f"qtest.{n}") for n in ("microqiskit", "qtext", "safepy", "render", "cog"))
assets = os.path.join(here, "..", "..", "modules", "media", "quantum", "assets")
cfg = types.SimpleNamespace(get=lambda k, d=None: {"quantum": {"assets_url": assets}}.get(k, d), prefix="!", data_dir="/tmp/qtest-data")
q = cog.Quantum(types.SimpleNamespace(config=cfg))

def probs(qc):
    return mq.simulate(qc, get="probabilities")

bell = {"00": 0.5, "11": 0.5}
# every input format gives the same Bell pair
for syn, code in [("q", "H-X#0-M\nI-X#1-M"), ("", "H-X#0\nI-X#1"),
                  ("qasm", 'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[2] q;\nh q[0];\ncx q[0], q[1];'),
                  ("", "OPENQASM 2.0;\nqreg q[2];\ncreg c[2];\nh q[0];\ncx q[0],q[1];\nmeasure q -> c;"),
                  ("python", "from microqiskit import QuantumCircuit\nqc = QuantumCircuit(2)\nqc.h(0)\nqc.cx(0, 1)"),
                  ("", "h 0\ncx 0 1")]:
    c, fmt, _ = q.circuit_from(syn, code)
    p = {k: round(v, 6) for k, v in probs(c).items()}
    assert p == bell, (syn, fmt, p)
# conversions round-trip
c, _, _ = q.circuit_from("q", "H-X#0-RZ(pi/2)-M\nI-X#1-I-------M")
for target in ("qasm", "qasm2", "python", "q", "diagram"):
    out = q.convert(c, target)
    assert out.strip(), target
assert "qreg q[2];" in q.convert(c, "qasm2") and "measure q[0] -> c[0];" in q.convert(c, "qasm2")
back, _, _ = q.circuit_from("qasm", q.convert(c, "qasm"))
assert back.data == c.data
back, _, _ = q.circuit_from("python", q.convert(c, "python"))
assert [op[0] for op in back.data] == [op[0] for op in c.data]
assert qt.to_text(qt.from_text("H-X#0-M\nI-X#1-M")).splitlines()[1].startswith("I-X#1")
# console
ops, n = qt.apply_console([], 1, "h 0; cx 0 1; rz pi/2 1; measure")
assert n == 2 and ops[-1] == ["measure_all"]
for bad in ("cx 0", "rz 0", "frob 1", "h"):
    try:
        qt.apply_console([], 1, bad); raise SystemExit(f"console accepted {bad!r}")
    except ValueError:
        pass
# options
assert q.options("shots=50 seed=3 -> qiskit") == ({"shots": 50, "seed": 3}, "python")
# python snippets are interpreted, never executed
for bad in ("import os", "open('x')", "(1).__class__", "while 1: pass", "QuantumCircuit(40)", "__import__('os')",
            "[x for x in range(3)]", "qc = QuantumCircuit(1)\nqc.__dict__"):
    try:
        q.circuit_from("python", bad); raise SystemExit(f"python accepted {bad!r}")
    except cog.QuantumError:
        pass
c, _, printed = q.circuit_from("python", "qc = QuantumCircuit(3, 3)\nqc.h(0)\nfor i in range(2):\n    qc.cx(i, i + 1)\n"
                               "qc.measure_all()\nprint(simulate(qc, 100, 'counts', seed=1))")
assert len(c.data) == 6 and "000" in printed
# simulate's seed no longer touches the global random generator
import random
random.seed(5); a = random.random(); random.seed(5); mq.simulate(c, 10, "counts", seed=1); assert random.random() == a
# Bloch vectors: |+> on x, |1> down, Bell pair has none
assert [round(x, 6) for x in rd.bloch_vectors([2 ** -0.5, 2 ** -0.5], 1)[0]] == [1, 0, 0]
assert [round(x, 6) for x in rd.bloch_vectors([0, 1], 1)[0]] == [0, 0, -1]
assert all(abs(x) < 1e-9 for x in rd.bloch_vectors([2 ** -0.5, 0, 0, 2 ** -0.5], 2)[0])
# the picture
if os.path.isdir(assets):
    from PIL import Image
    c, _, _ = q.circuit_from("q", "H-X#0-I---M\nI-X#1-X#0-M\nI-I---X#1-M")
    png, dist, measured = q.picture(c, 256, 1, "GHZ")
    im = Image.open(io.BytesIO(png))
    assert measured and set(dist) == {"000", "111"} and im.width == 1080 and len(png) < 900_000
    big, _, _ = q.circuit_from("", "\n".join(["h 0", *[f"cx 0 {k}" for k in range(1, 12)], "measure"]))
    png, _, _ = q.picture(big, 128, 1, "Twelve")
    assert len(png) < 900_000
q.saved.close()
print("quantum tests ok")
