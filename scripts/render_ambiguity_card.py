"""Render the Eval Log card "Two right answers, so it asks" as PNGs.

Every number comes from data/msft/ground-truth.json (FY2026 operating income, net
income, accession and fiscal year end), so the card cannot drift from the data the
server is tested against. Needs `rsvg-convert` and the Anton and IBM Plex Sans font
files (set RAHIL_DESIGN_FONTS, or pass --fonts). Writes
docs/images/ambiguity-landscape.png (1200x675) and ambiguity-square.png (1080x1080).

Palette: navy canvas and ink, paper panel, one red accent used only on "Asks which".
Sizes are set for a phone: the 1200px canvas shows at about 390px, so every label is
at least 28px and the footer at least 26px (asserted below).
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH = ROOT / "data" / "msft" / "ground-truth.json"
OUT = ROOT / "docs" / "images"
DEFAULT_FONTS = Path.home() / ".t3/projects/main/.agents/skills/rahil-design/assets/fonts"

NAVY, PAPER, INK, MUTED, RED, TOP = "#0E1A2F", "#F5F5EF", "#14233D", "#44506A", "#C8102E", "#C9D1DE"
MIN_LABEL_PX, MIN_FOOT_PX = 28, 26

# Per canvas: size, headline lines and px, subtitle lines and px, figure height, footer px.
LAYOUTS = {
    "landscape": dict(w=1200, h=675, h1=["Two right answers, so it asks"], h1px=66, sub=['Both operating income and net income are "profit". It asks which.'], subpx=28, fig_h=232, footpx=26),
    "square": dict(w=1080, h=1080, h1=["Two right answers,", "so it asks"], h1px=100, sub=['Both operating income and net', 'income are "profit". It asks which.'], subpx=34, fig_h=440, footpx=28),
}
PAD, PANEL_PAD = 48, 30


def load_facts():
    gt = json.loads(GROUND_TRUTH.read_text())
    y = gt["years"]["2026"]
    end = date.fromisoformat(y["end"])
    return {
        "operating_income": int(y["operating_income"]),
        "net_income": int(y["net_income"]),
        "accession": y["accession"],
        "year_end": f"{end:%b} {end.day}, {end.year}",
    }


def billions(v):
    return f"${v / 1e9:,.3f}B"


def t(x, y, s, size, fill=INK, weight=400, anchor="start", family="IBM Plex Sans"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{fill}" text-anchor="{anchor}">{escape(s)}</text>')


def card(kind, f):
    L = LAYOUTS[kind]
    w, h = L["w"], L["h"]
    assert L["subpx"] >= MIN_LABEL_PX and L["footpx"] >= MIN_FOOT_PX
    foot = [f"FY2026 = year ended {f['year_end']} (Microsoft 10-K).",
            f"Accession {f['accession']}. Returns needs_clarification.",
            "Source: github.com/RahilBhavan/financial-metrics-analyst"]
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
         f'<rect width="{w}" height="{h}" fill="{NAVY}"/>']
    y = PAD + MIN_LABEL_PX * 0.8
    s.append(t(PAD, y, "Rahil Bhavan", MIN_LABEL_PX, TOP))
    s.append(t(w - PAD, y, "Eval Log", MIN_LABEL_PX, PAPER, 600, "end"))
    y += 18
    for line in L["h1"]:
        y += L["h1px"] * 0.98
        s.append(t(PAD, y, line.upper(), L["h1px"], PAPER, 400, family="Anton"))
    y += 10
    for line in L["sub"]:
        y += L["subpx"] * 1.3
        s.append(t(PAD, y, line, L["subpx"], PAPER))
    # Paper panel: figure, then footer.
    top = y + 22
    fx, fw, fh = PAD + PANEL_PAD, w - 2 * (PAD + PANEL_PAD), L["fig_h"]
    foot_lh = L["footpx"] * 1.3
    panel_h = 24 + fh + 8 + foot_lh * len(foot) + 18
    s.append(f'<rect x="{PAD}" y="{top:.1f}" width="{w - 2 * PAD}" height="{panel_h:.1f}" rx="12" fill="{PAPER}"/>')
    oy = top + 24
    cy = oy + fh / 2
    bx = fx + fw * 0.36  # value column
    s.append(t(fx, cy - 6, '"Microsoft', 32, INK, 600))
    s.append(t(fx, cy + 32, 'FY2026 profit?"', 32, INK, 600))
    for lab, val, yy in (("Operating income", f["operating_income"], oy + fh * 0.26),
                         ("Net income", f["net_income"], oy + fh * 0.74)):
        s.append(f'<path d="M{bx - 78:.1f},{cy:.1f} C{bx - 44:.1f},{cy:.1f} {bx - 44:.1f},{yy:.1f} {bx - 10:.1f},{yy:.1f}" '
                 f'fill="none" stroke="{INK}" stroke-width="3"/>')
        s.append(t(bx, yy - 14, lab, MIN_LABEL_PX, MUTED))
        s.append(t(bx, yy + 32, billions(val), 44, INK, 600))
    ax = fx + fw
    s.append(t(ax - 2, cy + 6, "Asks which", 36, RED, 600, "end"))
    s.append(f'<rect x="{ax - 190}" y="{cy + 22:.1f}" width="188" height="9" fill="{INK}"/>')
    fy = oy + fh + 8
    for line in foot:
        fy += foot_lh
        s.append(t(fx, fy - 6, line, L["footpx"], MUTED))
    assert top + panel_h <= h - PAD + 1, f"{kind}: panel bottom {top + panel_h:.0f} overflows {h - PAD}"
    s.append("</svg>")
    return "".join(s)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fonts", type=Path, default=Path(os.environ.get("RAHIL_DESIGN_FONTS", DEFAULT_FONTS)))
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    facts = load_facts()
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        conf = Path(tmp) / "fonts.conf"
        conf.write_text(f'<?xml version="1.0"?><fontconfig><dir>{args.fonts}</dir><cachedir>{tmp}/cache</cachedir>'
                        '<include ignore_missing="yes">/etc/fonts/fonts.conf</include></fontconfig>')
        env = {**os.environ, "FONTCONFIG_FILE": str(conf)}
        for kind in LAYOUTS:
            svg = Path(tmp) / f"{kind}.svg"
            svg.write_text(card(kind, facts))
            png = args.out / f"ambiguity-{kind}.png"
            subprocess.run(["rsvg-convert", str(svg), "-o", str(png)], check=True, env=env)
            print(png)


if __name__ == "__main__":
    sys.exit(main())
