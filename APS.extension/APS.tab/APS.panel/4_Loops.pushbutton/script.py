# -*- coding: utf-8 -*-
"""Шлейфы: разбивка адресных устройств на ДПЛС (Болид) / АЛС (Рубеж), адресация, длины кабеля,
проверка сближения с силовыми лотками."""
__title__ = u"4. Шлейфы"
__doc__ = u"Разбить устройства на шлейфы, присвоить адреса, посчитать кабель"

import math

from pyrevit import revit, script, forms
from Autodesk.Revit import DB

import apslib
import apsgeom

doc = revit.doc
out = script.get_output()
rules = apslib.load_rules(doc)
ven = apslib.vendor(rules)
lp = rules["loops"]
names = rules["params"]
marker = names["marker"]

cap = int(ven["max_addresses_per_loop"] * ven.get("loop_fill_ratio", 1.0))
on_loop_roles = [k for k, v in ven["devices"].items() if v.get("on_loop", True)]

# устройства: всё категории «Пожарная сигнализация» в хосте, кроме неадресных ролей
devs = []
for el in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_FireAlarmDevices).WhereElementIsNotElementType():
    c = apslib.comments(el)
    role = None
    for part in c.split(u";"):
        if part.startswith(u"role="):
            role = part[5:]
    if role is not None and role not in on_loop_roles:
        continue
    fam = el.Symbol.Family.Name if hasattr(el, "Symbol") else u""
    if fam == ven["panel"]["family"]:
        continue
    loc = el.Location
    if not isinstance(loc, DB.LocationPoint):
        continue
    p = loc.Point
    lvl = doc.GetElement(el.LevelId)
    devs.append({"el": el, "x": apslib.to_mm(p.X), "y": apslib.to_mm(p.Y), "z": apslib.to_mm(p.Z),
                 "level": lvl.Name if lvl else u"?", "lz": apslib.to_mm(lvl.ProjectElevation) if lvl else 0})

if not devs:
    forms.alert(u"Нет устройств категории «Пожарная сигнализация» в модели.", exitscript=True)

# прибор / контроллер — точка старта
panel = None
for el in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_FireAlarmDevices).WhereElementIsNotElementType():
    if el.Symbol.Family.Name == ven["panel"]["family"] and isinstance(el.Location, DB.LocationPoint):
        panel = el.Location.Point
        break
if panel is not None:
    start = (apslib.to_mm(panel.X), apslib.to_mm(panel.Y))
    panel_z = apslib.to_mm(panel.Z)
else:
    start = (min(d["x"] for d in devs), min(d["y"] for d in devs))
    panel_z = None

# силовые лотки/короба для проверки сближения
power = []
lines, _ = apslib.collect_obstacles(doc)
for o in lines:
    if o["kind"] in ("cable_tray", "conduit") and not any(k.lower() in o["type"].lower() for k in lp["low_current_keywords"]):
        power.append(o)

by_level = {}
for d in devs:
    by_level.setdefault((d["lz"], d["level"]), []).append(d)

report, issues = [], []
loop_no = 0
total_cable = 0.0

with revit.Transaction(u"АПС: шлейфы и адресация"):
    for (lz, lname) in sorted(by_level.keys()):
        items = by_level[(lz, lname)]
        order = apsgeom.order_nearest([(i, d["x"], d["y"]) for i, d in enumerate(items)], start)
        for part in apsgeom.chunk(order, cap):
            loop_no += 1
            lid = u"{}{}".format(ven["loop_name"], loop_no)
            path = [start] + [(p[1], p[2]) for p in part]
            length = apsgeom.manhattan_len(path)
            avg_z = sum(items[p[0]]["z"] for p in part) / len(part)
            length += abs(avg_z - (panel_z if panel_z is not None else avg_z))
            length += 2 * lp["drop_per_device"] * len(part)
            length *= (1 + lp["cable_reserve"])
            total_cable += length
            for addr, p in enumerate(part, 1):
                el = items[p[0]]["el"]
                ok1 = apslib.set_text(el, names["loop"], lid)
                ok2 = apslib.set_text(el, names["address"], addr)
                if not (ok1 and ok2):
                    c = apslib.comments(el)
                    keep = [s for s in c.split(u";") if not s.startswith(u"loop=") and not s.startswith(u"addr=")]
                    apslib.set_comments(el, u";".join(keep + [u"loop=" + lid, u"addr={}".format(addr)]))
            # сближение с силовыми трассами
            hits = 0
            for a, b in zip(path[1:], path[2:]):
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                n = max(1, int(L / 500))
                for k in range(n + 1):
                    x = a[0] + (b[0] - a[0]) * k / n
                    y = a[1] + (b[1] - a[1]) * k / n
                    for o in power:
                        if o["z_bot"] < lz - 500 or o["z_bot"] > lz + 6000:
                            continue
                        if apsgeom.dist_point_seg(x, y, o["x1"], o["y1"], o["x2"], o["y2"]) < o["hw"] + lp["power_clear"]:
                            hits += 1
                            break
            if hits:
                issues.append([lname, lid, u"{} точек трассы ближе {:.0f} мм к силовым лоткам/коробам".format(hits, lp["power_clear"])])
            report.append([lname, lid, len(part), u"{:.1f}".format(length / 1000.0)])

    # провода на активном плане (опционально)
    view = doc.ActiveView
    if lp.get("draw_wires_in_active_plan") and isinstance(view, DB.ViewPlan):
        wt = DB.FilteredElementCollector(doc).OfClass(DB.Electrical.WireType).FirstElement()
        drawn = 0
        for (lz, lname), items in by_level.items():
            if view.GenLevel is None or view.GenLevel.Name != lname:
                continue
            order = apsgeom.order_nearest([(i, d["x"], d["y"]) for i, d in enumerate(items)], start)
            for a, b in zip(order, order[1:]):
                try:
                    ca = list(items[a[0]]["el"].MEPModel.ConnectorManager.Connectors)[0]
                    cb = list(items[b[0]]["el"].MEPModel.ConnectorManager.Connectors)[0]
                    z = view.GenLevel.ProjectElevation
                    pts = apslib.List[DB.XYZ]([DB.XYZ(ca.Origin.X, ca.Origin.Y, z), DB.XYZ(cb.Origin.X, cb.Origin.Y, z)])
                    DB.Electrical.Wire.Create(doc, wt.Id, view.Id, DB.Electrical.WiringType.Arc, pts, ca, cb)
                    drawn += 1
                except Exception as ex:
                    issues.append([lname, u"провод", u"{}".format(ex)])
                    break
        out.print_md(u"Нарисовано проводов на текущем плане: {}".format(drawn))

out.print_md(u"## Шлейфы — {} ({} до {} адресов, заполнение {:.0%})".format(
    ven["title"], ven["loop_name"], ven["max_addresses_per_loop"], ven.get("loop_fill_ratio", 1.0)))
out.print_table(report, columns=[u"Уровень", u"Шлейф", u"Устройств", u"Кабель, м (оценка)"])
out.print_md(u"**Итого кабеля (оценка с запасом {:.0%}):** {:.0f} м".format(lp["cable_reserve"], total_cable / 1000.0))
if issues:
    out.print_md(u"### Требует внимания")
    out.print_table(issues, columns=[u"Уровень", u"Шлейф", u"Замечание"])
out.print_md(u"Длина — оценка по ортогональной трассе (без обхода препятствий). Окончательные трассы — по проекту.")
