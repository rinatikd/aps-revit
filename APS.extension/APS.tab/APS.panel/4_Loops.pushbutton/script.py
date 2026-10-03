# -*- coding: utf-8 -*-
"""Шлейфы: деление на ЗКПС, разбивка адресных устройств на ДПЛС (Болид) / АЛС (Рубеж) с изоляторами КЗ,
адресация, длины кабеля, проверка сближения с силовыми лотками."""
__title__ = u"4. Шлейфы"
__doc__ = u"ЗКПС, шлейфы с изоляторами КЗ (кольцо/радиал), адреса, длины кабеля"

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
ring = lp.get("topology") == "ring"
idev = ven.get("isolator") or {}

cap = int(ven["max_addresses_per_loop"] * ven.get("loop_fill_ratio", 1.0))
on_loop_roles = [k for k, v in ven["devices"].items() if v.get("on_loop", True)]

fam_map = {}
for v in rules["vendors"].values():
    for role, d in v["devices"].items():
        fam_map[d["family"]] = role
    if v.get("isolator"):
        fam_map[v["isolator"]["family"]] = "isolator"


def comment_parts(el):
    res = {}
    for part in apslib.comments(el).split(u";"):
        if u"=" in part:
            k, val = part.split(u"=", 1)
            res[k] = val
    return res


# устройства: всё категории «Пожарная сигнализация» в хосте, кроме прибора, неадресных ролей и старых изоляторов
devs, old_iso = [], []
for el in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_FireAlarmDevices).WhereElementIsNotElementType():
    fam = el.Symbol.Family.Name if hasattr(el, "Symbol") else u""
    if fam == ven["panel"]["family"]:
        continue
    cp = comment_parts(el)
    role = cp.get(u"role") or fam_map.get(fam)
    if role == "isolator":
        if marker in apslib.comments(el):
            old_iso.append(el.Id)
        continue
    if role is not None and role not in on_loop_roles:
        continue
    loc = el.Location
    if not isinstance(loc, DB.LocationPoint):
        continue
    p = loc.Point
    lvl = doc.GetElement(el.LevelId)
    try:
        area = float(cp.get(u"rarea") or 0)
    except ValueError:
        area = 0.0
    devs.append({"el": el, "role": role or "smoke", "model": u"", "x": apslib.to_mm(p.X), "y": apslib.to_mm(p.Y),
                 "z": apslib.to_mm(p.Z), "level": lvl.Name if lvl else u"?",
                 "lz": apslib.to_mm(lvl.ProjectElevation) if lvl else 0,
                 "room": cp.get(u"room", u""), "room_no": cp.get(u"rno", u""), "room_name": cp.get(u"rname", u""),
                 "room_apt": cp.get(u"rapt", u""),
                 "room_area": area})

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
    panel_xyz = (start[0], start[1], apslib.to_mm(panel.Z))
else:
    start = (min(d["x"] for d in devs), min(d["y"] for d in devs))
    panel_xyz = None

# ЗКПС и шлейфы — та же логика, что в HTML-предпросмотре
zones = apsgeom.assign_zones(devs, rules, start)
zoned = rules.get("zones", {}).get("enabled") or rules.get("isolators", {}).get("enabled")
if zoned:
    n_loops = apsgeom.plan_loops(devs, start, cap, ven["loop_name"], on_loop_roles, rules, ven)
else:
    n_loops = apsgeom.assign_loops(devs, start, cap, ven["loop_name"], on_loop_roles)
zone_by_id = dict((z["id"], z) for z in zones)

# силовые лотки/короба для проверки сближения
power = []
lines, _ = apslib.collect_obstacles(doc)
for o in lines:
    if o["kind"] in ("cable_tray", "conduit") and not any(k.lower() in o["type"].lower() for k in lp["low_current_keywords"]):
        power.append(o)

iso_sym = apslib.find_symbol(doc, idev["family"], idev.get("type", u"")) if idev else None
levels = apslib.host_levels(doc)
issues, placed_iso, missing_iso = [], 0, 0

with revit.Transaction(u"АПС: ЗКПС, шлейфы, изоляторы, адресация"):
    if old_iso:
        doc.Delete(apslib.fam_list(old_iso))
    for d in devs:
        if not d.get("loop"):
            continue
        z = zone_by_id.get(d.get("zone") or u"")
        if d["role"] == "isolator":
            if iso_sym is None:
                missing_iso += 1
                continue
            inst = apslib.place(doc, iso_sym, apslib.level_for_z(levels, d["lz"]), d["x"], d["y"], d["z"])
            d["el"] = inst
            placed_iso += 1
        el = d["el"]
        ok1 = apslib.set_text(el, names["loop"], d["loop"])
        ok2 = apslib.set_text(el, names["address"], d["addr"])
        apslib.set_text(el, names.get("zone", u"АПС_ЗКПС"), d.get("zone") or u"")
        keep = [s for s in apslib.comments(el).split(u";")
                if s and not s.split(u"=", 1)[0] in (u"loop", u"addr", u"seq", u"zone", u"zkind", u"ztitle")]
        if d["role"] == "isolator":
            keep = [marker, u"role=isolator"]
        add = [u"seq={}".format(d["seq"])] if d.get("seq") else []
        if not (ok1 and ok2):
            add += [u"loop=" + d["loop"], u"addr={}".format(d["addr"])]
        if z:
            add += [u"zone=" + z["id"], u"zkind=" + z["kind"], u"ztitle=" + z["title"].replace(u";", u",")]
        apslib.set_comments(el, u";".join(keep + add))

    # сближение с силовыми трассами — по порядку обхода линии
    loops = {}
    for d in devs:
        if d.get("loop"):
            loops.setdefault(d["loop"], []).append(d)
    for lid, items in loops.items():
        items.sort(key=lambda q: q.get("seq") or 0)
        path = [start] + [(q["x"], q["y"]) for q in items]
        hits = 0
        lz = items[0]["lz"]
        for a, b in zip(path, path[1:]):
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
            issues.append([items[0]["level"], lid, u"{} точек трассы ближе {:.0f} мм к силовым лоткам/коробам".format(hits, lp["power_clear"])])

# отчёт: длины по build_docs (тот же расчёт, что в кнопке «6» и в HTML)
for d in devs:
    if not d["model"]:
        d["model"] = ven["devices"].get(d["role"], {}).get("model", d["role"]) if d["role"] != "isolator" else idev.get("model", u"")
docs = apsgeom.build_docs([d for d in devs if d.get("loop")], panel_xyz, ven, rules)
n_iso = len([d for d in devs if d["role"] == "isolator"])

out.print_md(u"## Шлейфы — {} ({} до {} адресов, заполнение {:.0%}, {})".format(
    ven["title"], ven["loop_name"], ven["max_addresses_per_loop"], ven.get("loop_fill_ratio", 1.0),
    u"кольцо" if ring else u"радиальная"))
out.print_table([[r["line"], r["count"], u"{:.1f}".format(r["length_m"])] for r in docs["scheme"] if r["kind"] == "loop"],
                columns=[u"Линия", u"Устройств (с изоляторами)", u"Кабель, м (оценка)"])
if zones:
    out.print_md(u"### ЗКПС: {}".format(len(zones)))
    out.print_table([[z["id"], z["level"], z["title"], z["count"], z["area_m2"]] for z in zones],
                    columns=[u"ЗКПС", u"Уровень", u"Состав", u"ИП", u"м²"])
out.print_md(u"Изоляторов КЗ: **{}** ({}). Размещено семейств: {}.".format(n_iso, idev.get("model", u"—"), placed_iso))
if missing_iso:
    issues.append([u"—", u"изоляторы", u"семейство «{}» не загружено: {} изоляторов только в отчёте и спецификации".format(
        idev.get("family", u""), missing_iso)])
if issues:
    out.print_md(u"### Требует внимания")
    out.print_table(issues, columns=[u"Уровень", u"Шлейф", u"Замечание"])
out.print_md(u"Длина — оценка по ортогональной трассе (без обхода препятствий){}. Окончательные трассы — по проекту.".format(
    u", с возвратом кольца к прибору" if ring else u""))
