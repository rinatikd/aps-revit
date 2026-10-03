# -*- coding: utf-8 -*-
"""Сравнение Python-версии apsgeom с JS-портом на выходе tools/parity.js.
python tools/parity_check.py out.json"""
import copy
import io
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "APS.extension", "lib"))
import apsgeom  # noqa: E402


def norm(o):
    """Приводит структуры к виду JSON (кортежи → списки, ключи → строки)."""
    return json.loads(json.dumps(o, ensure_ascii=False))


def diff(a, b, path="", out=None):
    out = [] if out is None else out
    if len(out) > 12:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append("%s.%s: только в %s" % (path, k, "py" if k in a else "js"))
            else:
                diff(a[k], b[k], path + "." + k, out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append("%s: длина py %d js %d" % (path, len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, "%s[%d]" % (path, i), out)
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        if abs(a - b) > 1e-6 * max(1.0, abs(a), abs(b)):
            out.append("%s: py %r js %r" % (path, a, b))
    elif a != b:
        out.append("%s: py %r js %r" % (path, a, b))
    return out


def main():
    with io.open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
    lines, points = data["obstacles"]["lines"], data["obstacles"]["points"]
    bad = 0
    for c in data["cases"]:
        rules = copy.deepcopy(c["rules"])
        ven = rules["vendors"][rules["active_vendor"]]
        devs = copy.deepcopy(c["devs_in"])
        panel = tuple(c["panel"]) if c["panel"] else None
        start = tuple(c["start"])
        zones = apsgeom.assign_zones(devs, rules, start)
        if c["planned"]:
            n = apsgeom.plan_loops(devs, start, c["cap"], ven["loop_name"], c["onLoop"], rules, ven)
        else:
            n = apsgeom.assign_loops(devs, start, c["cap"], ven["loop_name"], c["onLoop"])
        docs = apsgeom.full_docs(devs, panel, ven, rules)
        checks = apsgeom.check_project(docs, devs, zones, rules, ven)
        dxf = apsgeom.dxf_plan(c["rooms"], lines, points, devs, panel, zones, rules["loops"].get("topology") == "ring")
        py = norm({"n_loops": n, "zones": zones, "devs": devs, "docs": docs, "checks": checks})
        js = {k: c["out"][k] for k in ("n_loops", "zones", "devs", "docs", "checks")}
        d = diff(py, js)
        if dxf != c["out"]["dxf"]:
            pl, jl = dxf.split("\n"), c["out"]["dxf"].split("\n")
            k = next((i for i, (x, y) in enumerate(zip(pl, jl)) if x != y), min(len(pl), len(jl)))
            d.append("dxf: строка %d py %r js %r (строк py %d js %d)" % (k, pl[k] if k < len(pl) else None,
                                                                         jl[k] if k < len(jl) else None, len(pl), len(jl)))
        print(("OK   " if not d else "FAIL ") + c["name"])
        for x in d:
            print("     " + x)
        bad += bool(d)
    print("итого: %d из %d вариантов совпадают" % (len(data["cases"]) - bad, len(data["cases"])))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
