"""Render the Eval Log card "Microsoft profit has two answers" as PNGs, alt text and a hash manifest.

Every number comes from data/msft/ground-truth.json (FY2026 operating income, net income,
accession, fiscal year end) and the snapshot date from data/msft/manifest.json, so the card cannot
drift from the data the server is tested against. The design rules are in DESIGN.md.

Needs Python 3.9+ and a Chromium binary (CHROMIUM, default "chromium"). Writes to docs/images/:
ambiguity-landscape.png (1024x640), ambiguity-square.png (1024x1024), ambiguity-alt.txt and
ambiguity-manifest.json (SHA-256 of each PNG). The script checks the rendered page (no text under
26px, only Roboto Slab and Archivo, nothing overflowing, fonts loaded) and exits 1 if a check fails.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime
from html import escape, unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GROUND_TRUTH = ROOT / "data" / "msft" / "ground-truth.json"
MANIFEST = ROOT / "data" / "msft" / "manifest.json"
FONT_DIR = ROOT / "scripts" / "card-fonts"
OUT = ROOT / "docs" / "images"

NAVY, PAPER, INK, MUTED, RED, TOP = "#0B1F4B", "#F5F5EF", "#0B1F4B", "#44506A", "#C8102E", "#C9D1DE"
WIDTH, MIN_PX = 1024, 26
TITLE = "Microsoft “profit” has two answers, so it asks which"
QUERY = "Asked “Microsoft profit 2026”"
ASKS = "Asks which: operating income or net income?"

# Per canvas: height, title px, bar height px, outer padding px.
LAYOUTS = {
    "landscape": dict(h=640, title=46, bar=46, pad=36),
    "square": dict(h=1024, title=60, bar=104, pad=48),
}


def long_date(d):
    return f"{d:%b} {d.day}, {d.year}"


def load_facts():
    y = json.loads(GROUND_TRUTH.read_text())["years"]["2026"]
    captured = datetime.fromisoformat(json.loads(MANIFEST.read_text())["captured_at"]).date()
    return {
        "operating_income": int(y["operating_income"]),
        "net_income": int(y["net_income"]),
        "accession": y["accession"],
        "year_end": long_date(date.fromisoformat(y["end"])),
        "data_date": long_date(captured),
    }


def billions(v):
    return f"${v / 1e9:,.3f}B"


def footer_lines(f):
    return [f"Source: Microsoft FY2026 10-K, year ended {f['year_end']}.",
            f"Accession {f['accession']}. SEC data as of {f['data_date']}."]


def alt_text(f):
    return (f"Two bars on one scale from zero, from Microsoft's FY2026 10-K (year ended {f['year_end']}): "
            f"operating income {billions(f['operating_income'])} and net income {billions(f['net_income'])}. "
            f"Below them, in red: asked for Microsoft profit, the server asks which of the two is meant. "
            f"Source: Microsoft FY2026 10-K, accession {f['accession']}; SEC data as of {f['data_date']}.")


def font_face(family, weight, name):
    data = base64.b64encode((FONT_DIR / name).read_bytes()).decode()
    return (f"@font-face{{font-family:'{family}';font-weight:{weight};"
            f"src:url(data:font/woff2;base64,{data}) format('woff2')}}")


CHECK_JS = """
document.fonts.ready.then(()=>{
  const out={minPx:99,fonts:[],issues:[],texts:[]};
  const card=document.querySelector('.card'),cb=card.getBoundingClientRect();
  const w=document.createTreeWalker(card,NodeFilter.SHOW_TEXT);
  for(let n;n=w.nextNode();){
    if(!n.textContent.trim())continue;
    const el=n.parentElement,cs=getComputedStyle(el);
    out.minPx=Math.min(out.minPx,parseFloat(cs.fontSize));
    const f=cs.fontFamily.split(',')[0].replace(/['"]/g,'');
    if(!out.fonts.includes(f))out.fonts.push(f);
    out.texts.push(n.textContent.trim());
    if(el.scrollWidth>el.clientWidth+1)out.issues.push('overflow-x: '+n.textContent);
  }
  card.querySelectorAll('*').forEach(e=>{const b=e.getBoundingClientRect();
    if(b.right>cb.right+0.5||b.bottom>cb.bottom+0.5||b.left<-0.5||b.top<-0.5)out.issues.push('outside card: '+e.className);});
  const panel=document.querySelector('.panel').getBoundingClientRect(),foot=document.querySelector('.foot').getBoundingClientRect();
  if(panel.bottom>foot.top)out.issues.push('panel overlaps footer');
  if(foot.bottom>cb.bottom-8)out.issues.push('footer too close to the edge');
  const bars=[...document.querySelectorAll('.bar')].map(e=>e.getBoundingClientRect().width);
  out.barWidths=bars;
  out.fontsLoaded=['700 20px "Roboto Slab"','400 20px Archivo','600 20px Archivo'].every(s=>document.fonts.check(s));
  document.title='CHECK:'+JSON.stringify(out);
});
"""


def build_html(kind, f):
    L = LAYOUTS[kind]
    h, pad, bar_h = L["h"], L["pad"], L["bar"]
    inner = WIDTH - 2 * pad - 2 * 28  # panel padding is 28px a side
    top = max(f["operating_income"], f["net_income"])
    rows = "".join(
        f'<div class="lab">{escape(lab)}</div>'
        f'<div class="bar" style="width:{v / top * inner:.2f}px"><span>{escape(billions(v))}</span></div>'
        for lab, v in (("Operating income", f["operating_income"]), ("Net income", f["net_income"])))
    fonts = (font_face("Roboto Slab", 700, "roboto-slab-latin-700-normal.woff2")
             + font_face("Archivo", 400, "archivo-latin-400-normal.woff2")
             + font_face("Archivo", 600, "archivo-latin-600-normal.woff2"))
    foot = "".join(f"<div>{escape(line)}</div>" for line in footer_lines(f))
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>{escape(TITLE)}</title>
<style>{fonts}
*{{box-sizing:border-box;margin:0}}
html,body{{width:{WIDTH}px;height:{h}px;background:{NAVY};overflow:hidden}}
.card{{width:{WIDTH}px;height:{h}px;padding:{pad}px;display:flex;flex-direction:column;color:{PAPER};
  font:400 {MIN_PX}px/1.25 Archivo,sans-serif}}
.kick{{font-weight:600;color:{TOP}}}
h1{{text-wrap:balance;font:700 {L["title"]}px/1.15 'Roboto Slab',serif;margin-top:{10 if kind == "landscape" else 18}px}}
.panel{{background:{PAPER};color:{INK};border-radius:12px;padding:{20 if kind == "landscape" else 32}px 28px;
  margin-top:{16 if kind == "landscape" else 30}px}}
.q{{color:{MUTED}}}
.lab{{color:{MUTED};margin-top:{10 if kind == "landscape" else 30}px}}
.bar{{background:{NAVY};height:{bar_h}px;margin-top:4px;display:flex;align-items:center;justify-content:flex-end;
  padding-right:14px;color:{PAPER};font-weight:600;font-size:{34 if kind == "landscape" else 44}px;white-space:nowrap}}
.asks{{margin-top:{14 if kind == "landscape" else 44}px;border-top:4px solid {RED};padding-top:{8 if kind == "landscape" else 14}px;
  color:{RED};font-weight:600;font-size:{30 if kind == "landscape" else 34}px;white-space:nowrap}}
.foot{{margin-top:auto;color:{TOP}}}
</style>
<div class="card" role="img" aria-label="{escape(alt_text(f))}">
<div class="kick">Eval Log</div>
<h1>{escape(TITLE)}</h1>
<div class="panel"><div class="q">{escape(QUERY)}</div>{rows}<div class="asks">{escape(ASKS)}</div></div>
<div class="foot">{foot}</div>
</div>
<script>{CHECK_JS}</script></html>"""


def chromium(*args):
    # These flags avoid hangs seen with the default GPU path and with user flag files; a throwaway
    # profile keeps it apart from any running browser.
    with tempfile.TemporaryDirectory(prefix="card-chromium-") as profile:
        return subprocess.run(
            [os.environ.get("CHROMIUM", "chromium"), "--headless", "--no-sandbox", "--disable-gpu",
             "--disable-gpu-compositing", "--use-gl=disabled", "--disable-extensions",
             "--run-all-compositor-stages-before-draw", "--hide-scrollbars",
             "--force-device-scale-factor=1", f"--user-data-dir={profile}", *args],
            capture_output=True, text=True, timeout=90)


def check(page, f):
    dom = chromium("--virtual-time-budget=5000", "--dump-dom", f"file://{page}").stdout
    m = re.search(r"<title>CHECK:(.*?)</title>", dom, re.S)
    if not m:
        return None, False
    res = json.loads(unescape(m.group(1)))
    shown = set(res["texts"])
    wanted = {billions(f["operating_income"]), billions(f["net_income"]), TITLE, ASKS, *footer_lines(f)}
    top = max(f["operating_income"], f["net_income"])
    ratio = res["barWidths"][1] / res["barWidths"][0]
    ok = (res["minPx"] >= MIN_PX and not res["issues"] and res["fontsLoaded"]
          and set(res["fonts"]) == {"Roboto Slab", "Archivo"} and wanted <= shown
          and abs(ratio - f["net_income"] / top) < 0.005)  # bars keep the data ratio from zero
    return res, ok


def main():
    f = load_facts()
    OUT.mkdir(parents=True, exist_ok=True)
    failed, hashes = False, {}
    with tempfile.TemporaryDirectory(prefix="ambiguity-card-") as tmp:
        for kind, L in LAYOUTS.items():
            page = Path(tmp) / f"{kind}.html"
            page.write_text(build_html(kind, f))
            res, ok = check(page, f)
            print(f"{kind}: {'PASS' if ok else 'FAIL'} {json.dumps({k: v for k, v in (res or {}).items() if k != 'texts'})}")
            failed |= not ok
            png = OUT / f"ambiguity-{kind}.png"
            png.unlink(missing_ok=True)
            chromium("--virtual-time-budget=5000", f"--window-size={WIDTH},{L['h']}", f"--screenshot={png}", f"file://{page}")
            if not png.exists():
                sys.exit(f"chromium did not write {png}")
            hashes[png.name] = {"sha256": hashlib.sha256(png.read_bytes()).hexdigest(), "width": WIDTH, "height": L["h"]}
            print(f"wrote {png.relative_to(ROOT)}")
    (OUT / "ambiguity-alt.txt").write_text(alt_text(f) + "\n")
    (OUT / "ambiguity-manifest.json").write_text(json.dumps(
        {"title": TITLE, "alt_file": "ambiguity-alt.txt", "images": hashes}, indent=2) + "\n")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
