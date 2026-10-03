# -*- coding: utf-8 -*-
"""Встраивает актуальные исходники APS.extension и prd.md в APS_Revit.html (блок filesData).
Запуск из корня проекта: python tools/sync_html.py"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "APS_Revit.html")
ORDER = [
    "APS.extension/lib/aps_rules.json",
    "APS.extension/lib/apsgeom.py",
    "APS.extension/lib/apslib.py",
]


def main():
    files = {}
    for rel in ORDER:
        files[rel] = None
    for base, _, names in os.walk(os.path.join(ROOT, "APS.extension")):
        for n in sorted(names):
            if n.endswith((".py", ".json", ".yaml")):
                rel = os.path.relpath(os.path.join(base, n), ROOT).replace(os.sep, "/")
                files.setdefault(rel, None)
    files["prd.md"] = None
    for rel in list(files):
        with io.open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            files[rel] = f.read().replace("\r\n", "\n")
    json.loads(files[ORDER[0]])  # правила должны быть валидным JSON
    payload = json.dumps(files, ensure_ascii=False).replace("</", "<\\/")
    with io.open(HTML, encoding="utf-8") as f:
        html = f.read()
    pat = re.compile(r'(<script type="application/json" id="filesData">)(.*?)(</script>)', re.S)
    if not pat.search(html):
        sys.exit("filesData не найден")
    html = pat.sub(lambda m: m.group(1) + payload + m.group(3), html, count=1)
    with io.open(HTML, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    print("filesData: %d файлов" % len(files))


if __name__ == "__main__":
    main()
