"""Q text (the Q.js-style notation from quantum-web-lab) to and from MicroQiskit circuits, plus a console language.

    H-X#0-RZ(pi/2)-M          rows are qubits, steps are separated by - or spaces,
    I-X#1-I-------M           X#0 X#1 is a CNOT (the last # is the target)
"""

from __future__ import annotations

import re

from .microqiskit import QuantumCircuit, _ROT, _num as parse_angle  # noqa: F401

SYMS = {"I": "id", "H": "h", "X": "x", "Y": "y", "Z": "z", "S": "s", "SD": "sdg", "T": "t", "TD": "tdg",
        "SX": "sx", "SXD": "sxdg", "RX": "rx", "RY": "ry", "RZ": "rz", "P": "p", "M": "measure", "SWAP": "swap"}
CTRL = {"X": ["cx", "ccx"], "Z": ["cz", "ccz"], "Y": ["cy"], "H": ["ch"], "P": ["cp"]}
TOKEN = re.compile(r"^([A-Za-z]+)(?:\(([^)]*)\))?(?:#(\d+))?$")

INFO = {
    "id": "Does nothing.", "h": "Hadamard: makes a fair blend of 0 and 1.", "x": "X: flips 0 and 1 (a NOT).",
    "y": "Y: a flip with a twist of phase.", "z": "Z: flips the sign of the 1 part (phase).",
    "s": "S: a quarter turn of phase (90 degrees).", "sdg": "S dagger: undoes S.",
    "t": "T: an eighth turn of phase (45 degrees).", "tdg": "T dagger: undoes T.",
    "sx": "Square root of X: half a flip.", "sxdg": "Undoes SX.", "rx": "Rotate around X by an angle.",
    "ry": "Rotate around Y by an angle.", "rz": "Rotate around Z by an angle (turns phase).",
    "p": "Phase gate: turns the phase of 1 by an angle.", "cx": "CNOT: flips the target when the control is 1.",
    "cy": "Controlled Y.", "cz": "Controlled Z: flips the sign when both are 1.", "ch": "Controlled H.",
    "cp": "Controlled phase.", "ccx": "Toffoli: flips the target when both controls are 1.",
    "ccz": "Controlled-controlled Z.", "swap": "Swaps two qubits.",
    "measure": "Measure: read the qubit as a plain 0 or 1.",
}


def fmt_angle(a: float) -> str:
    from math import gcd, pi
    if abs(a) < 1e-12:
        return "0"
    sign, x = ("-" if a < 0 else ""), abs(a) / pi
    for m in range(1, 13):
        k = round(x * m)
        if 0 < k <= 4 * m and abs(x * m - k) < 1e-9:
            g = gcd(k, m)
            kk, mm = k // g, m // g
            return sign + ("pi" if kk == 1 else f"{kk}*pi") + ("" if mm == 1 else f"/{mm}")
    return sign + str(round(abs(a), 6))


def split_row(row: str) -> list[str]:
    out, cur, depth = [], "", 0
    for ch in row:
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and (ch == "-" or ch.isspace()):
            if cur:
                out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def from_text(text: str) -> QuantumCircuit:
    rows = [split_row(re.sub(r"//.*$", "", r).strip()) for r in str(text).splitlines()]
    rows = [r for r in rows if r] or [["I"]]
    width = max(len(r) for r in rows)
    has_m = any(t.upper() == "M" for r in rows for t in r)
    qc = QuantumCircuit(len(rows), len(rows) if has_m else 0)
    for col in range(width):
        groups: dict[str, dict] = {}
        for r, row in enumerate(rows):
            if col >= len(row):
                continue
            tok = row[col]
            m = TOKEN.match(tok)
            if not m:
                raise ValueError(f'I do not understand "{tok}" (row {r + 1}, step {col + 1})')
            sym = m.group(1).upper()
            g = SYMS.get(sym)
            if not g:
                raise ValueError(f'I do not know the gate "{m.group(1)}" (row {r + 1}, step {col + 1})')
            args = [parse_angle(a) for a in m.group(2).split(",")] if m.group(2) is not None else []
            if m.group(3) is not None:
                key = f"{sym}({m.group(2) or ''})"
                groups.setdefault(key, {"sym": sym, "p": args, "items": []})["items"].append((int(m.group(3)), r))
                continue
            if g == "id":
                continue
            if g == "measure":
                qc.measure(r, r)
            elif g in _ROT:
                if len(args) != 1:
                    raise ValueError(f"{m.group(1)} needs an angle, like {m.group(1)}(pi/2) (row {r + 1})")
                getattr(qc, g)(args[0], r)
            else:
                if args:
                    raise ValueError(f"{m.group(1)} takes no angle (row {r + 1})")
                getattr(qc, g)(r)
        for gr in groups.values():
            qs = [r for _, r in sorted(gr["items"])]
            if gr["sym"] == "SWAP":
                if len(qs) != 2:
                    raise ValueError(f"SWAP#0 and SWAP#1 must be used together (step {col + 1})")
                qc.swap(*qs)
                continue
            names = CTRL.get(gr["sym"])
            if not names:
                raise ValueError(f"{gr['sym']} cannot be linked with #")
            if len(qs) < 2 or len(qs) - 2 >= len(names):
                raise ValueError(f"{gr['sym']}#0 needs a partner like {gr['sym']}#1 in the same step (step {col + 1})")
            name = names[len(qs) - 2]
            if name == "cp":
                qc.cp(gr["p"][0] if gr["p"] else 0.0, *qs)
            else:
                getattr(qc, name)(*qs)
        qc.barrier()
    qc.data = [op for op in qc.data if op[0] != "barrier"]
    return qc


def qubits_of(op) -> list[int]:
    name = op[0]
    if name == "barrier":
        return []
    if name == "measure":
        return [op[1]]
    if name in _ROT:
        return [op[2]]
    if name == "cp":
        return [op[2], op[3]]
    return list(op[1:])


def layout(qc) -> list[tuple[int, tuple]]:
    """(step, op) for every gate, as early as it fits; a barrier starts a new step."""
    free = [0] * qc.num_qubits
    out = []
    for op in qc.data:
        qs = qubits_of(op)
        if not qs:
            top = max(free) if free else 0
            free = [top] * qc.num_qubits
            continue
        lo, hi = min(qs), max(qs)
        col = max(free[lo:hi + 1])
        for q in range(lo, hi + 1):
            free[q] = col + 1
        out.append((col, op))
    return out


def to_text(qc) -> str:
    placed = layout(qc)
    width = max([c for c, _ in placed] + [-1]) + 1
    grid = [["I"] * max(1, width) for _ in range(qc.num_qubits)]
    for col, op in placed:
        name = op[0]
        qs = qubits_of(op)
        if name == "measure":
            grid[op[1]][col] = "M"
        elif name in _ROT:
            grid[op[2]][col] = f"{name.upper()}({fmt_angle(op[1])})"
        elif name == "swap":
            for i, q in enumerate(qs):
                grid[q][col] = f"SWAP#{i}"
        elif name in ("cx", "cy", "cz", "ch", "cp", "ccx", "ccz"):
            base = {"cx": "X", "ccx": "X", "cy": "Y", "cz": "Z", "ccz": "Z", "ch": "H", "cp": "P"}[name]
            par = f"({fmt_angle(op[1])})" if name == "cp" else ""
            for i, q in enumerate(qs):
                grid[q][col] = f"{base}{par}#{i}"
        else:
            grid[qs[0]][col] = {v: k for k, v in SYMS.items()}.get(name, name.upper())
    return "\n".join("-".join(r) for r in grid)


def to_python(qc) -> str:
    """MicroQiskit code that builds the same circuit."""
    body, uses_pi = [], False
    for op in qc.data:
        name = op[0]
        if name == "barrier":
            body.append("qc.barrier()")
            continue
        if name == "measure":
            body.append(f"qc.measure({op[1]}, {op[2]})")
            continue
        if name == "id":
            continue
        if name in _ROT or name == "cp":
            a = fmt_angle(op[1])
            uses_pi |= "pi" in a
            body.append(f"qc.{name}({a}, {', '.join(map(str, op[2:]))})")
        else:
            body.append(f"qc.{name}({', '.join(map(str, op[1:]))})")
    head = ["from microqiskit import QuantumCircuit, simulate"] + (["from math import pi"] if uses_pi else [])
    size = f"{qc.num_qubits}" + (f", {qc.num_clbits}" if qc.num_clbits else "")
    return "\n".join(head + ["", f"qc = QuantumCircuit({size})"] + body + ["", "print(simulate(qc, 1000, 'counts'))"])


# -- the console: one command per line, like the lab's Q Console ----------------------------------------------
GATE_WORDS = {"i", "id", "h", "x", "y", "z", "s", "sdg", "t", "tdg", "sx", "sxdg", "rx", "ry", "rz", "p", "cx", "cnot",
              "cy", "cz", "ch", "cp", "ccx", "toffoli", "ccz", "swap", "measure", "m"}


def looks_like_console(text: str) -> bool:
    lines = [ln.strip() for ln in re.split(r"[;\n]", text) if ln.strip() and not ln.strip().startswith("//")]
    return bool(lines) and all(ln.split()[0].lower() in GATE_WORDS | {"qubits", "barrier"} for ln in lines)


def apply_console(qc_ops: list, n: int, text: str) -> tuple[list, int]:
    """Apply console lines like ``h 0``, ``cx 0 1``, ``rz pi/2 0``, ``measure`` to a saved circuit (ops, qubits)."""
    ops = list(qc_ops)
    for raw in re.split(r"[;\n]", text):
        line = re.sub(r"//.*$", "", raw).strip()
        if not line:
            continue
        word, *args = line.replace(",", " ").split()
        word = {"cnot": "cx", "toffoli": "ccx", "i": "id", "m": "measure"}.get(word.lower(), word.lower())
        if word == "qubits":
            if not args or not args[0].isdigit():
                raise ValueError("Use `qubits 3`.")
            n = int(args[0])
            continue
        if word == "barrier":
            ops.append(["barrier"])
            continue
        if word not in INFO:
            raise ValueError(f'I don\'t know "{line}". Try `h 0`, `cx 0 1`, `rz pi/2 0` or `measure`.')
        if word == "measure" and not args:
            ops.append(["measure_all"])
            continue
        if word in _ROT or word == "cp":
            if not args:
                raise ValueError(f"`{word}` needs an angle first, like `{word} pi/2 0`.")
            angle, qs = parse_angle(args[0]), args[1:]
        else:
            angle, qs = None, args
        if not qs or not all(q.isdigit() for q in qs):
            raise ValueError(f"`{line}`: say which qubit(s), like `{word} 0`.")
        need = {"cx": 2, "cy": 2, "cz": 2, "ch": 2, "cp": 2, "swap": 2, "ccx": 3, "ccz": 3}.get(word, 1)
        if len(qs) != need:
            raise ValueError(f"`{word}` needs {need} qubit{'s' if need > 1 else ''}.")
        ints = [int(q) for q in qs]
        n = max(n, max(ints) + 1)
        ops.append([word, angle, *ints])
    return ops, n


def build(ops: list, n: int) -> QuantumCircuit:
    has_m = any(o[0] in ("measure", "measure_all") for o in ops)
    qc = QuantumCircuit(n, n if has_m else 0)
    for o in ops:
        name = o[0]
        if name == "barrier":
            qc.barrier()
        elif name == "measure_all":
            for q in range(n):
                qc.measure(q, q)
        elif name == "measure":
            qc.measure(o[2], o[2])
        elif name in _ROT or name == "cp":
            getattr(qc, name)(o[1], *o[2:])
        else:
            getattr(qc, name)(*o[2:])
    return qc
