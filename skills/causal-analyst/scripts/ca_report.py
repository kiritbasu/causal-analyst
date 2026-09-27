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
    "double_ml": ("Double ML (overlap-weighted)", 2018, "2018", "ml", "Strips out what the traits already predict, then compares what's left. Its average leans towards units that could have gone either way.", "Chernozhukov et al., 2018"),
    "causal_forest": ("Causal forest", 2018, "2018", "ml", "Thousands of decision trees that look for who benefits most.", "Wager & Athey, 2018"),
    "causalpfn": ("CausalPFN", 2025, "2025", "fm", "Built for cause and effect: reads the data and estimates the effect in one pass.", "Balazadeh et al., 2025"),
    "aipw_tabpfn": ("Doubly robust, TabPFN", 2023, "2023", "fm", "A general prediction model used as the engine inside the doubly robust recipe (hosted by Prior Labs).", "Hollmann et al., 2023; v2 2025"),
    "gcomp_linear": ("G-computation, straight line", 1986, "1986", "classical", "Predicts the outcome at each amount assuming a straight-line relationship.", "Robins, 1986"),
    "gcomp_spline5": ("G-computation, smooth curve (5 knots)", 1986, "1986", "ml", "Predicts the outcome at each amount with a flexible curve.", "Robins, 1986"),
    "gcomp_spline8": ("G-computation, smooth curve (8 knots)", 1986, "1986", "ml", "Predicts the outcome at each amount with a flexible curve.", "Robins, 1986"),
    "gcomp_spline12": ("G-computation, smooth curve (12 knots)", 1986, "1986", "ml", "Predicts the outcome at each amount with a flexible curve.", "Robins, 1986"),
    "front_door": ("Front-door (through the middle step)", 1995, "1995", "classical", "Traces the effect through a middle step the action fully works through, sidestepping hidden drivers of the outcome.", "Pearl, 1995"),
    "gcomp_gbm": ("G-computation, boosted trees", 1986, "1986", "ml", "Predicts the outcome at each amount with gradient-boosted trees.", "Robins, 1986"),
}
def _safe_html(s):
    """Escape everything, then re-allow only <strong>, <em> and <br>."""
    t = e(str(s))
    for tag in ("strong", "em"):
        t = t.replace(f"&lt;{tag}&gt;", f"<{tag}>").replace(f"&lt;/{tag}&gt;", f"</{tag}>")
    return t.replace("&lt;br&gt;", "<br>").replace("&lt;br/&gt;", "<br>")


# The report is a static page: no scripts, no outside requests except the fonts.
CSP_META = ('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            'style-src \'unsafe-inline\' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src data:">')


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
    anchor, tx = ("end", X(rv) - 6) if X(rv) > 360 else ("start", X(rv) + 6)
    out.append(f'<text x="{tx:.1f}" y="{ay - 8}" font-size="13" fill="{INK}" text-anchor="{anchor}">Needed to erase: {rv:.2f}</text>')
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


def _clip(a, b, gap=3):
    """Segment between the borders of boxes a and b (x, y, w, h)."""
    ax, ay = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx, by = b[0] + b[2] / 2, b[1] + b[3] / 2
    dx, dy = bx - ax, by - ay
    def t(box):
        tx = (box[2] / 2) / abs(dx) if dx else 9e9
        ty = (box[3] / 2) / abs(dy) if dy else 9e9
        return min(tx, ty)
    L = math.hypot(dx, dy) or 1
    ta, tb = t(a) + gap / L, t(b) + gap / L
    return ax + dx * ta, ay + dy * ta, bx - dx * tb, by - dy * tb


EDGE_STYLE = {"assumed": ('#6b6964', '1.3', '', 'ah'), "effect": (INK, '2.4', '', 'ahb'),
              "hidden": ('#b5542c', '1.4', ' stroke-dasharray="5 4"', 'ahr'),
              "after": ('#8a8883', '1.5', ' stroke-dasharray="2 4"', 'ah'),
              "sme": ('#4a3aa7', '1.6', '', 'ahp'),
              "knowledge": ('#4a3aa7', '1.5', ' stroke-dasharray="6 4"', 'ahp'),
              "suspected": ('#b5542c', '1.4', ' stroke-dasharray="2 4"', 'ahr')}


def chart_dag(dag, W=960):
    """Layered diagram: recorded controls on top, action -> outcome in the middle, things that
    happen after the action and unrecorded factors below. Draws every node and every edge."""
    nodes = {n["id"]: n for n in dag["nodes"]}
    T, Y = dag["treatment"], dag["outcome"]
    ctrl = [n for n in dag["nodes"] if n["role"] in ("control", "other")]
    group = {}
    if len(ctrl) > 7:
        for c in ctrl:
            group[c["id"]] = "__g"
        ctrl = [{"id": "__g", "label": f"{len(ctrl)} recorded traits", "role": "control"}]
    nudges = [n for n in dag["nodes"] if n["role"] == "nudge (instrument)"]
    hidden = [n for n in dag["nodes"] if n["role"] == "hidden"]
    meds = [n for n in dag["nodes"] if n["role"] == "middle step"]
    placed = {c["id"] for c in ctrl} | {x["id"] for x in nudges + hidden + meds} | {T, Y} | set(group)
    below = [n for n in dag["nodes"] if n["id"] not in placed]
    pos, lab = {}, {}
    # row 0: controls
    k = max(len(ctrl), 1)
    cw = min(170, (W - 12 * (k - 1)) / k)
    x = (W - (k * cw + (k - 1) * 12)) / 2
    for c in ctrl:
        pos[c["id"]] = (x, 8, cw, 46); lab[c["id"]] = c["label"]; x += cw + 12
    # row 1: nudge, action, outcome
    nw = 150 if nudges else 0
    tw = 220
    pos[T] = (16 + (nw + 40 if nudges else 0), 150, tw, 54)
    pos[Y] = (W - 16 - tw, 150, tw, 54)
    for i, z in enumerate(nudges[:2]):
        pos[z["id"]] = (8, 150 + i * 62 - (31 if len(nudges) > 1 else 0) + (4 if len(nudges) == 1 else 0), nw, 46)
    y2 = 270
    if meds:
        mx0 = pos[T][0] + tw + 30
        mx1 = pos[Y][0] - 30
        mw = min(170, (mx1 - mx0 - 12 * (len(meds) - 1)) / len(meds))
        x = (mx0 + mx1 - (len(meds) * mw + (len(meds) - 1) * 12)) / 2
        for m in meds:
            pos[m["id"]] = (x, 232, mw, 46); x += mw + 12
        y2 = 330
    # row 2: things after the action (and any other role), row 3: unrecorded factors
    if below:
        bw = min(180, (W - 40 - 14 * (len(below) - 1)) / len(below))
        span = len(below) * bw + (len(below) - 1) * 14
        x = max(20, min((W - span) / 2, W - 20 - span))
        for b in below:
            pos[b["id"]] = (x, y2, bw, 46); x += bw + 14
        y2 += 90
    for i, h in enumerate(hidden[:2]):
        pos[h["id"]] = (W / 2 - 150 + (i - (len(hidden[:2]) - 1) / 2) * 320, y2, 300, 46)
    if hidden:
        y2 += 60
    H = max(y2 - 30, 220) + 16 if (below or hidden) else 224
    out = [f'<svg width="100%" viewBox="0 0 {W} {H:.0f}" role="img" aria-label="Causal diagram of the assumptions">',
           '<defs>' + "".join(f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{col}"/></marker>'
                              for mid, col in (("ah", "#6b6964"), ("ahb", INK), ("ahr", "#b5542c"), ("ahp", "#4a3aa7"))) + '</defs>']
    seen = set()
    for ed in dag["edges"]:
        a, b = group.get(ed["from"], ed["from"]), group.get(ed["to"], ed["to"])
        if a not in pos or b not in pos or a == b or (a, b) in seen:
            continue
        seen.add((a, b))
        kind = "effect" if (a, b) == (T, Y) else ed.get("kind", "assumed")
        col, sw, dash, mk = EDGE_STYLE.get(kind, EDGE_STYLE["assumed"])
        x1, y1, x2, y2_ = _clip(pos[a], pos[b])
        out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2_:.1f}" stroke="{col}" stroke-width="{sw}"{dash} marker-end="url(#{mk})"/>')
    def box(i, fill, stroke, tcol, size=13, weight="400", dash=""):
        x_, y_, w_, h_ = pos[i]
        label = lab.get(i) or nodes[i]["label"]
        return (f'<rect x="{x_:.1f}" y="{y_:.1f}" width="{w_:.1f}" height="{h_}" rx="9" fill="{fill}" stroke="{stroke}"{dash}/>'
                + _box_text(x_ + w_ / 2, y_ + h_ / 2, label, max(8, int(w_ / (size * 0.55))), size, tcol, weight))
    for c in ctrl:
        out.append(box(c["id"], "#f4f3ee", BASE, INK))
    for z in nudges[:2]:
        out.append(box(z["id"], "#efedf8", "#b9b1e0", INK, 12))
    for m in meds:
        out.append(box(m["id"], "#efedf8", "#b9b1e0", INK, 12.5))
    for b in below:
        out.append(box(b["id"], "#f0efec", "#b5b3ab", INK3, 12.5))
    for h in hidden[:2]:
        out.append(box(h["id"], "#ffffff", "#b5542c", "#b5542c", 12, dash=' stroke-dasharray="4 3"'))
    out.append(box(T, BLUE, BLUE, "#ffffff", 14, "600"))
    out.append(box(Y, "#1d6b43", "#1d6b43", "#ffffff", 14, "600"))
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
              "nudge": ("#e7e3f6", "#4a3aa7"), "middle step": ("#e7e3f6", "#4a3aa7"), "check": ("#fdf0d5", "#9a6a00"), "left out": ("#fbe6dc", ORANGE), "not used": ("#f4f3ee", "#b5b3ab")}


def _cell(v):
    """A raw value in the sample-rows table: exact, never abbreviated (IDs stay IDs)."""
    if v is None:
        return ""
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        s = f"{v:.4f}".rstrip("0").rstrip(".") if abs(v) < 1e4 else f"{v:.2f}"
        return s if s not in ("0", "-0") else f"{v:.3g}"   # keep tiny values visible
    return str(v)


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
        if c.get("meaning"):
            tag = "" if c.get("confirmed") else (' <span class="assumed">assumed from general knowledge</span>' if "general" in str(c.get("source", "")).lower() else ' <span class="assumed">assumed</span>')
            rec = f' · {e(c["recorded"])}' if c.get("recorded") and c["recorded"] not in ("the action", "the outcome", "unknown") else ""
            sub += f'<div class="meaning">{e(c["meaning"])}{rec}{tag}</div>'
        if c["n_unique"] == ov["rows"] and c["kind"] in ("number", "text/id") and c["role"] in ("left out", "not used"):
            viz, summ = "", f'unique for every row ({c["n_unique"]:,} values)'
        elif c["summary"] == "numeric":
            viz = mini_hist(c["histogram"]["counts"])
            summ = f'{_num(c["min"])} to {_num(c["max"])} · average {_num(c["mean"])}'
        else:
            viz = mini_cats(c["top"], c["other"], ov["rows"])
            summ = ", ".join(f'{e(t["value"])} ({t["count"] / ov["rows"]:.0%})' for t in c["top"][:3]) + (" …" if c["n_unique"] > 3 else "")
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
        body = "".join("<tr>" + "".join(f'<td>{e(_cell(v))}</td>' for v in r.values()) + "</tr>" for r in ov["sample_rows"])
        sample = (f'<details><summary>First {len(ov["sample_rows"])} rows of the file</summary>'
                  f'<div class="tscroll"><table class="sample"><tr>{head}</tr>{body}</table></div></details>')
    return tile_html, table, sample


def dag_in_words(dag, labels):
    nodes = {x["id"]: x for x in dag["nodes"]}
    L = lambda i: labels.get(i, nodes[i]["label"]) if i in nodes else i
    T, Y = dag["treatment"], dag["outcome"]
    ctrl = [x["id"] for x in dag["nodes"] if x["role"] == "control"]
    items = []
    if ctrl:
        items.append(("Compared like with like", f'{", ".join(L(c) for c in ctrl)} affect both {L(T)} and {L(Y)}, so the analysis compares cases that look alike on these.'))
    items.append(("The effect we measure", f'{L(T)} → {L(Y)}.'))
    for x in dag["nodes"]:
        if x["role"] == "nudge (instrument)":
            items.append(("A random nudge", f'{L(x["id"])} shifts {L(T)} but affects {L(Y)} only through it.'))
        if x["role"] == "middle step":
            items.append(("A middle step", f'The effect of {L(T)} flows through {L(x["id"])}.'))
        if x["role"] == "after the action":
            items.append(("Left out on purpose", f'{L(x["id"])} happens after {L(T)}, so controlling for it would hide or distort the effect.'))
        if x["role"] == "check: can't be affected":
            items.append(("A check", f'{L(T)} cannot plausibly change {L(x["id"])}, so any apparent effect on it measures hidden bias.'))
        if x["role"] == "hidden" and x.get("suspected"):
            items.append(("Suspected, not in the data", f'{x["label"].replace("Suspected, not in data: ", "")} may affect both {L(T)} and {L(Y)}. This comes from general knowledge of this kind of data, not from you; the checks below size it.'))
        elif x["role"] == "hidden":
            items.append(("Not in the data", f'{x["label"].replace("Not in data: ", "")} affects both {L(T)} and {L(Y)}. Nothing recorded can stand in for it, which limits what the data can answer.'))
    for ed in dag["edges"]:
        if ed["kind"] == "sme":
            items.append(("Added arrow", f'{L(ed["from"])} affects {L(ed["to"])}' + (" (you told us)." if ed.get("source") in ("sme", None) else f' ({ed["source"]}).')))
        if ed["kind"] == "knowledge":
            items.append(("Added from general knowledge", f'{L(ed["from"])} affects {L(ed["to"])}. Not confirmed by you.'))
    return "".join(f'<div class="mrow"><strong>{e(t)}.</strong> <span>{e(d)}</span></div>' for t, d in items)


def dag_legend(dag):
    kinds = {x["kind"] for x in dag["edges"]}
    it = [f'<span class="lg"><svg width="26" height="10" aria-hidden="true"><line x1="0" y1="5" x2="26" y2="5" stroke="#6b6964" stroke-width="2"/></svg>affects</span>']
    if "hidden" in kinds:
        it.append('<span class="lg"><svg width="26" height="10" aria-hidden="true"><line x1="0" y1="5" x2="26" y2="5" stroke="#b5542c" stroke-width="2" stroke-dasharray="5 4"/></svg>not in the data</span>')
    if "after" in kinds:
        it.append('<span class="lg"><svg width="26" height="10" aria-hidden="true"><line x1="0" y1="5" x2="26" y2="5" stroke="#8a8883" stroke-width="2" stroke-dasharray="2 4"/></svg>happens after the action: not controlled for</span>')
    if "knowledge" in kinds:
        it.append('<span class="lg"><svg width="26" height="10" aria-hidden="true"><line x1="0" y1="5" x2="26" y2="5" stroke="#4a3aa7" stroke-width="2" stroke-dasharray="6 4"/></svg>from general knowledge, not confirmed</span>')
    if "suspected" in kinds:
        it.append('<span class="lg"><svg width="26" height="10" aria-hidden="true"><line x1="0" y1="5" x2="26" y2="5" stroke="#b5542c" stroke-width="2" stroke-dasharray="2 4"/></svg>suspected from general knowledge, not in the data</span>')
    if "sme" in kinds:
        it.append('<span class="lg"><svg width="26" height="10" aria-hidden="true"><line x1="0" y1="5" x2="26" y2="5" stroke="#4a3aa7" stroke-width="2"/></svg>added from what you told us</span>')
    return f'<div class="legend">{"".join(it)}</div>'


def assumption_rows(r, n, diag):
    rows = n.get("assumptions")
    if not rows:
        rows = []
        for a in (r.get("identification") or {}).get("assumptions", []):
            low = a.lower()
            if "overlap" in low:
                ov = diag.get("overlap") or {}
                sh = ov.get("share_below_0.05", 0) + ov.get("share_above_0.95", 0)
                st = ("Checked: weak for " + f"{sh:.0%}" if sh > 0.05 else "Checked: good") if ov else "Not checked"
            elif "unrecorded" in low or "cannot be checked" in low:
                st = "Can't be checked; sized above"
            elif "measured before" in low:
                cbk = (r.get("spec") or {}).get("codebook") or {}
                used = (r.get("spec") or {}).get("confounders", [])
                st = ("Confirmed by you" if n.get("dag_confirmed") else
                      "Confirmed in the column sheet" if used and all((cbk.get(c) or {}).get("confirmed") for c in used) else "Assumed")
            else:
                st = "Assumed"
            rows.append({"text": a.split(" (")[0], "status": st})
    return "".join(f'<tr><td>{e(x["text"])}</td><td>{e(x["status"])}</td></tr>' for x in rows)


def chart_alternatives(alt, main, main_key, f, labels):
    """Dot plot: main estimate with its range as a band, then each alternative diagram."""
    rows = []
    for a in alt.get("user", []):
        if a.get("estimate") is not None:
            rows.append(("Your alternatives", a["name"], a.get("why", ""), a["estimate"], a.get("ci"), bool(a.get("illustrative"))))
    for a in alt.get("add_one", []):
        rows.append(("Also controlling for a left-out column", labels.get(a["column"], a["column"]), f'left out because: {a.get("left_out_because", "")}', a["estimate"], a.get("ci"), False))
    for a in alt.get("leave_one_out", []):
        rows.append(("Dropping one control", "without " + labels.get(a["column"], a["column"]), "", a["estimate"], a.get("ci"), False))
    if not rows:
        return ""
    lo, hi = main["ci"]
    vals = [0.0, lo, hi, main["estimate"]] + [v for r_ in rows for v in (r_[3], *(r_[4] or []))]
    d0, d1 = min(vals), max(vals)
    pad = (d1 - d0) * 0.06 or 1
    ticks = nice_ticks(d0 - pad, d1 + pad, 7)
    X = scale(min(ticks[0], d0 - pad), max(ticks[-1], d1 + pad), 380, 1090)
    groups, y = [], 30
    out = []
    band_top = 20
    last_g = None
    for g, name, why, est_, ci, illus in rows:
        if g != last_g:
            y += 14
            out.append(f'<text x="12" y="{y + 4}" font-size="12" letter-spacing="0.06em" fill="{MUTED}">{e(g.upper())}</text>')
            y += 26
            last_g = g
        out.append(f'<text x="24" y="{y + 5}" font-size="14" fill="{INK}">{e(name if len(name) <= 44 else name[:43] + "…")}</text>')
        if ci:
            out.append(f'<line x1="{X(ci[0]):.1f}" y1="{y}" x2="{X(ci[1]):.1f}" y2="{y}" stroke="#8a8883" stroke-width="2" stroke-linecap="round"/>')
        outside = not (lo <= est_ <= hi)
        col = ORANGE if outside else GREY
        dot = f'fill="{CARD}" stroke="{col}" stroke-width="2.2"' if illus else f'fill="{col}" stroke="{CARD}" stroke-width="2"'
        out.append(f'<circle cx="{X(est_):.1f}" cy="{y}" r="5.5" {dot}><title>{e(name)}: {e(f(est_))}{(" — " + e(why)) if why else ""}</title></circle>')
        out.append(f'<text x="{max(X(est_), X(ci[1]) if ci else X(est_)) + 12:.1f}" y="{y + 5}" font-size="13" fill="{INK if outside else MUTED}" font-weight="{600 if outside else 400}">{e(f(est_))}</text>')
        y += 32
    H = y + 40
    head = [f'<svg width="100%" viewBox="0 0 1136 {H}" role="img" aria-label="Estimate under alternative diagrams">',
            f'<rect x="{X(lo):.1f}" y="{band_top}" width="{X(hi) - X(lo):.1f}" height="{y - band_top}" fill="rgba(42,120,214,0.10)"/>',
            f'<line x1="{X(main["estimate"]):.1f}" y1="{band_top}" x2="{X(main["estimate"]):.1f}" y2="{y}" stroke="{BLUE}" stroke-width="2"/>',
            f'<text x="{X(main["estimate"]):.1f}" y="{band_top - 6}" font-size="12" font-weight="600" fill="{INK}" text-anchor="middle">Main result {e(f(main["estimate"]))}</text>']
    for t in ticks:
        head.append(f'<text x="{X(t):.1f}" y="{y + 22}" font-size="12" fill="{MUTED}" text-anchor="middle">{e(f(t, dec=tick_dec([tt * f.k for tt in ticks])))}</text>')
        head.append(f'<line x1="{X(t):.1f}" y1="{band_top}" x2="{X(t):.1f}" y2="{y}" stroke="{"#c3c2b7" if t == 0 else "#ecebe5"}"/>')
    return "".join(head + out) + "</svg>"


def structure_findings(sc, labels):
    fs = sc.get("findings") or []
    if not fs:
        return '<p class="small">The data raised no questions about the diagram.</p>'
    icon = {"possible consequence": "⚠", "linked to both": "?", "no linear link": "·", "timing conflict": "·", "action only": "·"}
    items = []
    for x in fs:
        txt = x["text"].replace(x["column"], labels.get(x["column"], x["column"]), 1)
        items.append(f'<div class="check"><span class="qi">{icon.get(x["kind"], "?")}</span><div class="small">{e(txt)}</div></div>')
    return "".join(items)


def chart_sim(sim, f):
    runs = sim["runs"]
    vals = [sim["planted"], sim["naive_mean"]] + [v for r_ in runs for v in r_["ci"]]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.1 or 1
    X = scale(lo - pad, hi + pad, 150, 500)
    H = 40 + 28 * len(runs) + 50
    out = [f'<svg width="100%" viewBox="0 0 520 {H}" role="img" aria-label="Recovering a planted effect">',
           f'<line x1="{X(sim["planted"]):.1f}" y1="14" x2="{X(sim["planted"]):.1f}" y2="{H - 34}" stroke="{GOODTXT}" stroke-width="2" stroke-dasharray="5 4"/>',
           f'<text x="{X(sim["planted"]):.1f}" y="10" font-size="12" fill="{INK}" text-anchor="middle">planted {e(f(sim["planted"]))}</text>']
    for i, r_ in enumerate(runs):
        y = 36 + 28 * i
        out.append(f'<text x="0" y="{y + 5}" font-size="13" fill="{INK2}">Simulation {i + 1}</text>')
        out.append(f'<line x1="{X(r_["ci"][0]):.1f}" y1="{y}" x2="{X(r_["ci"][1]):.1f}" y2="{y}" stroke="{BLUE}" stroke-width="2" stroke-linecap="round"/>')
        out.append(f'<circle cx="{X(r_["estimate"]):.1f}" cy="{y}" r="5.5" fill="{BLUE}" stroke="{CARD}" stroke-width="2"><title>{e(f(r_["estimate"]))}</title></circle>')
    y = 36 + 28 * len(runs)
    out.append(f'<text x="0" y="{y + 5}" font-size="13" fill="{INK2}">Raw gap</text><circle cx="{X(sim["naive_mean"]):.1f}" cy="{y}" r="5" fill="{ORANGE}"><title>{e(f(sim["naive_mean"]))}</title></circle>')
    out.append(f'<text x="{X(sim["naive_mean"]) + 10:.1f}" y="{y + 5}" font-size="12" fill="{MUTED}">{e(f(sim["naive_mean"]))}</text></svg>')
    return "".join(out)


def chart_negctl(ncs, main_rel, main_ci_rel, labels):
    """Relative 'effect' (% of the untreated average) on the main outcome and on outcomes the action can't change."""
    rows = []
    if main_rel is not None:
        rows.append(("The outcome we care about", main_rel, main_ci_rel, True))
    for x in ncs:
        if x.get("relative") is None or "estimate" not in x:
            continue
        b = x["untreated_mean"] or 1
        rows.append((labels.get(x["column"], x["column"]), x["relative"], [c / b for c in x["ci"]], False))
    if not rows:
        return ""
    vals = [0.0] + [v for _, m, ci, _ in rows for v in (m, *(ci or []))]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.12 or 0.05
    X = scale(lo - pad, hi + pad, 230, 500)
    H = 30 + 40 * len(rows) + 30
    out = [f'<svg width="100%" viewBox="0 0 520 {H}" role="img" aria-label="Effect on outcomes the action cannot change">',
           f'<line x1="{X(0):.1f}" y1="10" x2="{X(0):.1f}" y2="{H - 26}" stroke="{BASE}"/>',
           f'<text x="{X(0):.1f}" y="{H - 8}" font-size="12" fill="{MUTED}" text-anchor="middle">no effect</text>']
    for i, (name, m, ci, is_main) in enumerate(rows):
        y = 30 + 40 * i
        bad = (not is_main) and ci and not (ci[0] <= 0 <= ci[1])
        col = BLUE if is_main else (CRIT if bad else GREY)
        out.append(f'<text x="0" y="{y + 5}" font-size="13" font-weight="{600 if is_main else 400}" fill="{INK}">{e(name if len(name) <= 30 else name[:29] + "…")}</text>')
        if ci:
            out.append(f'<line x1="{X(ci[0]):.1f}" y1="{y}" x2="{X(ci[1]):.1f}" y2="{y}" stroke="{col}" stroke-width="2" stroke-linecap="round"/>')
        out.append(f'<circle cx="{X(m):.1f}" cy="{y}" r="5.5" fill="{col}" stroke="{CARD}" stroke-width="2"><title>{m:+.0%}</title></circle>')
        tx = X(max(m, ci[1] if ci else m)) + 10
        out.append(f'<text x="{tx:.1f}" y="{y + 5}" font-size="12" font-weight="{600 if bad else 400}" fill="{CRIT if bad else MUTED}">{m:+.0%}</text>')
    out.append("</svg>")
    return "".join(out)


def chart_plausibility(pz, main, f):
    lo, hi, est = pz["low"], pz["high"], pz["estimate"]
    ci = main.get("ci") or [est, est]
    vals = [0.0, lo, hi, est, *ci]
    a, b = min(vals), max(vals)
    pad = (b - a) * 0.12 or 1
    X = scale(a - pad, b + pad, 20, 500)
    out = [f'<svg width="100%" viewBox="0 0 520 120" role="img" aria-label="Our estimate against the range expected before the run">',
           f'<rect x="{X(lo):.1f}" y="18" width="{max(X(hi) - X(lo), 2):.1f}" height="64" fill="rgba(29,107,67,0.14)"/>',
           f'<text x="{(X(lo) + X(hi)) / 2:.1f}" y="12" font-size="12" fill="#1d6b43" text-anchor="middle">expected before the run</text>',
           f'<line x1="{X(0):.1f}" y1="18" x2="{X(0):.1f}" y2="82" stroke="{BASE}"/>',
           f'<line x1="{X(ci[0]):.1f}" y1="50" x2="{X(ci[1]):.1f}" y2="50" stroke="{BLUE}" stroke-width="2.5" stroke-linecap="round"/>',
           f'<circle cx="{X(est):.1f}" cy="50" r="6.5" fill="{BLUE}" stroke="{CARD}" stroke-width="2"/>',
           f'<text x="{X(est):.1f}" y="36" font-size="12.5" font-weight="600" fill="{INK}" text-anchor="middle">ours {e(f(est, sign=True))}</text>']
    for v in (lo, hi):
        out.append(f'<text x="{X(v):.1f}" y="100" font-size="12" fill="{MUTED}" text-anchor="middle">{e(f(v, sign=True))}</text>')
    out.append("</svg>")
    return "".join(out)


SOURCE_CHIP = {"sme": ("you told us", "#dcefe4", "#1d6b43"), "brief": ("from your brief", "#dcefe4", "#1d6b43"),
               "data": ("the data suggests", "#dbe8f8", "#2a78d6"),
               "general knowledge": ("general knowledge, not confirmed", "#efedf8", "#4a3aa7")}


def source_chip(src):
    key = str(src or "").lower()
    key = "general knowledge" if "general" in key or "literature" in key or "published" in key else key
    label, bg, fg = SOURCE_CHIP.get(key, (src or "", "#f4f3ee", GREY))
    return f'<span class="chip" style="background:{bg}"><i style="background:{fg}"></i>{e(label)}</span>' if label else ""


def domain_section(dn, spec, diag, labels):
    """What domain knowledge said before the run, and what was done about each point."""
    rows = []
    for t in dn.get("known_traps", []):
        if isinstance(t, str):
            t = {"name": t}
        rows.append(f'<div class="mrow"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><strong>{e(t.get("name", ""))}</strong>{source_chip(t.get("source", "general knowledge"))}</div>'
                    f'<span>{e(t.get("why", ""))}</span>' + (f'<div class="small" style="margin-top:4px"><b>What we did:</b> {e(t["handled"])}</div>' if t.get("handled") else "") + '</div>')
    for sh in spec.get("suspected_hidden", []):
        if isinstance(sh, str):
            sh = {"label": sh}
        px = ", ".join(labels.get(p, p) for p in sh.get("proxies", []))
        rows.append(f'<div class="mrow"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><strong>Suspected, not in the data: {e(sh.get("label", ""))}</strong>{source_chip(sh.get("source", "general knowledge"))}</div>'
                    f'<span>{e(sh.get("why", ""))}</span>' + (f'<div class="small" style="margin-top:4px"><b>Partial stand-in used as a control:</b> {e(px)}</div>' if px else "") + '</div>')
    for nc in spec.get("negative_control_outcomes", []):
        col = nc["column"] if isinstance(nc, dict) else nc
        why = nc.get("why", "") if isinstance(nc, dict) else ""
        rows.append(f'<div class="mrow"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><strong>Check against {e(labels.get(col, col))}</strong>{source_chip("general knowledge")}</div><span>{e(why or "The action cannot plausibly change this, so any apparent effect on it measures hidden bias.")}</span></div>')
    ee = spec.get("expected_effect")
    if ee:
        rows.append(f'<div class="mrow"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap"><strong>What to expect</strong>{source_chip(ee.get("source", "general knowledge"))}</div><span>{e(ee.get("basis", ""))}</span></div>')
    return "".join(rows)


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
.check{{display:flex;gap:14px;align-items:flex-start}} .qi{{flex:none;width:22px;height:22px;border-radius:50%;background:#f4f3ee;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:600}}
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
.dagwrap{{display:grid;grid-template-columns:minmax(0,1fr);gap:20px}}
table.assume td{{font-size:14px;vertical-align:top}}
table.cols td{{vertical-align:middle;font-size:14px}} .cn{{font-weight:600}} .raw{{font-size:12px;color:{MUTED};font-family:ui-monospace,Menlo,monospace}}
.meaning{{font-size:12.5px;color:{INK2};margin-top:2px;max-width:280px}} .assumed{{font-size:11px;background:#fbe6dc;border-radius:999px;padding:1px 7px;color:{INK}}}
.sm{{color:{INK2};font-size:13px;max-width:320px}} .why{{font-size:12px;color:{MUTED};margin-top:2px}}
.chip{{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:3px 10px;font-size:12px;color:{INK};white-space:nowrap}} .chip i{{width:8px;height:8px;border-radius:50%;display:inline-block}}
table.sample td,table.sample th{{font-size:13px;white-space:nowrap}}
details{{font-size:14px}} summary{{cursor:pointer;color:{INK3}}}
table{{border-collapse:collapse;width:100%;margin-top:10px;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:6px 10px;border-bottom:1px solid #ecebe5}} th{{color:{MUTED};font-weight:500}}
svg text{{font-family:"IBM Plex Sans",system-ui,sans-serif}}
@media (max-width:900px){{.dagwrap{{grid-template-columns:minmax(0,1fr)}} .page{{padding:32px 16px}} .tiles{{grid-template-columns:repeat(2,minmax(0,1fr))}} .grid2,.grid3,footer{{grid-template-columns:minmax(0,1fr)}} h1{{font-size:38px}} .big{{font-size:60px}}}}
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
             f'<h1>{e(n.get("title", "What is the effect?"))}</h1><p class="lede">{_safe_html(n.get("answer_html")) if n.get("answer_html") else e(n.get("answer", ""))}</p></header>')

    # hero cards
    hero = []
    if main_key and main.get("estimate") is not None:
        lo, hi = (main.get("ci") or [None, None])
        hero.append(card(f'<div class="eyebrow">{e(n.get("effect_label", "Effect"))}</div>'
                         f'<div class="bigrow"><span class="big">{e(f(main["estimate"], sign=True, dec=n.get("hero_decimals", sig_dec(main["estimate"] * f.k))))}</span><span class="unit">{e(n.get("unit", ""))}</span></div>'
                         + chart_hero_range(main["estimate"], lo, hi, f) +
                         f'<div class="note">95% likely range {e(f(lo))} to {e(f(hi))}'
                         + (f'; about {abs(rel):.0%} {"above" if rel > 0 else "below"} the untreated average' if (rel := (diag.get("derived") or {}).get("effect_relative_to_untreated")) is not None and abs(rel) < 5 else "") + '</div>'))
    else:
        b = (diag.get("bounds_no_instrument") or {}).get("mtr_mts") or (diag.get("instrument") or {}).get("bounds_on_average_effect")
        body = f'<div class="eyebrow">{e(n.get("effect_label", "Effect"))}</div><div class="bigrow"><span class="big" style="font-size:56px">We can’t tell</span></div>'
        if b and b.get("lower") is not None:
            body += f'<div class="small">Only a range can be given: <strong>{e(f(b["lower"]))}</strong> to <strong>{e(f(b["upper"]))}</strong>, and only if the assumptions below hold.</div>'
        hero.append(card(body))
    bullets = n.get("caution_bullets") or []
    blist = f'<ul class="small">{"".join(f"<li>{e(x)}</li>" for x in bullets)}</ul>' if bullets else ""
    hero.append(card(f'<div class="eyebrow">How much to trust it</div>{grade_scale(tier)}<div class="tierword">{WARN_ICON if tier in "CD" else ""}{TIER_WORD[tier]}</div>{blist}'))
    segs = diag.get("segments") or []
    seg_ok = len(segs) >= 3 and "error" not in segs[0] and main_key
    groups = [x for x in segs if "estimate" in x and not str(x.get("segment", "")).startswith("difference")]
    diffs = [(i, x) for i, x in enumerate(segs) if str(x.get("segment", "")).startswith("difference") and x.get("ci")]
    # 'real' only after allowing for the number of groups compared (simultaneous intervals)
    real = [(i, x) for i, x in diffs if (x.get("ci_adjusted") or x["ci"])[0] > 0 or (x.get("ci_adjusted") or x["ci"])[1] < 0]
    if seg_ok and real:
        i_, _ = max(real, key=lambda ix: abs(ix[1]["estimate"]))
        pair = sorted([segs[i_ - 2], segs[i_ - 1]], key=lambda x: -abs(x["estimate"]))
    elif seg_ok and diffs:
        lo_s, hi_s = min(x["estimate"] for x in groups), max(x["estimate"] for x in groups)
        hero.append(card(f'<div class="eyebrow">{e(n.get("segment_card_title", "Who gains most"))}</div>'
                         f'<div class="bigrow"><span style="font-family:{SERIF};font-size:40px;line-height:1.1">About the same for everyone</span></div>'
                         f'<p class="small">In every group we checked, the effect was between {e(f(lo_s, sign=True))} and {e(f(hi_s, sign=True))}. None of the gaps between groups is bigger than chance.</p>'
                         f'<div class="note">{e(n.get("segment_card_note_similar", ""))}</div>'))
        pair = None
    else:
        pair = segs[:2]
    if seg_ok and pair:
        a, b = pair
        hero.append(card(f'<div class="eyebrow">{e(n.get("segment_card_title", "Who gains most"))}</div>'
                         f'<div class="bigrow"><span class="big">{e(f(a["estimate"], sign=True, dec=n.get("hero_decimals", sig_dec(a["estimate"] * f.k))))}</span><span class="unit">{e(labels.get(a["segment"], a["segment"]))}</span></div>'
                         f'<div class="bigrow"><span style="font-family:{SERIF};font-size:34px">{e(f(b["estimate"], sign=True, dec=n.get("hero_decimals", sig_dec(b["estimate"] * f.k))))}</span><span class="unit">{e(labels.get(b["segment"], b["segment"]))}</span></div>'
                         f'<div class="note">{e(n.get("segment_card_note", ""))}</div>'))
    elif not seg_ok and n.get("third_card"):
        hero.append(card(f'<div class="eyebrow">{e(n["third_card"].get("title", ""))}</div><p class="small">{e(n["third_card"].get("text", ""))}</p>'))
    P.append(f'<section class="grid{len(hero)}" style="display:grid">{"".join(hero)}</section>')

    # the data
    ov = r.get("data_overview")
    if ov:
        tiles, table, sample = data_section(ov, labels, names, unit_word, n)
        P.append(section(n.get("data_title", "The data"), f'<div class="tiles">{tiles}</div>' + card(table + sample),
                         n.get("data_text") or f'What the analysis worked from: one row per {unit_word.rstrip("s")}, and the role each column played.'))

    # the causal diagram
    if r.get("dag"):
        confirmed = n.get("dag_confirmed")
        chip = (f'<span class="chip" style="background:#dcefe4"><i style="background:#1d6b43"></i>Confirmed by you</span>' if confirmed
                else f'<span class="chip" style="background:#fbe6dc"><i style="background:{ORANGE}"></i>Not yet confirmed</span>' if confirmed is False else "")
        warn = "".join(f'<div class="why">⚠ {e(w)}</div>' for w in r["dag"].get("warnings", []))
        P.append(section(n.get("dag_title", "How we think it works"),
                         f'<div class="dagwrap">' + card(chart_dag(r["dag"], 960) + dag_legend(r["dag"])) +
                         card(f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px"><h3>In words</h3>{chip}</div><div class="mlist" style="border:none;padding:0">{dag_in_words(r["dag"], labels)}</div>'
                              + (f'<div class="note">{e(n["dag_note"])}</div>' if n.get("dag_note") else "") + warn) + '</div>',
                         n.get("dag_text", "The causal diagram behind the analysis: each arrow means \u201caffects\u201d. It decides what to compare and what to leave out.")))

    # what domain knowledge said before the run
    spec_ = r.get("spec") or {}
    dn = spec_.get("domain_notes") or {}
    if dn or spec_.get("suspected_hidden") or spec_.get("negative_control_outcomes") or spec_.get("expected_effect"):
        rows_d = domain_section(dn, spec_, diag, labels)
        if rows_d:
            P.append(section(n.get("domain_title", f"What we know about {dn.get('domain', 'this kind of question')}"),
                             card(f'<div class="mlist" style="border:none;padding:0">{rows_d}</div>'),
                             n.get("domain_text", "Before running anything, we listed what usually goes wrong in this kind of analysis. Each point became a question for you, a check, or a control. Points marked ‘general knowledge’ were not confirmed by you.")))

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

    elif main_key and naive and m_est is not None and abs(m_est) > abs(naive):
        W = max(abs(naive), abs(m_est))
        bars = "".join(
            f'<div style="display:flex;align-items:center;gap:14px"><div style="width:160px;font-size:14px;font-weight:600">{e(lab)}</div>'
            f'<div style="flex:1"><div style="width:{100 * abs(v) / W:.1f}%;height:40px;background:{col};border-radius:0 6px 6px 0;display:flex;align-items:center;padding-left:14px;color:{tc};font-weight:600;white-space:nowrap">{e(f(v))}</div></div></div>'
            for lab, v, col, tc in ((n.get("naive_label", "Raw gap"), naive, ORANGE, INK), (n.get("action_label", "The real effect"), m_est, BLUE, "#fff")))
        P.append(section(n.get("gap_title", "The raw gap understates the effect"),
                         f'<div style="display:flex;flex-direction:column;gap:10px">{bars}</div>',
                         n.get("gap_text", "The people who got the action were, on average, headed for worse results anyway, so a simple comparison hides part of the effect.")))

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

    # what if the diagram is wrong
    alt = diag.get("alternatives") or {}
    sc = diag.get("structure_check") or {}
    if main_key and m_est is not None and main.get("ci") and (alt.get("user") or alt.get("add_one") or alt.get("leave_one_out")):
        ch = chart_alternatives(alt, main, main_key, f, labels)
        right = card('<h3>What the data itself suggests</h3><p class="small">A second opinion from a data-driven structure search. Treat these as questions, not answers: on its own this kind of search is often wrong.</p>'
                     + structure_findings(sc, labels)) if sc and "findings" in sc else ""
        P.append(section(n.get("alternatives_title", "What if our diagram is wrong?"),
                         card(ch + '<div class="legend"><span class="lg"><svg width="14" height="14" aria-hidden="true"><rect x="1" y="1" width="12" height="12" fill="rgba(42,120,214,0.25)"/></svg>Main result and its 95% range</span>'
                              f'<span class="lg"><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="5" fill="{ORANGE}"/></svg>Moves outside the range</span>'
                              + (f'<span class="lg"><svg width="14" height="14" aria-hidden="true"><circle cx="7" cy="7" r="4.5" fill="none" stroke="{ORANGE}" stroke-width="2"/></svg>A trap your answers rule out, shown for illustration</span>' if any(a.get("illustrative") for a in alt.get("user", [])) else "") +
                              '<span>Quick estimates, for comparison only; the main result stays as planned</span></div>') + right,
                         n.get("alternatives_text", "The answer depends on the diagram. Here is how it would change if we had drawn it differently: a different control set, a left-out column used as a control, or one control dropped.")))

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
        default_t = f"{share:.0%} had few look-alikes" if share >= 0.01 else "Almost everyone had look-alikes to compare with"
        tcards.append(card(f'<h3>{e(n.get("overlap_title", default_t))}</h3>'
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
    ncs = [x for x in (diag.get("negative_controls") or []) if "estimate" in x]
    if ncs and main_key and m_est is not None:
        base = (diag.get("derived") or {}).get("outcome_mean_untreated")
        mrel = m_est / base if base else None
        mci = [c / base for c in main["ci"]] if base and main.get("ci") else None
        bad = [x for x in ncs if not x["passes"]]
        tcards.append(card(f'<h3>{"The action seems to ‘change’ something it can’t" if bad else "No effect on things it can’t change"}</h3>'
                           '<p class="small">Changes relative to the untreated group’s average. We ran the main method on outcomes the action cannot plausibly affect. They should sit on the no-effect line.</p>'
                           + chart_negctl(ncs, mrel, mci, labels)
                           + (lambda c: (f'<div class="small" style="margin-top:10px"><b>If that hidden difference also inflates the main answer, the effect would be nearer {e(f(c["band"][0], sign=True))} to {e(f(c["band"][1], sign=True))}</b> (middle value {e(f(c["estimate"], sign=True))}). That assumes the difference shifts the main outcome by half to one and a half times the share it shifts the check outcome: a sensitivity band, not a corrected answer.</div>') if c else "")(diag.get("negative_control_adjusted") if (diag.get("negative_control_adjusted") or {}).get("band") else None)
                           + (f'<div class="note">{e(n.get("negative_control_note", "An apparent effect here means the groups differ in ways the data doesn’t record. The same difference likely inflates the main answer."))}</div>' if bad else "")))
    pz = diag.get("plausibility")
    if pz and main_key and main:
        tcards.append(card(f'<h3>{"In line with what was expected" if pz["inside"] else ("Far outside what was expected" if pz["far_outside"] else "Outside what was expected")}</h3>'
                           f'<p class="small">The range written into the plan before the run: {e(pz.get("basis") or "")}</p>' + chart_plausibility(pz, main, f)
                           + f'<div class="note">{source_chip(pz.get("source"))} This check never changes the estimate; it flags answers that need a second look.</div>'))
    sim = diag.get("simulation_check") or {}
    if sim.get("reps"):
        good = (sim["reps"] < 3 or sim["coverage"] >= 0.5) and abs(sim["bias"]) <= 0.25 * abs(sim["planted"] or 1)
        tcards.append(card(f'<h3>{("Tested on your data: it finds a planted effect" if sim["coverage"] >= 0.99 else "Tested on your data: it finds a planted effect, with ranges a little narrow") if good else "Tested on your data: it struggles"}</h3>'
                           f'<p class="small">We kept your real columns and who really got the action, simulated the outcome with a known effect of {e(f(sim["planted"]))}, and reran the main method. It recovered {e(f(sim["mean_estimate"]))} on average; {sim["coverage"]:.0%} of its ranges contained the planted value. The raw gap would have said {e(f(sim["naive_mean"]))}.</p>'
                           + chart_sim(sim, f) + '<div class="note">This checks the method on your data’s structure. It can’t test for factors missing from the data.</div>'))
    checks = []
    pl = diag.get("placebo_permuted_treatment")
    if pl:
        checks.append((check_row if pl["passes"] else fail_row)("Sanity check: a shuffled action shows no effect" if pl["passes"] else "Sanity check failed: a shuffled action showed an effect",
                      f"Shuffling who got the action at random ({len(pl.get('shuffles', [0]))} times) gave {('about 0' if abs(pl['estimate']) < 0.5 * 10 ** -f.dec / max(f.k, 1e-12) else f(pl['estimate'], sign=True))} on average{', close to zero as it should be' if pl['passes'] else ', clearly away from zero'}."))
    rc = diag.get("random_common_cause")
    if rc:
        checks.append(check_row("Adding a random variable changes nothing", f"The estimate moved by {f(abs(rc['change']))}."))
    subs = diag.get("subset_80pct_estimates")
    if subs:
        checks.append(check_row("Stable on random 80% subsets", f"{f(min(subs))} to {f(max(subs))}; blue line is the main result.", chart_subsets(subs, m_est, f)))
    if checks:
        d_note = ('<div class="note">These checks look for problems in the method. They can’t detect the unrecorded factor that makes this a D, so passing them doesn’t make the adjusted numbers trustworthy.</div>' if tier == "D" else "")
        tcards.append(card(f'<h3>{"Checks that passed" if all("Passed" in c for c in checks) else "Checks"}</h3>{"".join(checks)}{d_note}'))
    if tcards:
        P.append(section(n.get("trust_title", f"Why the grade is {tier}"), f'<div class="grid2">{"".join(tcards)}</div>', n.get("trust_text")))

    # assumptions + trap + data issues
    left = right = ""
    arows = assumption_rows(r, n, diag)
    if arows:
        left = f'<div style="display:flex;flex-direction:column;gap:14px"><h2>What this rests on</h2>' + card(f'<table class="assume"><tr><th>Assumption</th><th>Status</th></tr>{arows}</table>') + "</div>"
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
    trs = "".join(f'<tr><td>{e("Raw gap (not adjusted)" if k == "naive_difference" else METHODS.get(k, (k,))[0])}{" (main)" if k == main_key else ""}</td><td>{e(f(est[k]["estimate"]))}</td>'
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
    return (f'<!doctype html><html lang="{e(n.get("lang", "en"))}"><head><meta charset="utf-8">{CSP_META}<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(n.get("page_title", n.get("title", "Causal analysis")))}</title>{fonts}<style>{CSS}</style></head>'
            f'<body><main class="page">{"".join(P)}</main></body></html>')


def main(results_path, narrative_path, out_path):
    r = json.loads(Path(results_path).read_text())
    n = json.loads(Path(narrative_path).read_text()) if narrative_path else {}
    Path(out_path).write_text(render(r, n))
    print(f"wrote {out_path}")
