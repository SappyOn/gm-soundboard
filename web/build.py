"""Assemble public/ from the desktop UI + browser backend."""
import json, re, shutil, pathlib
root = pathlib.Path(__file__).parent
ui = root.parent / "desktop" / "ui"
pub = root / "public"
for f in ("app.js", "style.css"):
    shutil.copy(ui / f, pub / f)
starter = json.loads((root / "starter.json").read_text())
js = (root / "src" / "webapi.js").read_text().replace("/*STARTER_JSON*/[]", json.dumps(starter, ensure_ascii=False))
(pub / "webapi.js").write_text(js)
html = (ui / "index.html").read_text()
html = html.replace('<script src="app.js"></script>', '<script src="webapi.js"></script>\n<script src="app.js"></script>')
html = html.replace('<link rel="stylesheet" href="style.css">', '<meta name="description" content="Hotkey sound board for tabletop game masters">\n<link rel="icon" href="favicon.png">\n<link rel="stylesheet" href="style.css">')
(pub / "index.html").write_text(html)
print("built", sorted(p.name for p in pub.iterdir()))
