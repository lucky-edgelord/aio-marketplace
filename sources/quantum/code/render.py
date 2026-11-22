"""Pictures of circuits and their results for phones, in the Lilith Learning Lab / Quantum Web Lab look with a
cyberpunk edge: the circuit with the lab's gate colours and a probability dial on every wire, a "Chances" chart and a
neon Bloch sphere per qubit. Portrait, 1080 pixels wide; drawn at twice the size and scaled down, so edges are smooth."""

from __future__ import annotations

import io
import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .qtext import fmt_angle, layout, qubits_of

S = 2                                       # supersampling
U = 2                                       # 540 design units -> 1080 px
BG, PANEL, PANEL2, LINE = (12, 8, 20), (27, 20, 41), (38, 27, 59), (58, 45, 85)
TEXT, MUTED, FAINT = (241, 235, 255), (169, 157, 199), (120, 108, 150)
ACC, ACC2, PINK, BLUE, CYAN, WIRE = (178, 107, 255), (217, 172, 255), (255, 92, 184), (107, 182, 255), (0, 240, 255), (90, 74, 128)
COLORS = {  # the lab's gate colours
    "h": (224, 106, 168), "x": (107, 182, 255), "y": (107, 182, 255), "z": (107, 182, 255), "s": (143, 211, 255),
    "sdg": (143, 211, 255), "t": (143, 211, 255), "tdg": (143, 211, 255), "p": (143, 211, 255), "rz": (178, 107, 255),
    "rx": (178, 107, 255), "ry": (178, 107, 255), "sx": (178, 107, 255), "sxdg": (178, 107, 255), "id": (138, 127, 168),
    "swap": (217, 172, 255), "measure": (107, 93, 140),
}
DARK = (26, 10, 42)
LABEL = {"id": "I", "h": "H", "x": "X", "y": "Y", "z": "Z", "s": "S", "sdg": "S†", "t": "T", "tdg": "T†", "sx": "√X",
         "sxdg": "√X†", "rx": "RX", "ry": "RY", "rz": "RZ", "p": "P"}
CTRL_BASE = {"cx": "x", "ccx": "x", "cy": "y", "cz": "z", "ccz": "z", "ch": "h", "cp": "p"}
K = S * U                                    # design unit -> drawing pixels


class Fonts:
    def __init__(self, root: Path | None):
        self.root = Path(root) if root else None

    @lru_cache(maxsize=64)
    def get(self, kind: str, size: float) -> ImageFont.FreeTypeFont:
        name = {"sans": "IBMPlexSans-Regular.ttf", "bold": "IBMPlexSans-SemiBold.ttf",
                "mono": "IBMPlexMono-Regular.ttf", "monob": "IBMPlexMono-SemiBold.ttf", "sym": "DejaVuSans.ttf",
                "symb": "DejaVuSans-Bold.ttf"}[kind]
        paths = ([self.root / name] if self.root else []) + [Path(name), Path("/usr/share/fonts/truetype/dejavu") / name,
                                                             Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
        for p in paths:
            try:
                return ImageFont.truetype(str(p), int(size * K))
            except OSError:
                pass
        return ImageFont.load_default(int(size * K))


def tw(d, text, font):
    return d.textlength(text, font=font)


def center_text(d, xy, text, font, fill):
    x, y = xy
    b = d.textbbox((0, 0), text, font=font)
    d.text((x - (b[2] - b[0]) / 2 - b[0], y - (b[3] - b[1]) / 2 - b[1]), text, font=font, fill=fill)


def glow(im: Image.Image, shape, color, radius: float, width: float = 0, alpha: int = 150, kind: str = "rect"):
    """A soft neon halo behind a shape. Only the area around the shape is blurred, so it stays fast."""
    pts = [shape[i:i + 2] for i in range(0, 4, 2)] if kind != "line" else list(shape)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    m = int(radius * 3 + width + 4)
    x0, y0 = max(0, int(min(xs)) - m), max(0, int(min(ys)) - m)
    x1, y1 = min(im.width, int(max(xs)) + m), min(im.height, int(max(ys)) + m)
    if x1 <= x0 or y1 <= y0:
        return
    layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
    g = ImageDraw.Draw(layer)
    fill = color + (alpha,)
    if kind == "rect":
        g.rounded_rectangle([shape[0] - x0, shape[1] - y0, shape[2] - x0, shape[3] - y0], radius=int(6 * K), fill=fill)
    elif kind == "ellipse":
        g.ellipse([shape[0] - x0, shape[1] - y0, shape[2] - x0, shape[3] - y0], fill=fill)
    else:
        g.line([(p[0] - x0, p[1] - y0) for p in pts], fill=fill, width=int(width))
    layer = layer.filter(ImageFilter.GaussianBlur(radius))
    im.alpha_composite(layer, (x0, y0))


def panel(im: Image.Image, box, title: str = "", fonts=None, note: str = ""):
    """A rounded lab card with cyberpunk corner brackets."""
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=int(14 * K), fill=PANEL + (255,), outline=LINE + (255,), width=int(1 * K))
    c, w = int(14 * K), int(2 * K)
    for (cx, cy, dx, dy, col) in ((x0, y0, 1, 1, CYAN), (x1, y1, -1, -1, PINK)):
        d.line([(cx + dx * 4 * K, cy + dy * (4 * K + c)), (cx + dx * 4 * K, cy + dy * 4 * K), (cx + dx * (4 * K + c), cy + dy * 4 * K)],
               fill=col + (255,), width=w)
    if title:
        d.text((x0 + 16 * K, y0 + 10 * K), title, font=fonts.get("bold", 17), fill=TEXT)
        if note:
            d.text((x0 + 16 * K + tw(d, title, fonts.get("bold", 17)) + 10 * K, y0 + 14 * K), note,
                   font=fonts.get("mono", 12), fill=FAINT)


# -- the circuit ---------------------------------------------------------------------------------------------------
def gate_text(op) -> tuple[str, str]:
    name = op[0]
    if name in ("rx", "ry", "rz", "p"):
        return LABEL[name], fmt_angle(op[1]).replace("pi", "π")
    if name == "cp":
        return "P", fmt_angle(op[1]).replace("pi", "π")
    base = CTRL_BASE.get(name, name)
    return LABEL.get(base, base.upper()), ""


def picture_layout(qc):
    """Like qtext.layout, but a measurement's line runs down to c: other gates can't sit below it in that step."""
    n = qc.num_qubits
    free, gates, out = [0] * n, [0] * n, []
    for op in qc.data:
        qs = qubits_of(op)
        if not qs:
            free = [max(free)] * n
            gates = list(free)
            continue
        if op[0] == "measure":
            q = qs[0]
            col = max([free[q]] + gates[q + 1:])
            free[q] = col + 1
        else:
            lo, hi = min(qs), max(qs)
            col = max(free[lo:hi + 1])
            for k in range(lo, hi + 1):
                free[k] = gates[k] = col + 1
        out.append((col, op))
    return out


def draw_circuit(im: Image.Image, box, qc, fonts: Fonts, p1: list[float]):
    """The circuit inside ``box``, with each wire's chance of 1 as a dial at its end (like the lab)."""
    d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = box
    placed = picture_layout(qc)
    n = qc.num_qubits
    has_c = any(op[0] == "measure" for op in qc.data)
    cols = max([c for c, _ in placed] + [-1]) + 1
    left, right = x0 + 52 * K, x1 - 46 * K
    f_gate, f_angle = fonts.get("symb", 16), fonts.get("mono", 10)
    widths = [44 * K] * max(cols, 1)
    for c, op in placed:
        sym, ang = gate_text(op)
        widths[c] = max(widths[c], int(max(tw(d, sym, f_gate), tw(d, ang, f_angle)) + 18 * K))
    scale = min(1.0, (right - left - 10 * K) / max(1, sum(widths)))
    widths = [int(w * scale) for w in widths]
    row = (y1 - y0 - (24 * K if has_c else 0)) / max(n, 1)
    box_h = int(min(40 * K * max(scale, 0.7), row * 0.78))
    if box_h < 30 * K:                           # many qubits: smaller tiles and type
        f_gate, f_angle = fonts.get("symb", max(9, 16 * box_h / (40 * K))), fonts.get("mono", max(7, 10 * box_h / (40 * K)))
    ys = [y0 + row * q + row / 2 for q in range(n)]
    cy = y1 - 18 * K
    xs, x = [], left + 6 * K
    for w in widths:
        xs.append(x + w / 2)
        x += w
    for q, y in enumerate(ys):
        lf = fonts.get("mono", 13 if row > 30 * K else max(8, row / K * 0.42))
        b_ = d.textbbox((0, 0), f"q[{q}]", font=lf)
        d.text((x0 + 12 * K, y - (b_[3] + b_[1]) / 2), f"q[{q}]", font=lf, fill=MUTED)
        d.line([(left, y), (right, y)], fill=WIRE + (255,), width=int(1.6 * K))
        # probability dial: the chance this qubit reads 1
        r, dx = min(14 * K, row * 0.32), right + 22 * K
        d.ellipse([dx - r, y - r, dx + r, y + r], outline=MUTED + (255,), width=int(1.3 * K))
        if p1[q] > 0.004:
            d.pieslice([dx - r + K, y - r + K, dx + r - K, y + r - K], -90, -90 + 360 * p1[q], fill=ACC + (255,))
    if has_c:
        d.text((x0 + 14 * K, cy - 8 * K), "c", font=fonts.get("mono", 11), fill=MUTED)
        for dy in (-2 * K, 2 * K):
            d.line([(left, cy + dy), (right, cy + dy)], fill=LINE + (255,), width=int(K))

    def tile(xc, y, name, sym, ang):
        color = COLORS.get(name, BLUE)
        w = max(box_h, int(max(tw(d, sym, f_gate), tw(d, ang, f_angle)) + 14 * K))
        shape = [xc - w / 2, y - box_h / 2, xc + w / 2, y + box_h / 2]
        glow(im, shape, color, 7 * K, alpha=110)
        d2 = ImageDraw.Draw(im)
        d2.rounded_rectangle(shape, radius=int(8 * K), fill=color + (255,))
        if ang:
            center_text(d2, (xc, y - 5 * K), sym, f_gate, DARK)
            center_text(d2, (xc, y + 10 * K), ang, f_angle, DARK)
        else:
            center_text(d2, (xc, y), sym, f_gate, DARK)

    for c, op in placed:
        xc, name, qs = xs[c], op[0], qubits_of(op)
        d = ImageDraw.Draw(im)
        if name == "measure":
            y = ys[op[1]]
            for off in (-1.5 * K, 1.5 * K):
                d.line([(xc + off, y + box_h / 2), (xc + off, cy - 5 * K)], fill=LINE + (255,), width=int(K))
            d.polygon([(xc - 5 * K, cy - 7 * K), (xc + 5 * K, cy - 7 * K), (xc, cy - 1 * K)], fill=MUTED + (255,))
            tile(xc, y, "measure", "", "")
            d = ImageDraw.Draw(im)
            d.arc([xc - 10 * K, y - 6 * K, xc + 10 * K, y + 14 * K], 200, 340, fill=(255, 255, 255, 255), width=int(1.8 * K))
            d.line([(xc, y + 5 * K), (xc + 7 * K, y - 7 * K)], fill=(255, 255, 255, 255), width=int(1.8 * K))
            continue
        if name == "swap":
            a, b = ys[qs[0]], ys[qs[1]]
            glow(im, [(xc, a), (xc, b)], COLORS["swap"], 4 * K, width=6 * K, kind="line")
            d = ImageDraw.Draw(im)
            d.line([(xc, a), (xc, b)], fill=COLORS["swap"] + (255,), width=int(2 * K))
            for y in (a, b):
                k = 7 * K
                d.line([(xc - k, y - k), (xc + k, y + k)], fill=COLORS["swap"] + (255,), width=int(3 * K))
                d.line([(xc - k, y + k), (xc + k, y - k)], fill=COLORS["swap"] + (255,), width=int(3 * K))
            continue
        if name in CTRL_BASE:
            base = CTRL_BASE[name]
            ctrls, target = qs[:-1], qs[-1]
            lo, hi = min(ys[q] for q in qs), max(ys[q] for q in qs)
            glow(im, [(xc, lo), (xc, hi)], CYAN, 4 * K, width=6 * K, kind="line", alpha=120)
            d = ImageDraw.Draw(im)
            d.line([(xc, lo), (xc, hi)], fill=CYAN + (255,), width=int(2 * K))
            for q in ctrls + ([target] if base == "z" else []):
                r = 6 * K
                glow(im, [xc - r, ys[q] - r, xc + r, ys[q] + r], CYAN, 4 * K, kind="ellipse")
                ImageDraw.Draw(im).ellipse([xc - r, ys[q] - r, xc + r, ys[q] + r], fill=CYAN + (255,))
            d = ImageDraw.Draw(im)
            if base == "x":
                r, y = 14 * K, ys[target]
                glow(im, [xc - r, y - r, xc + r, y + r], CYAN, 6 * K, kind="ellipse")
                d = ImageDraw.Draw(im)
                d.ellipse([xc - r, y - r, xc + r, y + r], fill=PANEL + (255,), outline=CYAN + (255,), width=int(2.4 * K))
                d.line([(xc - 8 * K, y), (xc + 8 * K, y)], fill=CYAN + (255,), width=int(2.4 * K))
                d.line([(xc, y - 8 * K), (xc, y + 8 * K)], fill=CYAN + (255,), width=int(2.4 * K))
            elif base != "z":
                sym, ang = gate_text(op)
                tile(xc, ys[target], base, sym, ang)
            continue
        sym, ang = gate_text(op)
        tile(xc, ys[qs[0]], name, sym, ang)


# -- chances -------------------------------------------------------------------------------------------------------
def draw_chart(im: Image.Image, box, dist: dict[str, float], fonts: Fonts, most: int = 16):
    """Vertical bars like the lab's Chances view: percent on top, outcome below."""
    x0, y0, x1, y1 = box
    total = sum(dist.values()) or 1
    items = sorted(dist.items())
    more = 0
    if len(items) > most:
        items = sorted(sorted(dist.items(), key=lambda kv: -kv[1])[:most])
        more = len(dist) - most
    d = ImageDraw.Draw(im)
    inner_l, inner_r = x0 + 16 * K, x1 - 16 * K
    count = max(1, len(items))
    slot = (inner_r - inner_l) / count
    bar_w = min(42 * K, slot * 0.62)
    top, base = y0 + 56 * K, y1 - (46 * K if more else 32 * K)
    nbits = len(items[0][0]) if items else 1
    f_lab = fonts.get("mono", min(14, max(7, slot / K / max(nbits, 1) * 1.55)))
    f_pct = fonts.get("monob", min(14, max(7, slot / K * 0.3)))
    peak = max([v / total for _, v in items] + [1e-9])
    for i, (k, v) in enumerate(items):
        p = v / total
        xc = inner_l + slot * (i + 0.5)
        h = max(2 * K, (base - top - 18 * K) * p / max(peak, 1e-9))
        shape = [xc - bar_w / 2, base - h, xc + bar_w / 2, base]
        if p > 0.001:
            glow(im, shape, PINK, 6 * K, alpha=90)
        bar = Image.new("RGBA", (max(1, int(bar_w)), max(1, int(h))))
        bd = ImageDraw.Draw(bar)
        for yy in range(bar.height):     # pink at the top to purple at the bottom, like the lab
            t = yy / max(1, bar.height - 1)
            bd.line([(0, yy), (bar.width, yy)], fill=tuple(int(PINK[j] * (1 - t) + ACC[j] * t) for j in range(3)) + (255,))
        mask = Image.new("L", bar.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, bar.width - 1, bar.height + 8 * K], radius=int(5 * K), fill=255)
        im.paste(bar, (int(shape[0]), int(shape[1])), mask)
        d = ImageDraw.Draw(im)
        center_text(d, (xc, base - h - 10 * K), f"{p * 100:.0f}%" if p >= 0.0995 or p == 0 else f"{p * 100:.1f}%", f_pct, TEXT)
        lab = k if count <= 8 or nbits <= 4 else k
        center_text(d, (xc, base + 14 * K), lab, f_lab, MUTED)
    d.line([(inner_l, base), (inner_r, base)], fill=LINE + (255,), width=int(K))
    if more:
        d.text((inner_l, y1 - 24 * K), f"+ {more} more outcomes (the {most} most likely are shown)",
               font=fonts.get("sans", 10.5), fill=FAINT)


# -- Bloch spheres -------------------------------------------------------------------------------------------------
def bloch_vectors(state: list[complex], n: int) -> list[tuple[float, float, float]]:
    out = []
    for q in range(n):
        bit = 1 << q
        p0 = p1 = 0.0
        rho01 = 0j
        for i, a in enumerate(state):
            if i & bit:
                p1 += abs(a) ** 2
            else:
                p0 += abs(a) ** 2
                rho01 += a * state[i | bit].conjugate()
        out.append((2 * rho01.real, -2 * rho01.imag, p0 - p1))
    return out


AZ, EL = math.radians(35), math.radians(18)


def project(v, cx, cy, r):
    x, y, z = v
    sx = y * math.cos(AZ) - x * math.sin(AZ)
    depth = x * math.cos(AZ) + y * math.sin(AZ)
    sy = -z * math.cos(EL) + depth * math.sin(EL)
    return cx + r * sx, cy + r * sy, depth


def draw_bloch(im: Image.Image, center, r: float, v, label: str, fonts: Fonts):
    cx, cy = center
    # the ball: dark glass with a neon rim
    glow(im, [cx - r, cy - r, cx + r, cy + r], ACC, 10 * K, kind="ellipse", alpha=70)
    ball = Image.new("RGBA", (int(2 * r), int(2 * r)), (0, 0, 0, 0))
    px = ball.load()
    for yy in range(ball.height):
        for xx in range(ball.width):
            dx, dy = (xx - r) / r, (yy - r) / r
            dd = dx * dx + dy * dy
            if dd <= 1:
                hx, hy = dx + 0.42, dy + 0.48
                light = max(0.0, 1 - (hx * hx + hy * hy) / 2.0)
                rim = dd ** 4
                px[xx, yy] = tuple(int(min(255, (30, 20, 52)[j] + (80, 60, 140)[j] * light * 0.6 + (178, 107, 255)[j] * rim * 0.55))
                                   for j in range(3)) + (255,)
    mask = Image.new("L", ball.size, 0)
    ImageDraw.Draw(mask).ellipse([0, 0, ball.width - 1, ball.height - 1], fill=255)
    im.paste(ball, (int(cx - r), int(cy - r)), mask.filter(ImageFilter.GaussianBlur(K / 2)))
    d = ImageDraw.Draw(im)

    def curve(points, front, back, width):
        for a, b in zip(points, points[1:]):
            d.line([a[:2], b[:2]], fill=(front if (a[2] + b[2]) / 2 >= 0 else back) + (255,), width=int(width))

    ts = [i * math.pi / 60 for i in range(121)]
    curve([project((math.cos(t), math.sin(t), 0), cx, cy, r) for t in ts], (0, 200, 220), (40, 70, 100), 1.4 * K)
    curve([project((0, math.sin(t), math.cos(t)), cx, cy, r) for t in ts], (120, 90, 180), (60, 45, 95), 0.9 * K)
    f_ax = fonts.get("mono", 10)
    for vec, name in (((1, 0, 0), "x"), ((0, 1, 0), "y"), ((0, 0, 1), "|0⟩"), ((0, 0, -1), "|1⟩")):
        a, b = project((0, 0, 0), cx, cy, r), project(vec, cx, cy, r)
        d.line([a[:2], b[:2]], fill=(90, 74, 128, 255), width=int(0.8 * K))
        lx, ly, _ = project(tuple(c * 1.2 for c in vec), cx, cy, r)
        center_text(d, (lx, ly), name, fonts.get("sym", 12) if "⟩" in name else f_ax, MUTED if "⟩" in name else FAINT)
    length = math.sqrt(sum(c * c for c in v))
    base = project((0, 0, 0), cx, cy, r)
    if length > 0.02:
        tip = project(v, cx, cy, r)
        glow(im, [base[:2], tip[:2]], PINK, 5 * K, width=9 * K, kind="line", alpha=170)
        d = ImageDraw.Draw(im)
        d.line([base[:2], tip[:2]], fill=PINK + (255,), width=int(3 * K))
        rr = 5.5 * K
        glow(im, [tip[0] - rr * 2, tip[1] - rr * 2, tip[0] + rr * 2, tip[1] + rr * 2], PINK, 5 * K, kind="ellipse")
        d = ImageDraw.Draw(im)
        d.ellipse([tip[0] - rr, tip[1] - rr, tip[0] + rr, tip[1] + rr], fill=(255, 235, 248, 255), outline=PINK + (255,), width=int(1.6 * K))
    rr = 2.5 * K
    d.ellipse([base[0] - rr, base[1] - rr, base[0] + rr, base[1] + rr], fill=MUTED + (255,))
    theta = math.degrees(math.acos(max(-1, min(1, v[2] / length)))) if length > 1e-6 else 0
    phi = math.degrees(math.atan2(v[1], v[0])) % 360 if math.hypot(v[0], v[1]) > 1e-6 else 0
    center_text(d, (cx, cy + r * 1.25 + 16 * K), label, fonts.get("bold", 15), TEXT)
    stats = (f"θ {theta:.0f}°  φ {phi:.0f}°" if length > 0.98 else
             "entangled" if length < 0.02 else f"partly · {length:.2f}")
    center_text(d, (cx, cy + r * 1.25 + 34 * K), stats, fonts.get("sym", 11.5), FAINT)


# -- the card ----------------------------------------------------------------------------------------------------
def p_one(state: list[complex], n: int) -> list[float]:
    return [sum(abs(a) ** 2 for i, a in enumerate(state) if i >> q & 1) for q in range(n)]


def card(qc, dist: dict[str, float], state: list[complex], fonts: Fonts, title: str, chart_title: str,
         max_spheres: int = 4, footer: str = "") -> bytes:
    """Always 1080 x 1440 (3:4), so every answer shows at the same size in chat. Everything scales to fit."""
    W, H = 540 * K, 720 * K
    pad = 14 * K
    n = qc.num_qubits
    im = Image.new("RGBA", (W, H), BG + (255,))
    d = ImageDraw.Draw(im)
    for yy in range(0, H, int(4 * K)):            # faint scanlines
        d.line([(0, yy), (W, yy)], fill=(18, 12, 30, 255), width=1)
    tf = fonts.get("bold", 26)
    while tw(d, title, tf) > W - 2 * pad and tf.size > 14 * K:
        tf = fonts.get("bold", tf.size / K - 2)
    d.text((pad + 2 * K, 12 * K), title, font=tf, fill=TEXT)
    gates = sum(1 for op in qc.data if op[0] not in ("barrier", "measure"))
    depth = max([c for c, _ in layout(qc)] + [-1]) + 1
    meta = f"{n} QUBIT{'S' if n != 1 else ''} // {gates} GATE{'S' if gates != 1 else ''} // DEPTH {depth}"
    d.text((pad + 2 * K, 46 * K), meta, font=fonts.get("mono", 12), fill=CYAN)
    glow(im, [(pad, 68 * K), (W - pad, 68 * K)], PINK, 3 * K, width=3 * K, kind="line", alpha=200)
    d = ImageDraw.Draw(im)
    d.line([(pad, 68 * K), (W * 0.55, 68 * K)], fill=PINK + (255,), width=int(1.5 * K))
    d.line([(W * 0.55, 68 * K), (W - pad, 68 * K)], fill=CYAN + (255,), width=int(1.5 * K))
    # circuit
    c0, c1 = 78 * K, 290 * K
    panel(im, [pad, c0, W - pad, c1], "Circuit", fonts, "dial = chance of 1")
    draw_circuit(im, [pad, c0 + 42 * K, W - pad, c1 - 10 * K], qc, fonts, p_one(state, n))
    # chances
    h0, h1 = 300 * K, 494 * K
    panel(im, [pad, h0, W - pad, h1], "Chances", fonts, chart_title)
    draw_chart(im, [pad, h0, W - pad, h1], dist, fonts, most=8 if n > 3 else 16)
    # Bloch spheres: one row
    b0, b1 = 504 * K, 706 * K
    vecs = bloch_vectors(state, n)[:max(1, max_spheres)] if state is not None else []
    note = "before measurement" + (f" · {len(vecs)} of {n}" if n > len(vecs) else "")
    panel(im, [pad, b0, W - pad, b1], "Bloch spheres", fonts, note)
    if vecs:
        cell = (W - 2 * pad - 16 * K) / len(vecs)
        r = min(48 * K, cell / 2 - 14 * K, (b1 - b0 - 44 * K - 52 * K) / 2.5)
        cy = b0 + 44 * K + r * 1.25
        for i, v in enumerate(vecs):
            draw_bloch(im, (pad + 8 * K + cell * (i + 0.5), cy), r, v, f"q[{i}]", fonts)
    if footer:
        ImageDraw.Draw(im).text((pad + 2 * K, H - 12 * K), footer, font=fonts.get("mono", 9.5), fill=FAINT)
    im = im.convert("RGB").resize((W // S, H // S), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()
