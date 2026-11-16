"""
Generate the architecture diagram (assets/architecture_diagram_agentic_solution.svg).
Render to PNG with: node <scratch>/render_svg.js, or open the SVG in a browser.

Three tiers, read top to bottom:
  1. Data pipeline: a monthly delivery becomes certified data; teams are alerted when something is wrong.
  2. Agentic intelligence: Genie and the two agents answer three different questions on the same governed data.
  3. Decision: all three feed one decision brief for the CFO Office and Board, with human review.
"""
from pathlib import Path
from html import escape

W, H = 1600, 1010
INK, MUTED, BLUE, BLUE_D = "#0d1b4c", "#5b6378", "#2f66f6", "#1d4ed8"
FONT = "Inter, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif"
out = []


def text(x, y, lines, size=14, weight=400, color=INK, anchor="middle", lh=1.35):
    """Multi-line text; lines is a str or list. Each item may be (text, weight, color)."""
    if isinstance(lines, str):
        lines = [lines]
    for i, ln in enumerate(lines):
        t, w, c = (ln, weight, color) if isinstance(ln, str) else (ln + (color,))[:3] if len(ln) == 2 else ln
        out.append(f'<text x="{x}" y="{y + i * size * lh:.1f}" font-size="{size}" font-weight="{w}" fill="{c}" '
                   f'text-anchor="{anchor}">{escape(t)}</text>')


def box(x, y, w, h, fill="#fff", stroke="#d5dbea", sw=1.5, r=14, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def arrow(d, color="#8a93a8", sw=2, dash=None, head="ah"):
    ds = f' stroke-dasharray="{dash}"' if dash else ""
    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{ds} marker-end="url(#{head})"/>')


def badge(cx, cy, n, fill=BLUE):
    out.append(f'<circle cx="{cx}" cy="{cy}" r="15" fill="{fill}"/>')
    text(cx, cy + 5, str(n), size=14, weight=700, color="#fff")


def band_title(x, y, n, title, sub):
    badge(x + 15, y - 5, n)
    out.append(f'<text x="{x + 40}" y="{y}" fill="{INK}"><tspan font-size="19" font-weight="700">{escape(title)}</tspan>'
               f'<tspan font-size="14" fill="{MUTED}" dx="14">{escape(sub)}</tspan></text>')


# ---------------------------------------------------------------- frame
out.append(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
text(40, 46, [("Cloudstruck · from a monthly data delivery to a Board decision", 700)], size=24, anchor="start")
text(40, 72, "IFC CFO Office portfolio intelligence on Databricks", size=15, color=MUTED, anchor="start")

# ---------------------------------------------------------------- 1. data pipeline
band_title(40, 122, 1, "Data pipeline", "Databricks Jobs, every month · nothing reaches the agents until it is certified")
box(30, 140, 1540, 268, fill="#f5f8ff", stroke="#dbe4fb", r=18)

stages = [
    ("Incoming data", ["Monthly files land in a", "Unity Catalog volume:", "structured tables +", "free-text descriptions"]),
    ("Schema gate", ["Every column checked", "against its data contract", "before anything loads"]),
    ("Raw", ["Each delivery kept", "exactly as received,", "full history"]),
    ("Validate", ["Types and business rules;", "unusable rows quarantined,", "issues flagged with an owner"]),
    ("Enrich with AI", ["An LLM turns free-text", "descriptions into fields", "(capacity, product, renewable)"]),
    ("Certify", ["One governed row per project,", "72 reconciliation checks:", "nothing lost or double counted"]),
]
bw, bh, gap, x0, y0 = 222, 128, 33, 55, 162
centers = []
for i, (t, body) in enumerate(stages):
    x = x0 + i * (bw + gap)
    last = i == len(stages) - 1
    box(x, y0, bw, bh, fill=BLUE if last else "#ffffff", stroke=BLUE if last else "#c9d5f5", sw=1.6)
    c = "#ffffff" if last else INK
    text(x + bw / 2, y0 + 32, [(t, 700)], size=16, color=c)
    text(x + bw / 2, y0 + 58, body, size=13, color="#e8eeff" if last else MUTED)
    centers.append(x + bw / 2)
    if i:
        arrow(f"M{x - gap + 3} {y0 + bh / 2} L{x - 5} {y0 + bh / 2}", color=BLUE, sw=2.2, head="ahb")

# alerts under the gate, validate and enrich stages
alerts = [
    (1, "#fdecec", "#e5484d", "#a3171c", ["Structure problem: file held,", "job stops, data owner emailed"]),
    (3, "#fff5e6", "#e08a2e", "#7a4300", ["Issues queued for the", "owning team to fix"]),
    (4, "#fff5e6", "#e08a2e", "#7a4300", ["Uncertain readings sent", "to a human reviewer"]),
]
ay = 322
for i, fill, stroke, ink, lines in alerts:
    cx = centers[i]
    arrow(f"M{cx} {y0 + bh + 2} L{cx} {ay - 5}", color=stroke, sw=1.8, dash="5 4", head="ah_" + stroke[1:])
    box(cx - 111, ay, 222, 64, fill=fill, stroke=stroke, sw=1.4, r=12)
    text(cx, ay + 26, lines, size=13, color=ink, weight=600)
text(centers[0], ay + 26, [("Alerts go to the", 600), ("team that owns the fix", 600)], size=13, color=MUTED)
arrow(f"M{centers[0] + 92} {ay + 32} L{centers[1] - 117} {ay + 32}", color="#b8bfd0", sw=1.4, dash="3 4")

# ---------------------------------------------------------------- governance strip
gy = 426
box(30, gy, 1540, 50, fill="#eef2fb", stroke="#c9d5f5", r=12)
out.append(f'<text x="800" y="{gy + 31}" font-size="15" fill="{INK}" text-anchor="middle"><tspan font-weight="700">'
           'Unity Catalog</tspan><tspan dx="10">certified tables · 24 documented assumptions · lineage · access grants · '
           'every answer and agent run audited</tspan></text>')

# ---------------------------------------------------------------- 2. agentic intelligence
band_title(40, 530, 2, "Agentic intelligence", "")
agents = [
    ("Genie", "What happened?", ["Plain-language questions", "turned into SQL on the", "certified tables"]),
    ("Stress-test agent", "What if credit worsens?", ["Runs downside scenarios", "on reserves and expected", "credit loss"]),
    ("Capital allocation agent", "Where should new money go?", ["Ranks sectors and regions", "with portfolio data and", "cited market research"]),
]
aw, ah, ay2 = 380, 150, 552
ax = [110, 610, 1110]
for (t, q, body), x in zip(agents, ax):
    arrow(f"M{x + aw / 2} {gy + 52} L{x + aw / 2} {ay2 - 6}", color="#8a93a8", sw=2)
    box(x, ay2, aw, ah, fill="#ffffff", stroke=BLUE, sw=2, r=16)
    text(x + aw / 2, ay2 + 34, [(t, 700)], size=18)
    text(x + aw / 2, ay2 + 60, [(f"“{q}”", 600)], size=15, color=BLUE_D)
    text(x + aw / 2, ay2 + 88, body, size=13, color=MUTED)
gr_y = ay2 + ah + 14
text(800, gr_y + 12, "Guardrails on all three: figures come only from governed SQL, never from the model · trust check Green / Amber / Red · open-weight model on Databricks",
     size=13, color=MUTED)

# ---------------------------------------------------------------- 3. decision (the three pour into one brief)
dy, dw, dh = 790, 700, 104
dx = 800 - dw / 2
for x in ax:
    sx = x + aw / 2
    tx = 800 + (sx - 800) * 0.45
    arrow(f"M{sx} {gr_y + 26} C{sx} {dy - 40}, {tx} {dy - 50}, {tx} {dy - 6}", color=BLUE, sw=2.6, head="ahb")
badge(dx - 30, dy + 30, 3)
box(dx, dy, dw, dh, fill="url(#g)", stroke=BLUE_D, sw=2, r=18)
text(800, dy + 38, [("Decision brief for the CFO Office and Board", 700)], size=20, color="#ffffff")
text(800, dy + 66, ["What happened + the downside + where to allocate, in one view:", "which clients to back, which to review"],
     size=14, color="#e8eeff")

# people and the human-review loop
py = 940
arrow(f"M{dx + 170} {dy + dh + 2} L{dx + 170} {py - 6}", color="#8a93a8", sw=2)
arrow(f"M{dx + dw - 170} {dy + dh + 2} L{dx + dw - 170} {py - 6}", color="#8a93a8", sw=2)
box(dx + 30, py, 280, 46, fill="#f6f7fb", stroke="#c3c9d8", r=12)
text(dx + 170, py + 29, [("CFO Office · Board", 600)], size=15)
box(dx + dw - 330, py, 320, 46, fill="#f6f7fb", stroke="#c3c9d8", r=12)
text(dx + dw - 170, py + 29, [("Credit Risk Committee · human review", 600)], size=15)
# decision recorded back into the catalog
rx = dx + dw - 10
arrow(f"M{rx} {py + 23} L{1540} {py + 23} L{1540} {gy + 56}", color="#8a93a8", sw=1.6, dash="6 5")
text(1530, 870, [("decision", 600), ("recorded", 600)], size=12, color=MUTED, anchor="end")

# ---------------------------------------------------------------- write
defs = ['<marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M0 0 L10 5 L0 10 z" fill="#8a93a8"/></marker>',
        f'<marker id="ahb" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0 0 L10 5 L0 10 z" fill="{BLUE}"/></marker>',
        f'<linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BLUE}"/>'
        f'<stop offset="1" stop-color="#5b3df5"/></linearGradient>']
for c in ("e5484d", "e08a2e"):
    defs.append(f'<marker id="ah_{c}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
                f'<path d="M0 0 L10 5 L0 10 z" fill="#{c}"/></marker>')
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">'
       f'<defs>{"".join(defs)}</defs>\n' + "\n".join(out) + "\n</svg>\n")
Path(__file__).with_name("architecture_diagram_agentic_solution.svg").write_text(svg)
print("written")
