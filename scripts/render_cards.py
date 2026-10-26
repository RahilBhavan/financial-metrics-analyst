"""Render the two Eval Log cards as 1080x1080 PNGs in the Rahil Design charcoal / off-white / yellow system.

    uv run --with playwright==1.63.0 --with fonttools --with pillow --with numpy python scripts/render_cards.py

Cards: ambiguity (Microsoft FY2026, "Microsoft profit 2026" asks which profit) and restatement
(Kraft Heinz FY2017 operating income revision, a test fixture). Every number is read from
data/msft/ground-truth.json and data/reference-cases/khc/ground-truth.json; titles and alt text are
derived from the same values, and the script stops if a figure printed on a card disagrees with them.

It builds each card with Rahil Design's social_table template (390px authored canvas, exported at
1080x1080), measures the rendered text, audits every pixel against the tokens, and writes the
alt text, a feed check at 360px and 390px feeds, and a manifest with SHA-256 hashes. The design
bundle is read from --design-dir; its version and tokens hash are recorded in the manifest.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGES, EVIDENCE = ROOT / "docs" / "images", ROOT / "reports" / "cards"
DEFAULT_DESIGN = Path.home() / ".t3/projects/main/.agents/skills/rahil-design"
SIZE, CANVAS = 1080, 390
# Both cards carry a source, a fixture or parser limit and a date, so spacing steps down from the template's 18/14/10px
# to the tokens' space-3 (12px) and space-2 (8px); type sizes, fonts and colours are untouched.
TIGHT = "article{gap:12px}.figure{padding:12px;gap:8px}"
FEED_WIDTHS = {"feed-360": 326, "feed-390": 356}  # image width inside a 360px and a 390px feed


def short_date(iso):
    d = date.fromisoformat(iso)
    return f"{d:%b} {d.day}, {d.year}"


def billions(value):
    return f"${int(value) / 1e9:,.3f}B"


def millions(value):
    return f"${int(value) // 10**6:,}M"


def specs():
    msft = json.loads((ROOT / "data/msft/ground-truth.json").read_text())["years"]["2026"]
    manifest = json.loads((ROOT / "data/msft/manifest.json").read_text())
    khc = json.loads((ROOT / "data/reference-cases/khc/ground-truth.json").read_text())

    operating, net = billions(msft["operating_income"]), billions(msft["net_income"])
    title = f"${round(int(msft['operating_income']) / 1e9)}B operating.\n${round(int(msft['net_income']) / 1e9)}B net."
    snapshot = short_date(manifest["captured_at"][:10])
    year_end = short_date(msft["end"])
    ambiguity = {
        "id": "ambiguity", "title": title, "label_width": 62,
        "context": f"Microsoft FY2026 ended {year_end.rsplit(',', 1)[0]}",
        "rows": [{"label": "Operating income", "value": operating, "highlight": operating},
                 {"label": "Net income", "value": net}],
        "source": f"The parser offers these two for\n“profit”; not all its meanings.\nFY2026 10-K; data {snapshot}.",
        "alt": (f"{title.replace(chr(10), ' ')} Microsoft FY2026, the year ended {year_end}: operating income {operating} "
                f"and net income {net}. Asked for \"Microsoft profit 2026\", the parser offers these two choices; they "
                f"are not all the meanings of profit. Source: Microsoft FY2026 10-K, accession {msft['accession']}; "
                f"data snapshot {snapshot}."),
        "required": [operating, net, msft["accession"], snapshot, "not all the meanings of profit"],
    }

    original, recast = int(khc["original"]["value"]), int(khc["restated_and_recast"]["value"])
    error, presentation = original - int(khc["restated_before_recast"]), int(khc["restated_before_recast"]) - recast
    assert (error, presentation, original - recast) == (80 * 10**6, 636 * 10**6, 716 * 10**6), "KHC bridge changed"
    filed = short_date(khc["restated_and_recast"]["filed"])
    restatement = {
        "id": "restatement", "title": f"Only {millions(error)} was\nerror correction.", "label_width": 56,
        "context": f"Kraft Heinz FY2017 operating income: {millions(original - recast)} revision",
        "rows": [{"label": "Error correction", "value": millions(error), "highlight": millions(error)},
                 {"label": "Presentation\n(ASU 2017-07)", "value": millions(presentation)}],
        "source": f"SEC filing, {filed}.\nTest fixture, not a supported issuer.",
        "alt": (f"Only {millions(error)} was error correction. Kraft Heinz FY2017 operating income was revised by "
                f"{millions(original - recast)}, from {millions(original)} to {millions(recast)}: {millions(error)} error "
                f"correction plus {millions(presentation)} presentation change (ASU 2017-07). Source: SEC filing, {filed}. "
                f"Kraft Heinz is a test fixture in this project, not a supported issuer."),
        "required": [millions(error), millions(presentation), millions(original - recast), "ASU 2017-07", filed, "not a supported issuer"],
    }
    assert "June 7" not in restatement["alt"] + restatement["source"] and "Jun 7, 2019" in restatement["alt"]
    return [ambiguity, restatement]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_alt(spec):
    alt = spec["alt"]
    assert "\n" not in alt and "\r" not in alt and "  " not in alt and ".." not in alt, f"{spec['id']}: alt text is not one clean paragraph"
    missing = [r for r in spec["required"] if r not in alt]
    assert not missing, f"{spec['id']}: alt text lacks {missing}"


def render(html_path, png_path, firefox, measure):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True, executable_path=str(firefox))
        page = browser.new_page(viewport={"width": CANVAS, "height": CANVAS}, device_scale_factor=SIZE / CANVAS)
        page.goto(Path(html_path).resolve().as_uri())
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(300)
        measured = page.evaluate(measure)
        page.screenshot(path=str(png_path))
        browser.close()
    return measured


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--design-dir", type=Path, default=DEFAULT_DESIGN)
    ap.add_argument("--images", type=Path, default=IMAGES)
    ap.add_argument("--evidence", type=Path, default=EVIDENCE)
    ap.add_argument("--work", type=Path, required=True, help="scratch directory for the card HTML")
    args = ap.parse_args()
    sys.path.insert(0, str(args.design_dir / "scripts"))
    import social_bars as sb
    from PIL import Image
    from social_table import card_html

    tokens_path = args.design_dir / "assets/tokens.json"
    tokens = json.loads(tokens_path.read_text())
    for folder in (args.images, args.evidence, args.work):
        folder.mkdir(parents=True, exist_ok=True)
    cards, errors = [], []
    for spec in specs():
        check_alt(spec)
        highlighted = [r for r in spec["rows"] if r.get("highlight")]
        assert len(highlighted) == 1, "exactly one highlighted value"
        html_path, png = args.work / f"{spec['id']}.html", args.images / f"{spec['id']}-square.png"
        html_path.write_text(card_html(spec, tokens, sb.FONTS).replace("</style>", TIGHT + "</style>", 1))
        m = render(html_path, png, sb.FIREFOX, sb.MEASURE)
        sizes = [px for _, px in m["sizes"]]
        problems = [f"overflow: {o}" for o in m["overflow"]] + [f"font {f!r} is not a token font" for f in set(m["fonts"])]
        problems += [f"no glyph for {g}" for g in sb.missing_glyphs(m["glyphs"])] + sb.face_errors(m["faces"])
        problems += [f"text {min(sizes)}px below {sb.LABEL_PX}px"] * (min(sizes) < sb.LABEL_PX)
        image = Image.open(png)
        problems += [f"{png.name} is {image.size}, not {SIZE}x{SIZE}"] * (image.size != (SIZE, SIZE))
        audit = subprocess.run([sys.executable, str(args.design_dir / "scripts/pixel_audit.py"), str(png)], capture_output=True, text=True)
        problems += [f"pixel audit failed: {audit.stdout.strip()[-200:]}"] * bool(audit.returncode)
        pixels = audit.stdout.strip().split(": ", 1)[-1]
        (args.images / f"{spec['id']}-alt.txt").write_text(spec["alt"] + "\n")
        feeds = {}
        for name, width in FEED_WIDTHS.items():
            path = args.evidence / f"{spec['id']}-{name}.png"
            image.convert("RGB").resize((width, width), Image.LANCZOS).save(path)
            feeds[name] = {"file": path.name, "image_px": width, "sha256": sha(path)}
        brief = {"id": spec["id"], "title": spec["title"].replace("\n", " "), "system_version": sb.VERSION, "accents": 1,
                 "accent_meaning": "title-value", "sizes_checked": [f"{CANVAS}x{CANVAS}", f"{SIZE}x{SIZE}"],
                 "measurement_basis": "canvas", "measured_by": "social_bars/firefox", "min_label_px": min(sizes),
                 "point_px": max(sizes), "title_lines": m["title_lines"], "overflow": m["overflow"],
                 "source": spec["source"].replace("\n", " "), "alt": spec["alt"]}
        brief_path = args.evidence / f"{spec['id']}.brief.json"
        brief_path.write_text(json.dumps(brief, indent=2) + "\n")
        feed = subprocess.run([sys.executable, str(args.design_dir / "scripts/design_check.py"), "feed", str(brief_path)], capture_output=True, text=True)
        problems += [f"feed check: {feed.stdout.strip()}"] * bool(feed.returncode)
        cards.append({"id": spec["id"], "png": f"docs/images/{png.name}", "sha256": sha(png), "size": list(image.size),
                      "alt_file": f"docs/images/{spec['id']}-alt.txt", "alt_sha256": sha(args.images / f"{spec['id']}-alt.txt"),
                      "min_label_px": min(sizes), "title_px": max(sizes), "title_lines": m["title_lines"],
                      "pixel_audit": pixels, "feed_check": feed.stdout.strip().split(": ", 1)[-1], "feeds": feeds, "html": html_path})
        errors += [f"{spec['id']}: {p}" for p in problems]
    palette = subprocess.run([sys.executable, str(Path.home() / ".t3/projects/main/.agents/skills/dataviz/scripts/check_palette.py"),
                              "--tokens", str(tokens_path), *[str(c["html"]) for c in cards]], capture_output=True, text=True)
    report = json.loads(palette.stdout)
    for entry, card in zip(report["cards"], cards):
        entry["path"] = f"{card['id']} card HTML (rebuilt by this script, not committed)"
    (args.evidence / "palette-check.json").write_text(json.dumps(report, indent=2) + "\n")
    errors += report["errors"]
    for card in cards:
        del card["html"]
    manifest = {"design_system": "rahil-design", "version": (args.design_dir / "VERSION").read_text().strip(),
                "tokens_sha256": sha(tokens_path), "canvas_px": CANVAS, "export_px": SIZE, "cards": cards,
                "palette_check": "reports/cards/palette-check.json", "requested_version": "3.3.2: charcoal #111214, off-white #F5F5EF, yellow #FFE500, Anton and IBM Plex Sans, unchanged in the tokens since",
                "design_review": "pending: no named reviewer has passed these exact bytes"}
    (args.evidence / "cards-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for card in cards:
        print(f"{card['png']} {card['sha256']} labels {card['min_label_px']}px title {card['title_px']}px | {card['pixel_audit']} | {card['feed_check']}")
    print("palette check:", "passed" if report["passed"] else "FAILED")
    print("\n".join(errors) or "ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
