"""Causal diagram (DAG) for a spec: one source of truth for the picture, the Mermaid text,
and the graph used in the DoWhy identification cross-check."""
from __future__ import annotations

import json
import re
from pathlib import Path

HIDDEN = "U_hidden"


def _is_post(why) -> bool:
    w = str(why).lower()
    return "post" in w or "after" in w or "consequence" in w or "caused by" in w


def build(spec: dict) -> dict:
    """Nodes with roles and edges with kinds, from the spec.

    Edge kinds: assumed (from the plan), hidden (unrecorded driver), sme (arrow the SME added),
    knowledge (arrow from general domain knowledge, not confirmed), suspected (a driver that
    domain knowledge suggests but nobody confirmed; shown, sized, not used for identification),
    after (consequence of the action; deliberately not controlled for).
    """
    T, Y = spec["treatment"], spec["outcome"]
    lab = spec.get("labels", {})
    randomized = bool(spec.get("randomized"))
    nodes, edges = {}, []

    def node(n, role):
        nodes.setdefault(n, {"id": n, "label": lab.get(n, n), "role": role})

    def edge(a, b, kind, source=None):
        if (a, b) not in {(e["from"], e["to"]) for e in edges}:
            edges.append({"from": a, "to": b, "kind": kind, **({"source": source} if source else {})})

    node(T, "action"); node(Y, "outcome")
    meds = spec.get("mediators", [])
    if not meds:
        edge(T, Y, "assumed")
    for m in meds:
        node(m, "middle step"); edge(T, m, "assumed"); edge(m, Y, "assumed")
    for c in spec.get("confounders", []):
        node(c, "control")
        if not randomized:
            edge(c, T, "assumed")
        edge(c, Y, "assumed")
    for z in spec.get("instruments", []):
        node(z, "nudge (instrument)"); edge(z, T, "assumed")
    if spec.get("hidden_confounding") == "named_driver" and not randomized:
        note = spec.get("hidden_driver_label") or spec.get("hidden_driver_note") or "unrecorded driver"
        note = re.sub(r"\s*\((unrecorded|not recorded|not in (the )?data)\)\s*$", "", note, flags=re.I)
        if len(note) > 45:
            note = note[:44].rsplit(" ", 1)[0] + " ..."
        nodes[HIDDEN] = {"id": HIDDEN, "label": f"Not in data: {note}", "role": "hidden"}
        edge(HIDDEN, T, "hidden"); edge(HIDDEN, Y, "hidden")
    ncs = [x["column"] if isinstance(x, dict) else x for x in spec.get("negative_control_outcomes", [])]
    for c, why in spec.get("excluded", {}).items():
        if c in ncs:
            continue
        if _is_post(why):
            node(c, "after the action"); edge(T, c, "after")
    for item in spec.get("extra_edges", []):
        a, b = item[0], item[1]
        src = item[2] if len(item) > 2 else "sme"
        for n in (a, b):
            node(n, "other")
        edge(a, b, "knowledge" if "general" in str(src).lower() else "sme", src)
    if not randomized:
        for i, sh in enumerate(spec.get("suspected_hidden", [])[:2]):
            hid = f"U_suspected_{i}"
            lbl = sh.get("label", "suspected driver") if isinstance(sh, dict) else str(sh)
            nodes[hid] = {"id": hid, "label": f"Suspected, not in data: {lbl}", "role": "hidden", "suspected": True}
            edge(hid, T, "suspected", "general knowledge"); edge(hid, Y, "suspected", "general knowledge")
            for px in (sh.get("proxies", []) if isinstance(sh, dict) else []):
                if px in nodes:
                    edge(hid, px, "suspected", "general knowledge")
            for c in ncs:
                node(c, "check: can't be affected")
                edge(hid, c, "suspected", "general knowledge")
    if randomized:
        nodes[T]["label"] += " (randomized)"
    return {"nodes": list(nodes.values()), "edges": edges, "treatment": T, "outcome": Y}


def analysis_graph(dag: dict):
    """networkx DiGraph used for identification (drops 'after' display-only edges)."""
    import networkx as nx
    g = nx.DiGraph()
    for e in dag["edges"]:
        if e["kind"] not in ("after", "suspected"):
            g.add_edge(e["from"], e["to"])
    g.add_node(dag["treatment"]); g.add_node(dag["outcome"])
    return g


def mermaid(dag: dict) -> str:
    ids = {n["id"]: f"n{i}" for i, n in enumerate(dag["nodes"])}
    out = ["flowchart LR"]
    for n in dag["nodes"]:
        text = n["label"].replace('"', "'")
        shape = {"action": '(["{}"])', "outcome": '(["{}"])', "hidden": '{{{{"{}"}}}}'}.get(n["role"], '["{}"]')
        out.append(f"  {ids[n['id']]}{shape.format(text)}")
    for e in dag["edges"]:
        a, b = ids[e["from"]], ids[e["to"]]
        arrow = {"hidden": "-.->", "suspected": "-. suspected .->", "after": "-. not controlled .->", "sme": "==>", "knowledge": "-. general knowledge .->"}.get(e["kind"], "-->")
        out.append(f"  {a} {arrow} {b}")
    out += ["  classDef action fill:#1f5fa6,color:#fff,stroke:#1f5fa6",
            "  classDef outcome fill:#2e7d4f,color:#fff,stroke:#2e7d4f",
            "  classDef hidden fill:#fff,stroke:#b5542c,stroke-dasharray:4 3,color:#b5542c",
            "  classDef after fill:#eee,stroke:#999,color:#666"]
    for n in dag["nodes"]:
        cls = {"action": "action", "outcome": "outcome", "hidden": "hidden", "after the action": "after"}.get(n["role"])
        if cls:
            out.append(f"  class {ids[n['id']]} {cls}")
    return "\n".join(out)


def _wrap(s, width=22):
    words, lines, cur = s.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width and cur:
            lines.append(cur); cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    return "\n".join(lines)


def draw(dag: dict, path, group_over: int = 6):
    """Layered drawing with matplotlib only (no graphviz needed).

    Columns: causes (controls, nudges, hidden) | action / middle steps | outcome.
    'After the action' columns sit under the action. More than `group_over` controls are
    grouped into one box so the picture stays readable.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    nodes = {n["id"]: dict(n) for n in dag["nodes"]}
    edges = [dict(e) for e in dag["edges"]]
    T, Y = dag["treatment"], dag["outcome"]
    controls = [n for n, v in nodes.items() if v["role"] == "control"]
    sme_touch = {e["from"] for e in edges if e["kind"] in ("sme", "knowledge", "suspected")} | {e["to"] for e in edges if e["kind"] in ("sme", "knowledge", "suspected")}
    groupable = [c for c in controls if c not in sme_touch]
    if len(groupable) > group_over:
        gid = "__controls__"
        names = [nodes[c]["label"] for c in groupable]
        nodes[gid] = {"id": gid, "role": "control", "label": f"{len(names)} recorded traits: " + ", ".join(names[:8]) + (" ..." if len(names) > 8 else "")}
        for c in groupable:
            nodes.pop(c)
        new = []
        for e in edges:
            e = dict(e)
            if e["from"] in groupable: e["from"] = gid
            if e["to"] in groupable: e["to"] = gid
            if (e["from"], e["to"], e["kind"]) not in {(x["from"], x["to"], x["kind"]) for x in new}:
                new.append(e)
        edges = new

    top_nodes = [n for n, v in nodes.items() if v["role"] in ("control", "other")]
    nudges = [n for n, v in nodes.items() if v["role"] == "nudge (instrument)"]
    hidden = [n for n, v in nodes.items() if v["role"] == "hidden"]
    meds = [n for n, v in nodes.items() if v["role"] == "middle step"]
    after = [n for n, v in nodes.items() if v["role"] in ("after the action", "check: can't be affected")]
    # Confounding triangle: shared causes above, action left, outcome right, hidden driver below.
    W = max(6.0, 1.7 * min(len(top_nodes), 5))
    pos = {T: (0.0, 0.0), Y: (W, 0.0)}
    for i, n in enumerate(meds):
        pos[n] = (W * (i + 1) / (len(meds) + 1), 0.0)
    per_row = 5
    for i, n in enumerate(top_nodes):
        row, col = divmod(i, per_row)
        k = min(per_row, len(top_nodes) - row * per_row)
        x = W / 2 + (col - (k - 1) / 2) * (0.9 * W / max(k, 1))
        pos[n] = (x, 2.0 + 1.1 * row)
    for i, n in enumerate(nudges):
        pos[n] = (-2.4, 0.0 - 1.0 * i)
    for i, n in enumerate(hidden):
        pos[n] = (W / 2, -2.0 - i)
    for i, n in enumerate(after):
        pos[n] = (0.0 + 1.6 * i, -2.0 - (1.2 if hidden else 0))
    style = {"action": ("#1f5fa6", "white", "-"), "outcome": ("#2e7d4f", "white", "-"),
             "hidden": ("white", "#b5542c", "--"), "after the action": ("#eeeeee", "#666666", "-")}
    ys = [p[1] for p in pos.values()]
    fig_h = max(3.4, 1.0 * (max(ys) - min(ys)) + 2.2)
    fig, ax = plt.subplots(figsize=(max(10, 1.5 * W + 2), fig_h))
    boxes = {}
    for n, (x, y) in pos.items():
        v = nodes[n]
        fc, tc, ls = style.get(v["role"], ("#f4f6f9", "#222222", "-"))
        ec = {"hidden": "#b5542c", "after the action": "#999999"}.get(v["role"], fc if fc != "#f4f6f9" else "#8a94a6")
        txt = _wrap(v["label"], 40 if n.startswith("__") else 22)
        boxes[n] = ax.text(x, y, txt, ha="center", va="center", fontsize=9, color=tc, zorder=3,
                           bbox=dict(boxstyle="round,pad=0.45", fc=fc, ec=ec, ls=ls, lw=1.2))
    xs0 = [p[0] for p in pos.values()]
    ax.set_xlim(min(xs0) - 1.2, max(xs0) + 1.2)
    ax.set_ylim(min(ys) - 0.9, max(ys) + 0.9)
    fig.canvas.draw()
    inv = ax.transData.inverted()
    rects = {}
    for n, t in boxes.items():
        bb = t.get_bbox_patch().get_window_extent()
        (x0, y0), (x1, y1) = inv.transform([(bb.x0, bb.y0), (bb.x1, bb.y1)])
        rects[n] = (x0, y0, x1, y1)

    def clip(p, q, r, pad=0.04):
        """Point where segment p->q leaves rectangle r (p inside r)."""
        (px, py), (qx, qy) = p, q
        x0, y0, x1, y1 = r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad
        dx, dy = qx - px, qy - py
        ts = []
        for edge_v, d, o in ((x0, dx, px), (x1, dx, px)):
            if d: ts.append((edge_v - o) / d)
        for edge_v, d, o in ((y0, dy, py), (y1, dy, py)):
            if d: ts.append((edge_v - o) / d)
        t = min([t for t in ts if t > 0] or [0])
        return (px + t * dx, py + t * dy)

    for e in edges:
        a, b = e["from"], e["to"]
        if a not in pos or b not in pos:
            continue
        col, ls, lw = {"assumed": ("#555555", "-", 1.1), "hidden": ("#b5542c", "--", 1.3),
                       "sme": ("#7a3fb0", "-", 1.8), "after": ("#999999", ":", 1.2),
                       "knowledge": ("#7a3fb0", "--", 1.4), "suspected": ("#b5542c", ":", 1.3)}[e["kind"]]
        start = clip(pos[a], pos[b], rects[a])
        end = clip(pos[b], pos[a], rects[b])
        rad = 0.25 if (e["kind"] in ("sme", "knowledge") and abs(pos[a][1] - pos[b][1]) < 1e-9) else 0.0
        ax.annotate("", xy=end, xytext=start, zorder=2,
                    arrowprops=dict(arrowstyle="-|>,head_length=0.6,head_width=0.3", color=col, ls=ls, lw=lw,
                                    connectionstyle=f"arc3,rad={rad}", shrinkA=0, shrinkB=0))
    ax.axis("off")
    legend = [("#555555", "-", "assumed cause (from our plan)"), ("#b5542c", "--", "not in the data (hidden driver)"),
              ("#7a3fb0", "-", "added arrow (beyond the default plan)"), ("#999999", ":", "happens after the action: not controlled for"),
              ("#7a3fb0", "--", "from general knowledge, not confirmed"), ("#b5542c", ":", "suspected from general knowledge, not in the data")]
    used = {e["kind"] for e in edges}
    keep = {"assumed": 0, "hidden": 1, "sme": 2, "after": 3, "knowledge": 4, "suspected": 5}
    handles = [plt.Line2D([0], [0], color=c, ls=l, lw=1.5, label=t) for k, (c, l, t) in zip(keep, legend) if k in used]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.02), ncol=2, fontsize=8, frameon=False)
    ax.set_title("How we think it works: arrows mean 'affects'", fontsize=10, loc="left")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def checks(dag: dict) -> list[str]:
    """Plain-language warnings about the diagram itself."""
    import networkx as nx
    g = analysis_graph(dag)
    T, Y = dag["treatment"], dag["outcome"]
    warn = []
    if not nx.is_directed_acyclic_graph(g):
        lab = {n["id"]: n["label"] for n in dag["nodes"]}
        ctrl = {n["id"] for n in dag["nodes"] if n["role"] == "control"}
        for cyc in nx.simple_cycles(g):
            if T in cyc and ctrl & set(cyc):
                c = sorted(ctrl & set(cyc))[0]
                warn.append(f"'{lab[c]}' is listed as a control, but an arrow says the action affects it. If it can change because of the action, move it to excluded (post-treatment); if not, remove the arrow.")
            else:
                warn.append("The diagram has a loop: " + " -> ".join(lab.get(x, x) for x in cyc + cyc[:1]) + ". Causal diagrams can't have loops; ask which came first.")
        return warn
    desc = nx.descendants(g, T)
    for n in dag["nodes"]:
        if n["role"] == "control" and n["id"] in desc:
            warn.append(f"'{n['label']}' is used as a control but, per the diagram, the action affects it. Controlling for it can hide or flip the effect.")
    for n in dag["nodes"]:
        if n["role"] == "nudge (instrument)" and nx.has_path(g, n["id"], Y) and any(p for p in nx.all_simple_paths(g, n["id"], Y) if T not in p):
            warn.append(f"'{n['label']}' is meant to affect the outcome only through the action, but the diagram has another path to the outcome.")
    return warn


def write_all(spec: dict, outdir) -> dict:
    outdir = Path(outdir); outdir.mkdir(parents=True, exist_ok=True)
    dag = build(spec)
    dag["warnings"] = checks(dag)
    (outdir / "dag.json").write_text(json.dumps(dag, indent=1))
    (outdir / "dag.mmd").write_text(mermaid(dag))
    draw(dag, outdir / "dag.png")
    return dag
