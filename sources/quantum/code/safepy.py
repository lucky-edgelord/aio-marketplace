"""Run MicroQiskit snippets from chat without running Python: a small interpreter over Python's syntax tree that only
knows circuit code (assignments, for over range or a list, if, arithmetic, f-strings, print, MicroQiskit and a few
math functions). Anything else is refused with a plain message. Steps, gates, loops and output are capped."""

from __future__ import annotations

import ast
import math
import operator

from . import microqiskit as mq


class SnippetError(Exception):
    """Something the snippet did that we don't allow or that failed, worded for people."""


GATE_METHODS = {"id", "h", "x", "y", "z", "s", "sdg", "t", "tdg", "sx", "sxdg", "rx", "ry", "rz", "p", "cx", "cy",
                "cz", "ch", "swap", "cp", "ccx", "ccz", "measure", "barrier", "measure_all", "draw", "qasm"}
ATTRS = {"num_qubits", "num_clbits", "data"}
BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
CMP = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
       ast.GtE: operator.ge, ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}


class Runner:
    def __init__(self, max_qubits: int = 12, max_gates: int = 500, max_steps: int = 20000, max_output: int = 3000):
        self.max_qubits, self.max_gates, self.max_steps, self.max_output = max_qubits, max_gates, max_steps, max_output
        self.steps = 0
        self.sims = 0
        self.out: list[str] = []
        self.circuits: list[mq.QuantumCircuit] = []
        self.env: dict = {}
        self.funcs = {
            "QuantumCircuit": self.make_circuit, "simulate": self.simulate, "from_qasm": self.from_qasm,
            "print": self.print, "range": self.range, "len": len, "abs": abs, "round": round, "min": min, "max": max,
            "int": int, "float": float, "str": str, "bool": bool, "sum": sum, "sorted": sorted, "list": list,
            "dict": dict, "enumerate": enumerate, "zip": zip, "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
            "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
            "exp": math.exp, "log": math.log, "radians": math.radians, "degrees": math.degrees,
        }
        self.consts = {"pi": math.pi, "tau": math.tau, "e": math.e, "True": True, "False": False, "None": None}

    # -- allowed functions ------------------------------------------------------------------------------------
    def make_circuit(self, n, c=0):
        if not isinstance(n, int) or not isinstance(c, int):
            raise SnippetError("QuantumCircuit takes whole numbers: QuantumCircuit(2, 2)")
        if n > self.max_qubits:
            raise SnippetError(f"{n} qubits is too many here; the limit is {self.max_qubits}.")
        if c > 64:
            raise SnippetError("That's a lot of classical bits; 64 at most.")
        qc = mq.QuantumCircuit(n, c)
        self.circuits.append(qc)
        return qc

    def from_qasm(self, text):
        qc = mq.from_qasm(str(text))
        if qc.num_qubits > self.max_qubits:
            raise SnippetError(f"{qc.num_qubits} qubits is too many here; the limit is {self.max_qubits}.")
        self.circuits.append(qc)
        return qc

    def simulate(self, qc, shots=1024, get="counts", seed=None):
        if not isinstance(qc, mq.QuantumCircuit):
            raise SnippetError("simulate() needs a QuantumCircuit.")
        if not isinstance(shots, int) or not 1 <= shots <= 100000:
            raise SnippetError("shots must be a whole number from 1 to 100000.")
        self.sims += 1
        if self.sims > 10:
            raise SnippetError("simulate() can be called 10 times at most here.")
        if get == "memory" and shots > 2000:
            raise SnippetError("get='memory' is limited to 2000 shots here.")
        return mq.simulate(qc, shots, get, seed)

    def print(self, *args, sep=" ", end="\n"):
        self.out.append(sep.join(str(a) for a in args) + end)
        if sum(len(s) for s in self.out) > self.max_output:
            raise SnippetError("That printed too much.")

    def range(self, *args):
        r = range(*args)
        if len(r) > 2000:
            raise SnippetError("Loops are limited to 2000 turns here.")
        return r

    # -- the interpreter ------------------------------------------------------------------------------------------
    def tick(self, node):
        self.steps += 1
        if self.steps > self.max_steps:
            raise SnippetError("That ran too long.")
        gates = sum(len(c.data) for c in self.circuits)
        if gates > self.max_gates:
            raise SnippetError(f"That's more than {self.max_gates} gates.")

    def run(self, source: str):
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as e:
            raise SnippetError(f"Python syntax error on line {e.lineno}: {e.msg}") from e
        try:
            self.block(tree.body)
        except SnippetError:
            raise
        except (ValueError, TypeError, ZeroDivisionError, IndexError, KeyError, OverflowError) as e:
            raise SnippetError(str(e) or type(e).__name__) from e
        return self

    def block(self, body):
        for st in body:
            self.stmt(st)

    def stmt(self, n):
        self.tick(n)
        line = f" (line {n.lineno})"
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            mod = getattr(n, "module", None) or (n.names[0].name if n.names else "")
            if mod.split(".")[0] not in ("microqiskit", "math", "qiskit"):
                raise SnippetError(f"Only microqiskit and math can be imported{line}.")
            return
        if isinstance(n, ast.Expr):
            self.expr(n.value)
            return
        if isinstance(n, ast.Assign):
            value = self.expr(n.value)
            for t in n.targets:
                self.assign(t, value, line)
            return
        if isinstance(n, ast.AugAssign) and isinstance(n.target, ast.Name):
            op = BIN.get(type(n.op))
            if not op:
                raise SnippetError(f"That operator isn't supported{line}.")
            self.env[n.target.id] = self.binop(op, self.name(n.target.id, line), self.expr(n.value), line)
            return
        if isinstance(n, ast.For):
            items = self.expr(n.iter)
            if not isinstance(items, (range, list, tuple, str, dict, enumerate, zip)):
                raise SnippetError(f"for can loop over range(), a list or a string{line}.")
            for count, item in enumerate(items):
                if count >= 2000:
                    raise SnippetError("Loops are limited to 2000 turns here.")
                self.assign(n.target, item, line)
                self.block(n.body)
            return
        if isinstance(n, ast.If):
            self.block(n.body if self.expr(n.test) else n.orelse)
            return
        if isinstance(n, ast.Pass):
            return
        raise SnippetError(f"{type(n).__name__} isn't supported here{line}. Circuits only need assignments, "
                           "for, if, print and MicroQiskit calls.")

    def assign(self, t, value, line):
        if isinstance(t, ast.Name):
            if t.id in self.funcs or t.id in ("pi",):
                raise SnippetError(f"Please don't rename {t.id}{line}.")
            self.env[t.id] = value
        elif isinstance(t, (ast.Tuple, ast.List)):
            vals = list(value)
            if len(vals) != len(t.elts):
                raise SnippetError(f"Can't unpack {len(vals)} values into {len(t.elts)} names{line}.")
            for e, v in zip(t.elts, vals):
                self.assign(e, v, line)
        else:
            raise SnippetError(f"Only names can be assigned here{line}.")

    def name(self, ident, line=""):
        if ident in self.env:
            return self.env[ident]
        if ident in self.consts:
            return self.consts[ident]
        if ident in self.funcs:
            return self.funcs[ident]
        raise SnippetError(f"{ident} isn't defined{line}.")

    def binop(self, op, a, b, line=""):
        if op is operator.pow and isinstance(b, (int, float)) and abs(b) > 64:
            raise SnippetError(f"That power is too big{line}.")
        if op is operator.mul and (isinstance(a, (str, list)) or isinstance(b, (str, list))):
            if (len(a) if isinstance(a, (str, list)) else a) * (len(b) if isinstance(b, (str, list)) else b) > 10000:
                raise SnippetError(f"That's too long{line}.")
        out = op(a, b)
        if isinstance(out, (str, list, tuple)) and len(out) > 10000:
            raise SnippetError(f"That's too long{line}.")
        return out

    def expr(self, n):
        self.tick(n)
        line = f" (line {getattr(n, 'lineno', '?')})"
        if isinstance(n, ast.Constant):
            if isinstance(n.value, (int, float, str, bool, complex)) or n.value is None:
                return n.value
            raise SnippetError(f"That kind of value isn't supported{line}.")
        if isinstance(n, ast.Name):
            return self.name(n.id, line)
        if isinstance(n, ast.BinOp):
            op = BIN.get(type(n.op))
            if not op:
                raise SnippetError(f"That operator isn't supported{line}.")
            return self.binop(op, self.expr(n.left), self.expr(n.right), line)
        if isinstance(n, ast.UnaryOp):
            v = self.expr(n.operand)
            if isinstance(n.op, ast.USub):
                return -v
            if isinstance(n.op, ast.UAdd):
                return +v
            if isinstance(n.op, ast.Not):
                return not v
            raise SnippetError(f"That operator isn't supported{line}.")
        if isinstance(n, ast.BoolOp):
            vals = n.values
            if isinstance(n.op, ast.And):
                v = True
                for x in vals:
                    v = self.expr(x)
                    if not v:
                        return v
                return v
            v = False
            for x in vals:
                v = self.expr(x)
                if v:
                    return v
            return v
        if isinstance(n, ast.Compare):
            left = self.expr(n.left)
            for op, right in zip(n.ops, n.comparators):
                r = self.expr(right)
                f = CMP.get(type(op))
                if not f:
                    raise SnippetError(f"That comparison isn't supported{line}.")
                if not f(left, r):
                    return False
                left = r
            return True
        if isinstance(n, ast.IfExp):
            return self.expr(n.body) if self.expr(n.test) else self.expr(n.orelse)
        if isinstance(n, (ast.List, ast.Tuple)):
            vals = [self.expr(e) for e in n.elts]
            return vals if isinstance(n, ast.List) else tuple(vals)
        if isinstance(n, ast.Dict):
            return {self.expr(k): self.expr(v) for k, v in zip(n.keys, n.values)}
        if isinstance(n, ast.Subscript):
            target = self.expr(n.value)
            if not isinstance(target, (list, tuple, dict, str)):
                raise SnippetError(f"Only lists, dicts and strings can be indexed{line}.")
            if isinstance(n.slice, ast.Slice):
                s = n.slice
                return target[slice(*(self.expr(x) if x is not None else None for x in (s.lower, s.upper, s.step)))]
            return target[self.expr(n.slice)]
        if isinstance(n, ast.JoinedStr):
            parts = []
            for v in n.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                else:
                    val = self.expr(v.value)
                    spec = "".join(str(x.value) for x in v.format_spec.values) if v.format_spec else ""
                    if any(len(d) > 2 for d in __import__("re").findall(r"\d+", spec)):
                        raise SnippetError(f"That format is too wide{line}.")
                    parts.append(format(val, spec))
            return "".join(parts)
        if isinstance(n, ast.Attribute):
            obj = self.expr(n.value)
            if isinstance(obj, mq.QuantumCircuit) and n.attr in ATTRS:
                return getattr(obj, n.attr)
            raise SnippetError(f"{n.attr} isn't available here{line}.")
        if isinstance(n, ast.Call):
            args = [self.expr(a) for a in n.args if not isinstance(a, ast.Starred)]
            if any(isinstance(a, ast.Starred) for a in n.args):
                raise SnippetError(f"*args isn't supported{line}.")
            kwargs = {}
            for k in n.keywords:
                if k.arg is None:
                    raise SnippetError(f"**kwargs isn't supported{line}.")
                kwargs[k.arg] = self.expr(k.value)
            f = n.func
            if isinstance(f, ast.Name):
                fn = self.name(f.id, line)
                if fn not in self.funcs.values():
                    raise SnippetError(f"{f.id} can't be called{line}.")
                return fn(*args, **kwargs)
            if isinstance(f, ast.Attribute):
                obj = self.expr(f.value)
                if isinstance(obj, mq.QuantumCircuit) and f.attr in GATE_METHODS:
                    return getattr(obj, f.attr)(*args, **kwargs)
                if isinstance(obj, dict) and f.attr in ("get", "items", "keys", "values"):
                    return list(getattr(obj, f.attr)(*args)) if f.attr != "get" else obj.get(*args)
                if isinstance(obj, list) and f.attr in ("append", "index", "count"):
                    return getattr(obj, f.attr)(*args)
                if isinstance(obj, str) and f.attr in ("join", "upper", "lower", "format", "replace", "split"):
                    return getattr(obj, f.attr)(*args, **kwargs)
                raise SnippetError(f".{f.attr}() isn't available here{line}.")
            raise SnippetError(f"That call isn't supported{line}.")
        raise SnippetError(f"{type(n).__name__} isn't supported here{line}.")

    def circuit(self):
        """The circuit to show: qc if there is one, else the last one made."""
        qc = self.env.get("qc")
        if isinstance(qc, mq.QuantumCircuit):
            return qc
        return self.circuits[-1] if self.circuits else None

    def printed(self) -> str:
        return "".join(self.out)
