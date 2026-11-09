"""Build the public 'Try to scam Kavach' page (site/index.html).

The page runs the real guard in the browser with Pyodide, so the Python sources are inlined:
the kavach/ package from the repo root plus site/py/engine.py (the obedient AI and the JSON bridge).

  python site/build.py
"""
import json
import pathlib

here = pathlib.Path(__file__).resolve().parent
root = here.parent
modules = ["__init__", "agent", "bank", "detectors", "guard", "langs", "session", "tools"]
files = {f"kavach/{m}.py": (root / "kavach" / f"{m}.py").read_text(encoding="utf-8") for m in modules}
files["engine.py"] = (here / "py" / "engine.py").read_text(encoding="utf-8")
blob = json.dumps(files, ensure_ascii=False).replace("</", "<\\/")
body = (here / "template.html").read_text(encoding="utf-8").replace("__PYSRC__", blob)
page = ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n'
        + body.replace("<style>", "<style>\n:root{padding-top:env(safe-area-inset-top,0px)}", 1) + "\n</html>\n")
(here / "index.html").write_text(page, encoding="utf-8")
print(f"site/index.html: {len(page):,} bytes")
