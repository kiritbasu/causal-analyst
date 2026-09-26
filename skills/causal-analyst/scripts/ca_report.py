"""Render the causal-analyst report as one self-contained HTML page.

Numbers and charts come from results.json (written by `ca.py run`). The plain-language copy
comes from narrative.json, written by Claude after reading the results (schema in
references/report-template.md). Every section renders only when its data exists, so the same
template covers yes/no and amount treatments, trust tiers A-D, instruments and bounds.
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path

# ---------------------------------------------------------------------------- palette
INK, INK2, INK3, MUTED = "#141413", "#3d3c38", "#4a4945", "#5c5a55"
HAIR, BASE, CARD, GROUND = "#e4e2db", "#c3c2b7", "#fcfcfb", "#f6f4ef"
BLUE, ORANGE, GREY = "#2a78d6", "#eb6834", "#6b6964"
FAM = {"classical": "#6b6964", "ml": "#4a3aa7", "fm": "#1baf7a"}
WARN, GOODTXT, CRIT = "#fab219", "#006300", "#d03b3b"
TIER_FILL = {"A": "#0ca30c", "B": "#86b6ef", "C": WARN, "D": "#ec835a"}
TIER_WORD = {"A": "Strong", "B": "Good", "C": "Caution", "D": "Not answerable from this data"}
SERIF = "Newsreader, Georgia, serif"

METHODS = {
    # key: (label, year, year label, family, one-liner, citation)
    "regression_linear": ("Linear regression", 1805, "1800s", "classical", "Adjusts for each trait assuming straight-line relationships.", "Least squares, early 1800s"),
    "ipw_gbm": ("Propensity weighting", 1983, "1983", "classical", "Estimates each unit's chance of getting the action, then reweights so the groups look alike.", "Rosenbaum & Rubin, 1983"),
    "regression_gbm": ("ML regression", 1986, "1986", "ml", "Predicts each unit's outcome with and without the action.", "G-computation, Robins 1986"),
    "aipw_gbm": ("Doubly robust ML", 1994, "1994", "ml", "Models both who gets the action and the outcome; still right if either model is.", "Robins, Rotnitzky & Zhao, 1994"),
    "aipw_spline": ("Doubly robust, spline models", 1994, "1994", "ml", "The same recipe with smooth-curve models instead of trees.", "Robins, Rotnitzky & Zhao, 1994"),
    "double_ml": ("Double ML", 2018, "2018", "ml", "Strips out what the traits already predict, then compares what's left.", "Chernozhukov et al., 2018"),
    "causal_forest": ("Causal forest", 2018, "2018", "ml", "Thousands of decision trees that look for who benefits most.", "Wager & Athey, 2018"),
    "causalpfn": ("CausalPFN", 2025, "2025", "fm", "Built for cause and effect: reads the data and estimates the effect in one pass.", "Balazadeh et al., 2025"),
    "aipw_tabpfn": ("Doubly robust, TabPFN", 2023, "2023", "fm", "A general prediction model used as the engine inside the doubly robust recipe (hosted by Prior Labs).", "Hollmann et al., 2023; v2 2025"),
    "gcomp_linear": ("G-computation, straight line", 1986, "1986", "classical", "Predicts the outcome at each amount assuming a straight-line relationship.", "Robins, 1986"),
    "gcomp_spline5": ("G-computation, smooth curve (5 knots)", 1986, "1986", "ml", "Predicts the outcome at each amount with a flexible curve.", "Robins, 1986"),
    "gcomp_spline8": ("G-computation, smooth curve (8 knots)", 1986, "1986", "ml", "Predicts the outcome at each amount with a flexible curve.", "Robins, 1986"),
    "gcomp_spline12": ("G-computation, smooth curve (12 knots)", 1986, "1986", "ml", "Predicts the outcome at each amount with a flexible curve.", "Robins, 1986"),
    "gcomp_gbm": ("G-computation, boosted trees", 1986, "1986", "ml", "Predicts the outcome at each amount with gradient-boosted trees.", "Robins, 1986"),
}
FAMILY_TEXT = {
    "classical": ("1800s to 1980s", "Classical statistics", "Fit a simple formula, then compare like with like. Transparent and fast.",
                  "wrong when relationships are curved; weighting gets shaky when some units were near-certain to get the action."),
    "ml": ("1986 to 2018", "Machine learning with statistical guarantees", "Flexible machine-learning models learn the patterns; a statistical recipe corrects their bias and gives honest ranges. Today's standard in industry and research.",
           "need a few thousand rows to shine, and like every method here, can't see factors missing from the data."),
    "fm": ("2023 to today", "Foundation models", "Transformers, the architecture behind large language models, pre-trained on millions of simulated datasets. They recognise the pattern in your data without being trained on it.",
           "the newest and least proven. Accurate in tests, but their own ranges run too narrow, so they are cross-checks only."),
}


def e(s) -> str:
    return html.escape(str(s), quote=True)


class Fmt:
    def __init__(self, n):
        self.pre = n.get("value_prefix", "")
        self.suf = n.get("value_suffix", "")
        self.dec = int(n.get("decimals", 2))
        self.k = float(n.get("value_scale", 1))

    def __call__(self, v, sign=False, dec=None):
        if v is None:
            return "n/a"
        v = v * self.k
        d = self.dec if dec is None else dec
        s = f"{abs(v):,.{d}f}"
        lead = "−" if v < 0 else ("+" if sign and v > 0 else "")
        return f"{lead}{self.pre}{s}{self.suf}"


def nice_ticks(lo, hi, n=6):
    span = hi - lo if hi > lo else 1.0
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=mag * 10)
    start = math.floor(lo / step) * step
    ticks, t = [], start
    while t <= hi + 1e-9:
        ticks.append(round(t, 10))
        t += step
    return ticks


def tick_dec(ticks):
    if len(ticks) < 2:
        return 0
    step = abs(ticks[1] - ticks[0])
    d = max(0, -math.floor(math.log10(step)))
    if round(step * 10 ** d) % 1 or abs(step * 10 ** d - round(step * 10 ** d)) > 1e-9:
        d += 1
    return d


def sig_dec(v, sig=2):
    """Decimals that show `sig` significant figures (0 for |v| >= 10**(sig-1))."""
    if v == 0:
        return 0
    return max(0, sig - 1 - math.floor(math.log10(abs(v))))


def scale(d0, d1, r0, r1):
    return lambda v: r0 + (r1 - r0) * (v - d0) / (d1 - d0 if d1 != d0 else 1)


def bar_path(x0, x1, yc, h=24, r=4):
    """Horizontal bar from baseline x0 to data end x1, 4px rounded data end."""
    top, bot = yc - h / 2, yc + h / 2
    if abs(x1 - x0) < 2 * r:
        return f'<rect x="{min(x0, x1):.1f}" y="{top:.1f}" width="{abs(x1 - x0):.1f}" height="{h}" '
    if x1 >= x0:
        return (f'<path d="M{x0:.1f} {top:.1f} H{x1 - r:.1f} a{r} {r} 0 0 1 {r} {r} V{bot - r:.1f} '
                f'a{r} {r} 0 0 1 -{r} {r} H{x0:.1f} Z" ')
    return (f'<path d="M{x0:.1f} {top:.1f} H{x1 + r:.1f} a{r} {r} 0 0 0 -{r} {r} V{bot - r:.1f} '
            f'a{r} {r} 0 0 0 {r} {r} H{x0:.1f} Z" ')


def card(inner, extra=""):
    return f'<div class="card" {extra}>{inner}</div>'


def section(title, body, intro=None):
    i = f'<p class="intro">{e(intro)}</p>' if intro else ""
    return f'<section><h2>{e(title)}</h2>{i}{body}</section>'


# ---------------------------------------------------------------------------- charts
def chart_hero_range(est, lo, hi, f):
    d0 = min(0.0, lo) if lo is not None else min(0.0, est)
    d1 = max(hi if hi is not None else est, 0.0)
    pad = (d1 - d0) * 0.15 or 1
    d0, d1 = d0 - (pad if d0 < 0 else 0), d1 + pad
    X = scale(d0, d1, 6, 334)
    parts = [f'<svg width="300" height="54" viewBox="0 0 340 54" role="img" aria-label="Best estimate {e(f(est))}, likely range {e(f(lo))} to {e(f(hi))}">',
             f'<line x1="0" y1="22" x2="340" y2="22" stroke="#e1e0d9"/>',
             f'<line x1="{X(0):.1f}" y1="12" x2="{X(0):.1f}" y2="32" stroke="#8a8883"/>',
             f'<text x="{X(0):.1f}" y="50" font-size="12" fill="{MUTED}" text-anchor="middle">{e(f(0, dec=0))}</text>']
    if lo is not None and hi is not None:
        parts.append(f'<rect x="{X(lo):.1f}" y="14" width="{X(hi) - X(lo):.1f}" height="16" rx="8" fill="rgba(42,120,214,0.18)"/>')
        if X(hi) - X(lo) > 70 and X(lo) - X(0) > 40:
            parts += [f'<text x="{X(lo):.1f}" y="50" font-size="12" fill="{MUTED}" text-anchor="middle">{e(f(lo))}</text>',
                      f'<text x="{X(hi):.1f}" y="50" font-size="12" fill="{MUTED}" text-anchor="middle">{e(f(hi))}</text>']
    parts.append(f'<circle cx="{X(est):.1f}" cy="22" r="7" fill="{BLUE}" stroke="{CARD}" stroke-width="2"><title>Best estimate {e(f(est))}</title></circle></svg>')
    return "".join(parts)


def grade_scale(tier):
    cells = []
    for t in "ABCD":
        if t == tier:
            cells.append(f'<div class="gcell on" style="background:{TIER_FILL[t]}">{t}</div>')
        else:
            cells.append(f'<div class="gcell">{t}</div>')
    return f'<div class="grades" role="img" aria-label="Trust grade {tier}, {TIER_WORD[tier]}, on a scale from A to D">{"".join(cells)}</div>'


def chart_forest(rows, main_key, naive, f, bounds=None, width=1136):
    """rows: list of (key, label, est, lo, hi)."""
    vals = [v for _, _, est, lo, hi in rows for v in (est, lo, hi) if v is not None] + [0.0]
    if bounds:
        vals += [bounds[0], bounds[1]]
    d0, d1 = min(vals), max(vals)
    pad = (d1 - d0) * 0.08 or 1
    d0, d1 = (d0 - pad if d0 < 0 else d0), (d1 + pad if d1 > 0 else d1)
    naive_on = naive is not None and d0 <= naive <= d1 * 1.6
    if naive_on:
        d1 = max(d1, naive + pad)
        d0 = min(d0, naive - pad)
    ticks = nice_ticks(d0, d1, 7)
    d0, d1 = min(d0, ticks[0]), max(d1, ticks[-1])
    X = scale(d0, d1, 330, width - 90)
    n = len(rows) + (1 if naive_on else 0)
    H = 40 + n * 40 + 40
    axis_y = 30 + n * 40
    out = [f'<svg width="100%" viewBox="0 0 {width} {H}" role="img" aria-label="Estimates and 95% ranges by method">']
    if bounds:
        out.append(f'<rect x="{X(bounds[0]):.1f}" y="20" width="{X(bounds[1]) - X(bounds[0]):.1f}" height="{axis_y - 20}" fill="rgba(42,120,214,0.10)"><title>Range the true effect lies in, under stated assumptions: {e(f(bounds[0]))} to {e(f(bounds[1]))}</title></rect>')
    for t in ticks:
        out.append(f'<line x1="{X(t):.1f}" y1="20" x2="{X(t):.1f}" y2="{axis_y}" stroke="{"#c3c2b7" if t == 0 else "#ecebe5"}"/>')
        out.append(f'<text x="{X(t):.1f}" y="{axis_y + 22}" font-size="12" fill="{MUTED}" text-anchor="middle">{e(f(t, dec=tick_dec([t * f.k for t in ticks])))}</text>')
    out.append(f'<line x1="{X(d0):.1f}" y1="{axis_y}" x2="{X(d1):.1f}" y2="{axis_y}" stroke="{BASE}"/>')
    all_rows = list(rows) + ([("naive_difference", "Raw gap (not adjusted)", naive, None, None)] if naive_on else [])
    for i, (k, lab, est, lo, hi) in enumerate(all_rows):
        y = 50 + i * 40
        fam = METHODS.get(k, (None, None, None, "ml"))[3]
        is_main = k == main_key
        is_naive = k == "naive_difference"
        col = BLUE if is_main else (ORANGE if is_naive else GREY)
        if is_main:
            out.append(f'<rect x="0" y="{y - 18}" width="{width}" height="36" rx="8" fill="rgba(42,120,214,0.08)"/>')
        fw = 'font-weight="600" ' if is_main else ""
        out.append(f'<text x="12" y="{y + 5}" font-size="15" {fw}fill="{INK if is_main else INK2}">{e(lab)}</text>')
        if lo is not None and hi is not None:
            out.append(f'<line x1="{X(lo):.1f}" y1="{y}" x2="{X(hi):.1f}" y2="{y}" stroke="{col if is_main else "#8a8883"}" stroke-width="{3 if is_main else 2}" stroke-linecap="round"/>')
        rng = f" ({f(lo)} to {f(hi)})" if lo is not None else ""
        tip = f"<title>{e(lab)}: {e(f(est))}{e(rng)}</title>"
        if fam == "fm":
            out.append(f'<rect x="{X(est) - 6:.1f}" y="{y - 6}" width="12" height="12" transform="rotate(45 {X(est):.1f} {y})" fill="{col}" stroke="{CARD}" stroke-width="2">{tip}</rect>')
        else:
            out.append(f'<circle cx="{X(est):.1f}" cy="{y}" r="{7 if is_main else 5}" fill="{col}" stroke="{CARD}" stroke-width="2">{tip}</circle>')
        if is_main or is_naive:
            out.append(f'<text x="{max(X(est), X(hi) if hi is not None else X(est)) + 14:.1f}" y="{y + 5}" font-size="14" font-weight="600" fill="{INK}">{e(f(est))}</text>')
    if naive is not None and not naive_on:
        out.append(f'<text x="{width}" y="14" font-size="12" fill="{MUTED}" text-anchor="end">Raw gap {e(f(naive))} is off this scale →</text>')
    out.append("</svg>")
    return "".join(out)


def forest_legend(has_fm, main_key, bounds):
    items = []
    if main_key:
        items.append(f'<span class="lg"><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="6" fill="{BLUE}"/></svg>Main method, fixed before the run</span>')
    items.append(f'<span class="lg"><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="{GREY}"/></svg>{"Cross-check" if main_key else "Reference estimate (biased)"}</span>')
    if has_fm:
        items.append(f'<span class="lg"><svg width="14" height="14" aria-hidden="true"><rect x="3" y="3" width="8" height="8" transform="rotate(45 7 7)" fill="{GREY}"/></svg>Foundation model</span>')
    if bounds:
        items.append(f'<span class="lg"><svg width="14" height="14" aria-hidden="true"><rect x="1" y="1" width="12" height="12" fill="rgba(42,120,214,0.25)"/></svg>Range the true effect lies in (under stated assumptions; not a confidence interval)</span>')
    items.append('<span>Line = 95% likely range</span>')
    return f'<div class="legend">{"".join(items)}</div>'


def chart_timeline(keys):
    items = {}
    for k in keys:
        if k in METHODS:
            lab, yr, ylab, fam, _, cite = METHODS[k]
            items.setdefault((yr, fam), []).append((k, lab, ylab, cite))
    X = lambda yr: 40 if yr < 1900 else 140 + (min(yr, 2026) - 1980) * (960 / 46)
    out = ['<svg width="100%" viewBox="0 0 1136 262" role="img" aria-label="Timeline of when each method was first published">',
           f'<line x1="40" y1="150" x2="96" y2="150" stroke="{BASE}" stroke-width="2"/>',
           f'<line x1="108" y1="140" x2="100" y2="160" stroke="{BASE}" stroke-width="2"/><line x1="118" y1="140" x2="110" y2="160" stroke="{BASE}" stroke-width="2"/>',
           f'<line x1="122" y1="150" x2="1100" y2="150" stroke="{BASE}" stroke-width="2"/>',
           f'<text x="40" y="186" font-size="12" fill="{MUTED}" text-anchor="middle">1800s</text>']
    for yr in (1980, 1990, 2000, 2010, 2020):
        out.append(f'<text x="{X(yr):.1f}" y="186" font-size="12" fill="{MUTED}" text-anchor="middle">{yr}</text>')
    for i, ((yr, fam), group) in enumerate(sorted(items.items())):
        x = X(yr)
        up = i % 2 == 0
        col = FAM[fam]
        labels = [g[1] for g in group]
        anchor = "start" if x < 80 else ("end" if x > 1060 else "middle")
        tx = x if anchor == "middle" else (x if anchor == "start" else 1136)
        tip = "; ".join(f"{g[1]}: {g[3]}" for g in group)
        if up:
            out.append(f'<line x1="{x:.1f}" y1="150" x2="{x:.1f}" y2="{104}" stroke="{col}"/>')
            for j, lab in enumerate(reversed(labels)):
                out.append(f'<text x="{tx:.1f}" y="{78 - 16 * j}" font-size="13" font-weight="600" fill="{INK}" text-anchor="{anchor}">{e(lab)}</text>')
            out.append(f'<text x="{tx:.1f}" y="94" font-size="12" fill="{MUTED}" text-anchor="{anchor}">{e(group[0][2])}</text>')
        else:
            out.append(f'<line x1="{x:.1f}" y1="150" x2="{x:.1f}" y2="206" stroke="{col}"/>')
            for j, lab in enumerate(labels):
                out.append(f'<text x="{tx:.1f}" y="{226 + 16 * j}" font-size="13" font-weight="600" fill="{INK}" text-anchor="{anchor}">{e(lab)}</text>')
            out.append(f'<text x="{tx:.1f}" y="{226 + 16 * len(labels)}" font-size="12" fill="{MUTED}" text-anchor="{anchor}">{e(group[0][2])}</text>')
        if fam == "fm":
            out.append(f'<rect x="{x - 6:.1f}" y="144" width="12" height="12" transform="rotate(45 {x:.1f} 150)" fill="{col}" stroke="{CARD}" stroke-width="2"><title>{e(tip)}</title></rect>')
        else:
            out.append(f'<circle cx="{x:.1f}" cy="150" r="7" fill="{col}" stroke="{CARD}" stroke-width="2"><title>{e(tip)}</title></circle>')
    out.append("</svg>")
    return "".join(out)


def family_cards(keys, main_key):
    fams = {}
    for k in keys:
        if k in METHODS:
            fams.setdefault(METHODS[k][3], []).append(k)
    out = []
    for fam in ("classical", "ml", "fm"):
        if fam not in fams:
            continue
        span, name, how, watch = FAMILY_TEXT[fam]
        rows = "".join(
            f'<div class="mrow"><strong>{e(METHODS[k][0])}{" (main)" if k == main_key else ""}.</strong> <span>{e(METHODS[k][4])}</span></div>'
            for k in fams[fam])
        out.append(f'<div class="card fam" style="border-top:4px solid {FAM[fam]}"><div class="eyebrow">{e(span)}</div><h3>{e(name)}</h3>'
                   f'<p class="small">{e(how)}</p><div class="mlist">{rows}</div><div class="watch"><strong>Watch out:</strong> {e(watch)}</div></div>')
    return f'<div class="grid{len(out)}">{"".join(out)}</div>'


def chart_segments(segs, f, labels):
    """segs: diag['segments'] list; groups of (segment, not segment, difference)."""
    blocks = []
    i = 0
    while i < len(segs):
        grp = segs[i:i + 3]
        i += 3
        if len(grp) < 3 or any("error" in g for g in grp):
            continue
        a, b, d = grp
        vals = [0.0] + [v for g in (a, b) for v in (g["estimate"], *g["ci"])]
        ticks = nice_ticks(min(vals), max(vals), 5)
        X = scale(min(ticks[0], min(vals)), max(ticks[-1], max(vals)), 300, 980)
        out = [f'<svg width="100%" viewBox="0 0 1136 220" role="img" aria-label="Effect by group">']
        for t in ticks:
            out.append(f'<line x1="{X(t):.1f}" y1="16" x2="{X(t):.1f}" y2="176" stroke="{"#c3c2b7" if t == 0 else "#ecebe5"}"/>')
            out.append(f'<text x="{X(t):.1f}" y="198" font-size="12" fill="{MUTED}" text-anchor="middle">{e(f(t, dec=tick_dec([t * f.k for t in ticks])))}</text>')
        for row, g in ((50, a), (120, b)):
            name = labels.get(g["segment"], g["segment"])
            out.append(f'<text x="12" y="{row - 5}" font-size="15" font-weight="600" fill="{INK}">{e(name)}</text>')
            if g.get("n"):
                out.append(f'<text x="12" y="{row + 13}" font-size="12" fill="{MUTED}">{g["n"]:,} units</text>')
            out.append(bar_path(X(0), X(g["estimate"]), row) + f'fill="{BLUE}"><title>{e(name)}: {e(f(g["estimate"]))} ({e(f(g["ci"][0]))} to {e(f(g["ci"][1]))})</title></path>'
                       if abs(X(g["estimate"]) - X(0)) >= 8 else
                       f'<rect x="{min(X(0), X(g["estimate"])):.1f}" y="{row - 12}" width="{abs(X(g["estimate"]) - X(0)):.1f}" height="24" fill="{BLUE}"/>')
            lo, hi = X(g["ci"][0]), X(g["ci"][1])
            out.append(f'<line x1="{lo:.1f}" y1="{row}" x2="{hi:.1f}" y2="{row}" stroke="{INK}" stroke-width="2"/>'
                       f'<line x1="{lo:.1f}" y1="{row - 7}" x2="{lo:.1f}" y2="{row + 7}" stroke="{INK}" stroke-width="2"/>'
                       f'<line x1="{hi:.1f}" y1="{row - 7}" x2="{hi:.1f}" y2="{row + 7}" stroke="{INK}" stroke-width="2"/>')
            out.append(f'<text x="{max(hi, X(g["estimate"])) + 14:.1f}" y="{row + 5}" font-size="15" font-weight="600" fill="{INK}">{e(f(g["estimate"], sign=True))}</text>')
        out.append(f'<line x1="300" y1="176" x2="980" y2="176" stroke="{BASE}"/></svg>')
        out.append(f'<div class="note">Bars show the effect in each group; black whiskers are the 95% likely range. Difference: {e(f(d["estimate"], sign=True))} (range {e(f(d["ci"][0]))} to {e(f(d["ci"][1]))}){", clearly not noise" if d["ci"][0] > 0 or d["ci"][1] < 0 else ", which could be noise"}.</div>')
        blocks.append(card("".join(out)))
    return "".join(blocks)


def chart_overlap(hist, names):
    T, U = hist["treated"], hist["untreated"]
    m = max(max(T), max(U), 1)
    h = 110
    out = ['<svg width="100%" viewBox="0 0 540 284" role="img" aria-label="Distribution of the chance of getting the action, by group">',
           '<rect x="38" y="20" width="26" height="236" fill="#f0efec"/><rect x="494" y="20" width="26" height="236" fill="#f0efec"/>']
    for i, (t, u) in enumerate(zip(T, U)):
        x = 40 + 24 * i
        ht, hu = h * t / m, h * u / m
        rng = f"{i * 5}–{i * 5 + 5}%"
        out.append(f'<rect x="{x}" y="{138 - ht:.1f}" width="22" height="{ht:.1f}" fill="{BLUE}"><title>{t} {e(names[0])} with a {rng} chance</title></rect>')
        out.append(f'<rect x="{x}" y="142" width="22" height="{hu:.1f}" fill="{ORANGE}"><title>{u} {e(names[1])} with a {rng} chance</title></rect>')
    out += [f'<line x1="38" y1="140" x2="520" y2="140" stroke="{BASE}"/>',
            f'<text x="40" y="276" font-size="12" fill="{MUTED}" text-anchor="middle">0%</text>',
            f'<text x="280" y="276" font-size="12" fill="{MUTED}" text-anchor="middle">50%</text>',
            f'<text x="520" y="276" font-size="12" fill="{MUTED}" text-anchor="middle">100%</text>',
            '</svg>',
            f'<div class="legend"><span class="lg"><svg width="14" height="14" aria-hidden="true"><rect x="1" y="1" width="12" height="12" rx="2" fill="{BLUE}"/></svg>{e(names[0].capitalize())} (above the line)</span>'
            f'<span class="lg"><svg width="14" height="14" aria-hidden="true"><rect x="1" y="1" width="12" height="12" rx="2" fill="{ORANGE}"/></svg>{e(names[1].capitalize())} (below)</span>'
            f'<span>Across: estimated chance of getting the action</span></div>']
    return "".join(out)


def nice_var(name, labels):
    if name in labels:
        return labels[name]
    for col in sorted(labels, key=len, reverse=True):
        if name.startswith(col + "_"):
            return f"{labels[col]}: {name[len(col) + 1:]}"
    return name.replace("_", " ")


def chart_balance(bal, labels):
    rows = sorted(bal, key=lambda b: -abs(b["smd_before"]))[:8]
    vals = [v for b in rows for v in (b["smd_before"], b["smd_after_weighting"])]
    d0, d1 = min(-0.2, min(vals) - 0.05), max(1.2 if max(vals) > 0.6 else 0.6, max(vals) + 0.05)
    X = scale(d0, d1, 170, 480)
    H = 40 * len(rows) + 70
    ay = 40 * len(rows) + 16
    out = [f'<svg width="100%" viewBox="0 0 520 {H}" role="img" aria-label="Differences between groups before and after adjustment">',
           f'<rect x="{X(-0.1):.1f}" y="10" width="{X(0.1) - X(-0.1):.1f}" height="{ay - 10}" fill="rgba(12,163,12,0.10)"/>',
           f'<line x1="{X(0):.1f}" y1="10" x2="{X(0):.1f}" y2="{ay}" stroke="{BASE}"/>']
    for i, b in enumerate(rows):
        y = 30 + 40 * i
        name = nice_var(b["variable"], labels)
        xb, xa = X(b["smd_before"]), X(b["smd_after_weighting"])
        out.append(f'<text x="0" y="{y + 5}" font-size="14" fill="{INK2}">{e(name[:24])}</text>')
        out.append(f'<line x1="{min(xa, xb):.1f}" y1="{y}" x2="{max(xa, xb):.1f}" y2="{y}" stroke="#e1e0d9" stroke-width="2"/>')
        out.append(f'<circle cx="{xb:.1f}" cy="{y}" r="6" fill="{CARD}" stroke="{ORANGE}" stroke-width="2"><title>Before: {b["smd_before"]:.2f}</title></circle>')
        out.append(f'<circle cx="{xa:.1f}" cy="{y}" r="6" fill="{BLUE}" stroke="{CARD}" stroke-width="2"><title>After: {b["smd_after_weighting"]:.2f}</title></circle>')
    out.append(f'<line x1="170" y1="{ay}" x2="480" y2="{ay}" stroke="{BASE}"/>')
    for t in nice_ticks(d0, d1, 4):
        if d0 <= t <= d1:
            out.append(f'<text x="{X(t):.1f}" y="{ay + 18}" font-size="12" fill="{MUTED}" text-anchor="middle">{t:g}</text>')
    out.append(f'<text x="325" y="{ay + 36}" font-size="12" fill="{MUTED}" text-anchor="middle">Difference between groups (in standard deviations)</text></svg>')
    return "".join(out)


def chart_hidden(sens, labels):
    rv = sens["robustness_value"]
    bench = sens.get("benchmarks", [])[:6]
    top = max([b["strength"] for b in bench] + [rv]) * 1.15 or 1
    X = scale(0, top, 170, 460)
    H = 40 * max(len(bench), 1) + 60
    ay = 40 * max(len(bench), 1) + 12
    out = [f'<svg width="100%" viewBox="0 0 520 {H}" role="img" aria-label="Strength of recorded factors versus strength needed to erase the effect">']
    for i, b in enumerate(bench):
        y = 26 + 40 * i
        name = nice_var(b["confounder"], labels)
        out.append(f'<text x="0" y="{y + 5}" font-size="14" fill="{INK2}">{e(name[:24])}</text>')
        w = X(b["strength"]) - 170
        if w >= 8:
            out.append(bar_path(170, X(b["strength"]), y, h=20) + f'fill="{GREY}"><title>{b["strength"]:.2f}</title></path>')
        elif w > 0:
            out.append(f'<rect x="170" y="{y - 10}" width="{w:.1f}" height="20" fill="{GREY}"><title>{b["strength"]:.3f}</title></rect>')
    out.append(f'<line x1="{X(rv):.1f}" y1="8" x2="{X(rv):.1f}" y2="{ay}" stroke="{CRIT}" stroke-width="2" stroke-dasharray="5 4"/>')
    out.append(f'<text x="{X(rv) + 6:.1f}" y="{ay - 8}" font-size="13" fill="{INK}">Needed to erase: {rv:.2f}</text>')
    out.append(f'<line x1="170" y1="{ay}" x2="460" y2="{ay}" stroke="{BASE}"/>')
    for t in nice_ticks(0, top, 4):
        if t <= top:
            out.append(f'<text x="{X(t):.1f}" y="{ay + 20}" font-size="12" fill="{MUTED}" text-anchor="middle">{t:g}</text>')
    out.append("</svg>")
    return "".join(out)


def chart_subsets(subs, main, f):
    vals = subs + ([main] if main is not None else [])
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.4 or 1
    X = scale(lo - pad, hi + pad, 6, 294)
    out = [f'<svg width="300" height="46" viewBox="0 0 300 46" role="img" aria-label="Estimates on random 80% subsets"><line x1="0" y1="16" x2="300" y2="16" stroke="#e1e0d9"/>']
    if main is not None:
        out.append(f'<line x1="{X(main):.1f}" y1="4" x2="{X(main):.1f}" y2="28" stroke="{BLUE}" stroke-width="2"/>')
    for s in subs:
        out.append(f'<circle cx="{X(s):.1f}" cy="16" r="5" fill="{GREY}" stroke="{CARD}" stroke-width="2"><title>{e(f(s))}</title></circle>')
    out.append(f'<text x="0" y="42" font-size="12" fill="{MUTED}">{e(f(lo - pad))}</text><text x="300" y="42" font-size="12" fill="{MUTED}" text-anchor="end">{e(f(hi + pad))}</text></svg>')
    return "".join(out)


def _wrap2(t, width):
    words, lines, cur = str(t).split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    if len(lines) > 2:
        lines = [lines[0], (" ".join(lines[1:]))[: width - 1] + "…"]
    return lines


def _box_text(cx, cy, text, width_chars, size, fill, weight="400"):
    lines = _wrap2(text, width_chars)
    y0 = cy - (len(lines) - 1) * size * 0.6 + size * 0.35
    return "".join(f'<text x="{cx:.1f}" y="{y0 + i * size * 1.2:.1f}" font-size="{size}" font-weight="{weight}" text-anchor="middle" fill="{fill}">{e(l)}</text>' for i, l in enumerate(lines))


def chart_dag(dag):
    nodes = {n["id"]: n for n in dag["nodes"]}
    T, Y = dag["treatment"], dag["outcome"]
    ctrl = [n for n in nodes.values() if n["role"] in ("control", "other")]
    if len(ctrl) > 6:
        ctrl = [{"id": "__g", "label": f"{len(ctrl)} recorded traits", "role": "control"}]
    nudges = [n for n in nodes.values() if n["role"] == "nudge (instrument)"]
    hidden = [n for n in nodes.values() if n["role"] == "hidden"]
    after = [n for n in nodes.values() if n["role"] == "after the action"]
    meds = [n for n in nodes.values() if n["role"] == "middle step"]
    W = 508
    out = [f'<svg width="100%" viewBox="0 0 {W} 300" role="img" aria-label="Causal diagram of the assumptions">',
           '<defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#6b6964"/></marker>'
           '<marker id="ahb" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#141413"/></marker>'
           '<marker id="ahr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#b5542c"/></marker></defs>']
    tx0 = 20 + (90 if nudges else 0)
    tw = 150
    Tb = (tx0, 132, tw, 48)
    Yb = (W - 20 - tw, 132, tw, 48)
    k = max(len(ctrl), 1)
    cw = min(100, (W - 8 * (k - 1)) / k)
    x = (W - (k * cw + (k - 1) * 8)) / 2
    for c in ctrl:
        out.append(f'<rect x="{x:.1f}" y="4" width="{cw:.1f}" height="38" rx="8" fill="#f4f3ee" stroke="{BASE}"/>' + _box_text(x + cw / 2, 23, c["label"], max(6, int(cw / 6.6)), 11, INK))
        if c.get("role") == "control":
            out.append(f'<line x1="{x + cw / 2:.1f}" y1="44" x2="{Tb[0] + Tb[2] / 2 + (x - W / 2) / 12:.1f}" y2="130" stroke="#6b6964" stroke-width="1.2" marker-end="url(#ah)"/>')
            out.append(f'<line x1="{x + cw / 2:.1f}" y1="44" x2="{Yb[0] + Yb[2] / 2 + (x - W / 2) / 12:.1f}" y2="130" stroke="#6b6964" stroke-width="1.2" marker-end="url(#ah)"/>')
        x += cw + 8
    out.append(f'<rect x="{Tb[0]}" y="{Tb[1]}" width="{Tb[2]}" height="{Tb[3]}" rx="10" fill="{BLUE}"/>' + _box_text(Tb[0] + Tb[2] / 2, 156, nodes[T]["label"], 20, 12.5, "#ffffff", "600"))
    out.append(f'<rect x="{Yb[0]}" y="{Yb[1]}" width="{Yb[2]}" height="{Yb[3]}" rx="10" fill="#1d6b43"/>' + _box_text(Yb[0] + Yb[2] / 2, 156, nodes[Y]["label"], 20, 12.5, "#ffffff", "600"))
    if meds:
        mx = (Tb[0] + Tb[2] + Yb[0]) / 2
        out.append(f'<rect x="{mx - 50}" y="140" width="100" height="32" rx="8" fill="#f4f3ee" stroke="{BASE}"/><text x="{mx}" y="161" font-size="11.5" text-anchor="middle" fill="{INK}">{e(meds[0]["label"][:14])}</text>')
        out.append(f'<line x1="{Tb[0] + Tb[2] + 2}" y1="156" x2="{mx - 54}" y2="156" stroke="{INK}" stroke-width="2" marker-end="url(#ahb)"/><line x1="{mx + 52}" y1="156" x2="{Yb[0] - 4}" y2="156" stroke="{INK}" stroke-width="2" marker-end="url(#ahb)"/>')
    else:
        out.append(f'<line x1="{Tb[0] + Tb[2] + 2}" y1="156" x2="{Yb[0] - 4}" y2="156" stroke="{INK}" stroke-width="2" marker-end="url(#ahb)"/>')
    for i, z in enumerate(nudges[:1]):
        out.append(f'<rect x="4" y="140" width="84" height="32" rx="8" fill="#f4f3ee" stroke="{BASE}"/>' + _box_text(46, 156, z["label"], 12, 10.5, INK))
        out.append(f'<line x1="90" y1="156" x2="{Tb[0] - 4}" y2="156" stroke="#6b6964" stroke-width="1.2" marker-end="url(#ah)"/>')
    if hidden:
        hx = W / 2
        out.append(f'<rect x="{hx - 120}" y="236" width="240" height="40" rx="8" fill="#fff" stroke="#b5542c" stroke-dasharray="4 3"/>' + _box_text(hx, 256, hidden[0]["label"], 38, 11, "#b5542c"))
        out.append(f'<line x1="{hx - 60}" y1="236" x2="{Tb[0] + Tb[2] / 2}" y2="180" stroke="#b5542c" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ahr)"/>')
        out.append(f'<line x1="{hx + 60}" y1="236" x2="{Yb[0] + Yb[2] / 2}" y2="180" stroke="#b5542c" stroke-width="1.4" stroke-dasharray="5 4" marker-end="url(#ahr)"/>')
    if after and not hidden:
        a = after[0]
        cx = Tb[0] + Tb[2] / 2
        out.append(f'<line x1="{cx}" y1="178" x2="{cx}" y2="236" stroke="#8a8883" stroke-width="1.5" stroke-dasharray="2 4" marker-end="url(#ah)"/>')
        out.append(f'<rect x="{cx - 75}" y="238" width="150" height="32" rx="8" fill="#f0efec" stroke="#b5b3ab"/>' + _box_text(cx, 254, a["label"], 22, 12, INK3))
        out.append(f'<text x="{cx + 90}" y="252" font-size="12" fill="{INK3}">happens after the action:</text><text x="{cx + 90}" y="268" font-size="12" fill="{INK3}">not controlled for</text>')
    out.append("</svg>")
    return "".join(out)


def chart_bad_control(bc, f):
    a, b = bc["correct_controls"]["estimate"], bc["also_controlling_for_excluded"]["estimate"]
    lo, hi = min(0, a, b), max(0, a, b)
    pad = (hi - lo) * 0.12 or 1
    X = scale(lo - pad, hi + pad, 140, 440)
    out = [f'<svg width="100%" viewBox="0 0 520 150" role="img" aria-label="Estimate with and without the excluded columns as controls">',
           f'<line x1="{X(0):.1f}" y1="8" x2="{X(0):.1f}" y2="122" stroke="{BASE}"/>']
    for y, lab, v, col in ((36, "Correct controls", a, BLUE), (86, "Plus excluded", b, CRIT)):
        out.append(f'<text x="0" y="{y + 5}" font-size="13" font-weight="600" fill="{INK}">{lab}</text>')
        out.append(bar_path(X(0), X(v), y) + f'fill="{col}"><title>{e(f(v, sign=True))}</title></path>')
        inside = abs(X(v) - X(0)) > 90
        if inside:
            tx, anc, col_t = (X(0) + X(v)) / 2, "middle", "#ffffff"
        else:
            tx, anc, col_t = X(v) + (10 if v >= 0 else -10), ("start" if v >= 0 else "end"), INK
        out.append(f'<text x="{tx:.1f}" y="{y + 5}" font-size="13" font-weight="600" fill="{col_t}" text-anchor="{anc}">{e(f(v, sign=True))}</text>')
    out.append(f'<text x="{X(0):.1f}" y="142" font-size="12" fill="{MUTED}" text-anchor="middle">{e(f(0, dec=0))}</text></svg>')
    return "".join(out)


ROLE_STYLE = {"action": ("#dbe8f8", BLUE), "outcome": ("#dcefe4", "#1d6b43"), "control": ("#ecebe5", GREY),
              "nudge": ("#e7e3f6", "#4a3aa7"), "middle step": ("#e7e3f6", "#4a3aa7"), "left out": ("#fbe6dc", ORANGE), "not used": ("#f4f3ee", "#b5b3ab")}


def _num(v):
    a = abs(v)
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e4:
        return f"{v / 1e3:.0f}k"
    if a >= 100 or float(v).is_integer():
        return f"{v:,.0f}"
    return f"{v:.2f}" if a < 10 else f"{v:.1f}"


def mini_hist(counts):
    m = max(counts) or 1
    w = 120 / len(counts)
    bars = "".join(f'<rect x="{i * w + 0.5:.1f}" y="{28 - 26 * c / m:.1f}" width="{w - 1:.1f}" height="{26 * c / m:.1f}" fill="#8a8883"/>' for i, c in enumerate(counts))
    return f'<svg width="120" height="28" viewBox="0 0 120 28" aria-hidden="true">{bars}<line x1="0" y1="28" x2="120" y2="28" stroke="{BASE}"/></svg>'


def mini_cats(top, other, total):
    x, parts = 0.0, []
    shades = ["#6b6964", "#8a8883", "#a9a7a0", "#c3c2b7"]
    for i, t in enumerate(top):
        w = 120 * t["count"] / total
        parts.append(f'<rect x="{x:.1f}" y="6" width="{max(w - 1.5, 0.5):.1f}" height="16" rx="2" fill="{shades[i % 4]}"><title>{e(t["value"])}: {t["count"]:,}</title></rect>')
        x += w
    if other:
        parts.append(f'<rect x="{x:.1f}" y="6" width="{max(120 * other / total - 1.5, 0.5):.1f}" height="16" rx="2" fill="#e1e0d9"><title>other: {other:,}</title></rect>')
    return f'<svg width="120" height="28" viewBox="0 0 120 28" aria-hidden="true">{"".join(parts)}</svg>'


def data_section(ov, labels, names, units, n):
    tiles = [(f'{ov["rows"]:,}', units), (f'{ov["columns"]}', "columns")]
    if ov.get("treated_share") is not None:
        tiles.append((f'{ov["treated_share"]:.0%}', f'{names["treated"]}'))
    tiles.append((f'{ov["complete_rows_pct"]:.0f}%', "rows with no missing values"))
    tile_html = "".join(f'<div class="tile"><div class="tv">{e(v)}</div><div class="tl">{e(l)}</div></div>' for v, l in tiles)
    rows = []
    for c in ov["column_info"]:
        bg, fg = ROLE_STYLE.get(c["role"], ROLE_STYLE["not used"])
        chip = f'<span class="chip" style="background:{bg}"><i style="background:{fg}"></i>{e(c["role"])}</span>'
        name = labels.get(c["column"], c["column"])
        sub = f'<div class="raw">{e(c["column"])}</div>' if name != c["column"] else ""
        if c["n_unique"] == ov["rows"] and c["kind"] in ("number", "text/id") and c["role"] in ("left out", "not used"):
            viz, summ = "", f'unique for every row ({c["n_unique"]:,} values)'
        elif c["summary"] == "numeric":
            viz = mini_hist(c["histogram"]["counts"])
            summ = f'{_num(c["min"])} to {_num(c["max"])} · average {_num(c["mean"])}'
        else:
            viz = mini_cats(c["top"], c["other"], ov["rows"])
            summ = ", ".join(f'{t["value"]} ({t["count"] / ov["rows"]:.0%})' for t in c["top"][:3]) + (" …" if c["n_unique"] > 3 else "")
        if c.get("why_left_out"):
            summ += f'<div class="why">Left out: {e(c["why_left_out"])}</div>'
        miss = f'{c["missing_pct"]:.0f}%' if c["missing_pct"] >= 0.5 else ("<1%" if c["missing_pct"] > 0 else "none")
        rows.append(f'<tr><td><div class="cn">{e(name)}</div>{sub}</td><td>{chip}</td><td>{e(c["kind"])}</td><td>{miss}</td><td>{viz}</td><td class="sm">{summ}</td></tr>')
    more = f'<div class="note">Showing {ov["columns_shown"]} of {ov["columns"]} columns.</div>' if ov["columns_shown"] < ov["columns"] else ""
    table = (f'<div class="tscroll"><table class="cols"><tr><th>Column</th><th>Role in the analysis</th><th>Type</th><th>Missing</th><th>Distribution</th><th>Summary</th></tr>{"".join(rows)}</table></div>{more}')
    sample = ""
    if ov.get("sample_rows"):
        keys = list(ov["sample_rows"][0].keys())
        head = "".join(f'<th>{e(labels.get(k, k))}</th>' for k in keys)
        body = "".join("<tr>" + "".join(f'<td>{e(_num(v) if isinstance(v, float) else ("" if v is None else v))}</td>' for v in r.values()) + "</tr>" for r in ov["sample_rows"])
        sample = (f'<details><summary>First {len(ov["sample_rows"])} rows of the file (columns used in the analysis)</summary>'
                  f'<div class="tscroll"><table class="sample"><tr>{head}</tr>{body}</table></div></details>')
    return tile_html, table, sample


def check_row(title, text, extra=""):
    icon = f'<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="{GOODTXT}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-label="Passed"><path d="M20 6L9 17l-5-5"/></svg>'
    return f'<div class="check">{icon}<div><div class="ctitle">{e(title)}</div><div class="small">{e(text)}</div>{extra}</div></div>'


def fail_row(title, text):
    icon = f'<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="{CRIT}" stroke-width="2.5" stroke-linecap="round" aria-label="Failed"><path d="M18 6L6 18M6 6l12 12"/></svg>'
    return f'<div class="check">{icon}<div><div class="ctitle">{e(title)}</div><div class="small">{e(text)}</div></div></div>'


# ---------------------------------------------------------------------------- page
CSS = f"""
*{{box-sizing:border-box}}
html{{color-scheme:light}}
body{{margin:0;background:{GROUND};color:{INK};font-family:"IBM Plex Sans",system-ui,-apple-system,"Segoe UI",sans-serif}}
.page{{max-width:1280px;margin:0 auto;padding:56px 72px 72px;display:flex;flex-direction:column;gap:52px}}
.top{{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:{MUTED}}}
h1{{margin:0;font-family:{SERIF};font-weight:500;font-size:56px;line-height:1.05;letter-spacing:-.01em;max-width:980px}}
h2{{margin:0;font-family:{SERIF};font-weight:500;font-size:34px}}
h3{{margin:0;font-size:18px;font-weight:600}}
.lede{{margin:0;font-size:20px;line-height:1.5;color:{INK2};max-width:900px}}
section{{display:flex;flex-direction:column;gap:18px}}
.intro{{margin:0;font-size:16px;line-height:1.55;color:{INK2};max-width:860px}}
.card{{background:{CARD};border:1px solid {HAIR};border-radius:16px;padding:24px 28px;display:flex;flex-direction:column;gap:12px;min-width:0}}
.grid2,.grid3{{display:grid;gap:20px}}
.grid2{{grid-template-columns:repeat(2,minmax(0,1fr))}}
.grid3{{grid-template-columns:repeat(3,minmax(0,1fr))}}
.grid1{{display:grid;gap:20px}}
.eyebrow{{font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{MUTED}}}
.big{{font-family:{SERIF};font-size:80px;line-height:.9;font-weight:500}}
.bigrow{{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}}
.unit{{font-size:16px;color:{INK3}}}
.small{{font-size:14px;line-height:1.5;color:{INK2};margin:0}}
.note{{font-size:14px;color:{INK3}}}
.grades{{display:flex;gap:8px}}
.gcell{{width:52px;height:52px;border-radius:12px;border:1px solid #e1e0d9;display:flex;align-items:center;justify-content:center;font-size:20px;color:#8a8883}}
.gcell.on{{width:64px;border:none;font-size:26px;font-weight:600;color:{INK}}}
.tierword{{display:flex;align-items:center;gap:8px;font-size:18px;font-weight:600}}
ul.small{{padding-left:18px}}
.decomp{{display:flex;gap:2px;height:56px}}
.decomp div{{display:flex;align-items:center;padding-left:18px;font-weight:600;font-size:16px;white-space:nowrap;overflow:visible}}
.legend{{display:flex;gap:24px;flex-wrap:wrap;font-size:13px;color:{INK3}}}
.lg{{display:flex;align-items:center;gap:6px}}
.fam h3{{font-size:20px}}
.mlist{{display:flex;flex-direction:column;gap:10px;border-top:1px solid #ecebe5;padding-top:12px}}
.mrow{{font-size:14px;line-height:1.45}} .mrow span{{color:{INK2}}}
.watch{{font-size:13px;line-height:1.5;color:{INK2};background:#f4f3ee;border-radius:10px;padding:12px 14px}}
.check{{display:flex;gap:14px;align-items:flex-start}}
.ctitle{{font-size:15px;font-weight:600;margin-bottom:2px}}
.issue svg,.check svg{{flex:none}}
.issue{{background:#fff6e0;border:1px solid #f0d59a;border-radius:16px;padding:18px 22px;display:flex;gap:12px;align-items:flex-start}}
.dark{{background:{INK};color:#faf9f5;border-radius:16px;padding:28px 32px;display:flex;flex-direction:column;gap:16px}}
.dark h2{{color:#faf9f5;font-size:30px}}
.step{{display:flex;gap:14px;font-size:15px;line-height:1.5}} .step .n{{font-family:{SERIF};font-size:28px;color:#86b6ef;line-height:1}}
.q{{font-size:15px;line-height:1.5;color:{INK2}}} .q strong{{color:{INK}}}
footer{{border-top:1px solid #dcdad2;padding-top:20px;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px;font-size:13px;line-height:1.5;color:{INK3}}}
footer b{{color:{INK};display:block}}
.tiles{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:20px}}
.tile{{background:{CARD};border:1px solid {HAIR};border-radius:14px;padding:18px 22px}}
.tv{{font-family:{SERIF};font-size:40px;line-height:1}} .tl{{font-size:13px;color:{MUTED};margin-top:6px}}
.tscroll{{overflow-x:auto}}
table.cols td{{vertical-align:middle;font-size:14px}} .cn{{font-weight:600}} .raw{{font-size:12px;color:{MUTED};font-family:ui-monospace,Menlo,monospace}}
.sm{{color:{INK2};font-size:13px;max-width:320px}} .why{{font-size:12px;color:{MUTED};margin-top:2px}}
.chip{{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:3px 10px;font-size:12px;color:{INK};white-space:nowrap}} .chip i{{width:8px;height:8px;border-radius:50%;display:inline-block}}
table.sample td,table.sample th{{font-size:13px;white-space:nowrap}}
details{{font-size:14px}} summary{{cursor:pointer;color:{INK3}}}
table{{border-collapse:collapse;width:100%;margin-top:10px;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid #ecebe5}} th{{color:{MUTED};font-weight:500}}
svg text{{font-family:"IBM Plex Sans",system-ui,sans-serif}}
@media (max-width:900px){{.page{{padding:32px 16px}} .tiles{{grid-template-columns:repeat(2,minmax(0,1fr))}} .grid2,.grid3,footer{{grid-template-columns:minmax(0,1fr)}} h1{{font-size:38px}} .big{{font-size:60px}}}}
@media print{{body{{background:#fff}} .card,.issue{{break-inside:avoid}}}}
"""

WARN_ICON = f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="{INK}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l10 18H2z"/><path d="M12 10v5"/><path d="M12 18h.01"/></svg>'


def render(results: dict, narrative: dict) -> str:
    r, n = results, narrative
    f = Fmt(n)
    spec = r.get("spec", {})
    labels = dict(spec.get("labels", {}))
    labels.update(n.get("labels", {}))
    diag = r.get("diagnostics", {})
    est = r.get("estimates", {})
    main_key = r.get("main_method")
    main = r.get("main_result") or {}
    tier = r.get("trust_tier", "D")
    naive = (est.get("naive_difference") or {}).get("estimate")
    names = n.get("group_names", {"treated": "treated", "untreated": "untreated"})
    unit_word = n.get("units", "units")
    P = []

    # header
    meta = n.get("meta_line") or f'Run {r.get("manifest", {}).get("run_at_utc", "")[:10]} · {r.get("rows_used", 0):,} {unit_word} · method fixed before the run'
    P.append(f'<header style="display:flex;flex-direction:column;gap:16px"><div class="top"><span>Causal analysis · {e(n.get("eyebrow", ""))}</span><span>{e(meta)}</span></div>'
             f'<h1>{e(n.get("title", "What is the effect?"))}</h1><p class="lede">{n.get("answer_html") or e(n.get("answer", ""))}</p></header>')

    # hero cards
    hero = []
    if main_key and main.get("estimate") is not None:
        lo, hi = (main.get("ci") or [None, None])
        hero.append(card(f'<div class="eyebrow">{e(n.get("effect_label", "Effect"))}</div>'
                         f'<div class="bigrow"><span class="big">{e(f(main["estimate"], sign=True, dec=n.get("hero_decimals", sig_dec(main["estimate"] * f.k))))}</span><span class="unit">{e(n.get("unit", ""))}</span></div>'
                         + chart_hero_range(main["estimate"], lo, hi, f) +
                         f'<div class="note">95% likely range {e(f(lo))} to {e(f(hi))}</div>'))
    else:
        b = (diag.get("bounds_no_instrument") or {}).get("mtr_mts") or (diag.get("instrument") or {}).get("bounds_on_average_effect")
        body = f'<div class="eyebrow">{e(n.get("effect_label", "Effect"))}</div><div class="bigrow"><span class="big" style="font-size:56px">We can’t tell</span></div>'
        if b and b.get("lower") is not None:
            body += f'<div class="small">The true effect lies between <strong>{e(f(b["lower"]))}</strong> and <strong>{e(f(b["upper"]))}</strong>, under the assumptions below.</div>'
        hero.append(card(body))
    bullets = n.get("caution_bullets") or []
    blist = f'<ul class="small">{"".join(f"<li>{e(x)}</li>" for x in bullets)}</ul>' if bullets else ""
    hero.append(card(f'<div class="eyebrow">How much to trust it</div>{grade_scale(tier)}<div class="tierword">{WARN_ICON if tier in "CD" else ""}{TIER_WORD[tier]}</div>{blist}'))
    segs = diag.get("segments") or []
    if len(segs) >= 3 and "error" not in segs[0] and main_key:
        a, b = segs[0], segs[1]
        hero.append(card(f'<div class="eyebrow">{e(n.get("segment_card_title", "Who gains most"))}</div>'
                         f'<div class="bigrow"><span class="big">{e(f(a["estimate"], sign=True, dec=n.get("hero_decimals", sig_dec(a["estimate"] * f.k))))}</span><span class="unit">{e(labels.get(a["segment"], a["segment"]))}</span></div>'
                         f'<div class="bigrow"><span style="font-family:{SERIF};font-size:34px">{e(f(b["estimate"], sign=True, dec=n.get("hero_decimals", sig_dec(b["estimate"] * f.k))))}</span><span class="unit">{e(labels.get(b["segment"], b["segment"]))}</span></div>'
                         f'<div class="note">{e(n.get("segment_card_note", ""))}</div>'))
    elif n.get("third_card"):
        hero.append(card(f'<div class="eyebrow">{e(n["third_card"].get("title", ""))}</div><p class="small">{e(n["third_card"].get("text", ""))}</p>'))
    P.append(f'<section class="grid{len(hero)}" style="display:grid">{"".join(hero)}</section>')

    # the data
    ov = r.get("data_overview")
    if ov:
        tiles, table, sample = data_section(ov, labels, names, unit_word, n)
        P.append(section(n.get("data_title", "The data"), f'<div class="tiles">{tiles}</div>' + card(table + sample),
                         n.get("data_text") or f'What the analysis worked from: one row per {unit_word.rstrip("s")}, and the role each column played.'))

    # decomposition of the raw gap
    m_est = main.get("estimate")
    if main_key and naive and m_est is not None and naive * m_est > 0 and abs(m_est) < abs(naive):
        sel = naive - m_est
        share = sel / naive
        wsel = max(0.08, min(0.92, share))
        P.append(section(n.get("gap_title", f"Most of the {f(naive, dec=0)} gap isn't the action"),
                         f'<div class="decomp" role="img" aria-label="Raw gap {e(f(naive))}: {e(f(sel))} from who got the action, {e(f(m_est))} from the action itself">'
                         f'<div style="flex:{wsel:.3f};background:{ORANGE};border-radius:6px 0 0 6px;color:{INK}" title="Who got it: {e(f(sel))}">{e(n.get("selection_label", "Who got it"))} · {e(f(sel))} · {share:.0%}</div>'
                         f'<div style="flex:{1 - wsel:.3f};background:{BLUE};border-radius:0 6px 6px 0;color:#fff" title="The action itself: {e(f(m_est))}">{e(n.get("action_label", "The action"))} · {e(f(m_est))}</div></div>'
                         f'<div class="legend" style="justify-content:space-between"><span>{e(f(0, dec=0))}</span><span>Raw gap {e(f(naive))}</span></div>',
                         n.get("gap_text")))

    # forest
    order = ["aipw_gbm", "double_ml", "causal_forest", "causalpfn", "aipw_tabpfn", "aipw_spline", "regression_linear", "ipw_gbm", "regression_gbm"]
    keys = [k for k in est if k != "naive_difference" and isinstance(est[k], dict) and est[k].get("estimate") is not None and "error" not in est[k]]
    keys.sort(key=lambda k: (k != main_key, order.index(k) if k in order else 99, k))
    rows = [(k, METHODS.get(k, (k,))[0] + (" · main" if k == main_key else (" · foundation model" if METHODS.get(k, (0, 0, 0, ""))[3] == "fm" else "")),
             est[k]["estimate"], *(est[k].get("ci") or [None, None])) for k in keys]
    bounds = None
    if not main_key:
        b = (diag.get("bounds_no_instrument") or {}).get("mtr_mts") or (diag.get("instrument") or {}).get("bounds_on_average_effect")
        if b and b.get("lower") is not None:
            bounds = (b["lower"], b["upper"])
    if rows:
        has_fm = any(METHODS.get(k, (0, 0, 0, ""))[3] == "fm" for k in keys)
        title = n.get("methods_title") or (f"{len(rows)} methods side by side" if main_key else "Adjusted estimates are not the answer here")
        P.append(section(title, card(chart_forest(rows, main_key, naive, f, bounds) + forest_legend(has_fm, main_key, bounds)), n.get("methods_text")))
        present = {METHODS[k][3] for k in keys if k in METHODS}
        lg = {"classical": f'<span class="lg"><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="6" fill="{FAM["classical"]}"/></svg>Classical statistics</span>',
              "ml": f'<span class="lg"><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="6" fill="{FAM["ml"]}"/></svg>Machine learning with statistical guarantees</span>',
              "fm": f'<span class="lg"><svg width="14" height="14" aria-hidden="true"><rect x="3" y="3" width="8" height="8" transform="rotate(45 7 7)" fill="{FAM["fm"]}"/></svg>Foundation models (transformers)</span>'}
        methods_html = section("Meet the methods", card(chart_timeline(keys) + '<div class="legend">' + "".join(lg[k] for k in ("classical", "ml", "fm") if k in present)
                                                  + '<span>Year = when the idea was first published</span></div>') + family_cards(keys, main_key),
                         "These methods come from three generations of thinking about cause and effect. Older ones are simpler and more transparent; newer ones handle messier patterns. Using several side by side shows whether the answer depends on the technique.")
        P.append(methods_html if main_key else f'<details><summary>About the methods above</summary>{methods_html}</details>')

    # instrument / bounds detail (tier D)
    inst = diag.get("instrument") or {}
    if not main_key and (inst.get("complier_effect_2sls") or diag.get("bounds_no_instrument")):
        cards = []
        ce = inst.get("complier_effect_2sls")
        if ce and ce.get("estimate") is not None:
            cards.append(card(f'<h3>Effect for the units the nudge moved</h3><div class="bigrow"><span class="big" style="font-size:56px">{e(f(ce["estimate"], sign=True))}</span></div>'
                              f'<p class="small">95% range {e(f(ce["ci"][0]))} to {e(f(ce["ci"][1]))}. This is the effect only for units whose action was changed by the nudge, not for everyone.</p>'))
        bn = diag.get("bounds_no_instrument")
        if bn:
            cards.append(card(f'<h3>What we can say without more assumptions</h3>'
                              f'<p class="small">With no assumptions: between {e(f(bn["worst_case"]["lower"]))} and {e(f(bn["worst_case"]["upper"]))}.</p>'
                              f'<p class="small">If the action never hurts, and those who got it would have done at least as well anyway: between <strong>{e(f(bn["mtr_mts"]["lower"]))}</strong> and <strong>{e(f(bn["mtr_mts"]["upper"]))}</strong>.</p>'))
        if cards:
            P.append(section(n.get("bounds_title", "What the data can still tell us"), f'<div class="grid{len(cards)}">{"".join(cards)}</div>', n.get("bounds_text")))

    # segments detail
    if segs and main_key:
        seg_html = chart_segments(segs, f, labels)
        if seg_html:
            P.append(section(n.get("segment_title", "Who benefits more"), seg_html, n.get("segment_text")))

    # trust section
    tcards = []
    ov = diag.get("overlap") or {}
    if ov.get("histogram"):
        share = ov.get("share_below_0.05", 0) + ov.get("share_above_0.95", 0)
        trim = ov.get("trimmed_estimate")
        tnote = f' Leaving them out gives <strong>{e(f(trim["estimate"]))}</strong>.' if trim and main_key else ""
        tcards.append(card(f'<h3>{e(n.get("overlap_title", f"{share:.0%} had few look-alikes"))}</h3>'
                           f'<p class="small">Each unit’s estimated chance of getting the action: {e(names["treated"])} above the line, {e(names["untreated"])} below. The shaded ends are near-certain cases, where comparisons are thin.</p>'
                           + chart_overlap(ov["histogram"], (names["treated"], names["untreated"])) + f'<div class="note">{share:.1%} fall in the shaded ends.{tnote}</div>'))
    if diag.get("balance"):
        mx = diag.get("max_abs_smd_after", 0)
        tcards.append(card(f'<h3>{"After adjustment, the groups look alike" if mx <= 0.1 else "Some difference remains after adjustment"}</h3>'
                           '<p class="small">How different the groups are on each trait, before (hollow) and after (filled) the adjustment. Inside the band means well matched.</p>'
                           + chart_balance(diag["balance"], labels) + f'<div class="note">Largest remaining difference: {mx:.2f} (guideline: under 0.1).</div>'))
    sens = diag.get("sensitivity") or {}
    if sens.get("robustness_value") is not None and sens.get("benchmarks"):
        tcards.append(card('<h3>How strong would a hidden factor need to be?</h3>'
                           '<p class="small">Each bar is how strongly a recorded factor drives both the action and the outcome. A hidden factor past the dashed line could erase the effect.</p>'
                           + chart_hidden(sens, labels) + (f'<div class="note">{e(n["hidden_note"])}</div>' if n.get("hidden_note") else "")))
    checks = []
    pl = diag.get("placebo_permuted_treatment")
    if pl:
        checks.append((check_row if pl["passes"] else fail_row)("Fake action shows no effect" if pl["passes"] else "Fake action showed an effect",
                      f"Shuffling who got the action at random gave {f(pl['estimate'], sign=True)}, a range that {'includes' if pl['passes'] else 'excludes'} zero."))
    rc = diag.get("random_common_cause")
    if rc:
        checks.append(check_row("Adding a random variable changes nothing", f"The estimate moved by {f(abs(rc['change']))}."))
    subs = diag.get("subset_80pct_estimates")
    if subs:
        checks.append(check_row("Stable on random 80% subsets", f"{f(min(subs))} to {f(max(subs))}; blue line is the main result.", chart_subsets(subs, m_est, f)))
    if checks:
        tcards.append(card(f'<h3>{"Checks that passed" if all("Passed" in c for c in checks) else "Checks"}</h3>{"".join(checks)}'))
    if tcards:
        P.append(section(n.get("trust_title", f"Why the grade is {tier}"), f'<div class="grid2">{"".join(tcards)}</div>', n.get("trust_text")))

    # assumptions + trap + data issues
    left = right = ""
    if r.get("dag"):
        left = f'<div style="display:flex;flex-direction:column;gap:14px"><h2>What this rests on</h2>' + card(chart_dag(r["dag"]) + f'<div class="note">Arrows mean "affects". {e(n.get("dag_note", ""))}</div>') + "</div>"
    rparts = []
    bc = diag.get("bad_control_illustration")
    if bc and "error" not in bc and main_key:
        rparts.append(f'<h2>{e(n.get("trap_title", "The trap we avoided"))}</h2>' + card(f'<p class="small">{e(n.get("trap_text", "These columns are results of the action. Treating them as controls changes the answer:"))}</p>' + chart_bad_control(bc, f) +
                      '<div class="note">Simple regression, shown only to illustrate; the main result does not use it.</div>'))
    for iss in n.get("data_issues", []):
        rparts.append(f'<div class="issue"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="{INK}" stroke-width="2" stroke-linecap="round" aria-label="Data issue"><circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16h.01"/></svg>'
                      f'<div><div class="ctitle">{e(iss.get("title", "Data issue to check"))}</div><div class="small">{e(iss.get("text", ""))}</div></div></div>')
    if rparts:
        right = f'<div style="display:flex;flex-direction:column;gap:14px">{"".join(rparts)}</div>'
    if left or right:
        P.append(f'<section class="grid2" style="display:grid">{left}{right}</section>')

    # next steps + questions
    ns = n.get("next_steps", [])
    qs = n.get("questions", [])
    blocks = []
    pw = diag.get("power") or []
    pw_html = ""
    if pw:
        rows_pw = "".join(f'<div>{p["per_group_control"]:,} {e(unit_word)} per group to spot a lift of {e(f(p["lift"]))}</div>' for p in pw)
        pw_html = f'<div style="border-top:1px solid #3a3a37;padding-top:14px;font-size:14px;line-height:1.6;color:#d9d7cf"><div style="font-weight:600;color:#faf9f5">Sizing a randomized test (80% power)</div>{rows_pw}</div>'
    if ns or pw_html:
        blocks.append('<div class="dark"><h2>What to do next</h2>' + "".join(
            f'<div class="step"><span class="n">{i + 1}</span><div><strong>{e(s.get("title", ""))}</strong> {e(s.get("text", ""))}</div></div>' for i, s in enumerate(ns)) + pw_html + "</div>")
    if qs:
        blocks.append(card('<h2 style="font-size:30px">Questions for you</h2>' + "".join(f'<div class="q"><strong>{e(q.get("title", ""))}</strong> {e(q.get("text", ""))}</div>' for q in qs)))
    if blocks:
        P.append(f'<section class="grid{len(blocks)}" style="display:grid">{"".join(blocks)}</section>')

    # footer + table view
    man = r.get("manifest", {})
    v = man.get("versions", {})
    opt = diag.get("optional_cross_checks", {})
    fm_used = [nm for k, nm in (("causalpfn", "CausalPFN"), ("tabpfn", "TabPFN API")) if (opt.get(k) or {}).get("ran")]
    trs = "".join(f'<tr><td>{e(METHODS.get(k, (k,))[0])}{" (main)" if k == main_key else ""}</td><td>{e(f(est[k]["estimate"]))}</td>'
                  f'<td>{e(f(est[k]["ci"][0]) + " to " + f(est[k]["ci"][1])) if est[k].get("ci") else "n/a"}</td></tr>'
                  for k in (["naive_difference"] if naive is not None else []) + keys)
    P.append(f'<details><summary>All estimates as a table</summary><table><tr><th>Method</th><th>Estimate</th><th>95% range</th></tr>{trs}</table></details>')
    main_label = e(METHODS.get(main_key, (main_key,))[0]) if main_key else "None: the data can’t answer this"
    P.append(f'<footer><div><b>Data</b>Fingerprint {e(man.get("fingerprint", ""))}<br>{r.get("rows_used", 0):,} rows used, {r.get("rows_dropped_missing", 0):,} dropped</div>'
             f'<div><b>Main method</b>{main_label}</div>'
             f'<div><b>Run</b>Seed {e(man.get("seed", ""))} · {e(man.get("budget", ""))} budget<br>{man.get("runtime_sec", 0):.0f} seconds</div>'
             f'<div><b>Packages</b>{e(" · ".join(f"{k} {val}" for k, val in v.items() if k in ("sklearn", "statsmodels", "econml", "dowhy")))}{("<br>" + e(" · ".join(fm_used))) if fm_used else ""}</div></footer>')

    fonts = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500;6..72,600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">')
    return (f'<!doctype html><html lang="{e(n.get("lang", "en"))}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(n.get("page_title", n.get("title", "Causal analysis")))}</title>{fonts}<style>{CSS}</style></head>'
            f'<body><main class="page">{"".join(P)}</main></body></html>')


def main(results_path, narrative_path, out_path):
    r = json.loads(Path(results_path).read_text())
    n = json.loads(Path(narrative_path).read_text()) if narrative_path else {}
    Path(out_path).write_text(render(r, n))
    print(f"wrote {out_path}")
