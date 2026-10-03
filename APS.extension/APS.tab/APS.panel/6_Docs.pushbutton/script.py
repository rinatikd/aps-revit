# -*- coding: utf-8 -*-
"""Документация по модели АПС: структурная схема (чертёжный вид Revit), кабельный журнал и
спецификация оборудования, изделий и материалов (CSV для Excel)."""
__title__ = u"6. Схема, СО,\nжурнал, DXF"
__doc__ = u"Структурная схема, кабельный журнал, спецификация, расчёт АЛС/ДПЛС, подбор сечения и АКБ"

import io
import os

from pyrevit import revit, script, forms
from Autodesk.Revit import DB

import apslib
import apsgeom

doc = revit.doc
out = script.get_output()
rules = apslib.load_rules(doc)
ven = apslib.vendor(rules)
names = rules["params"]
sep = rules["documentation"].get("csv_separator", u";")

# --- семейство -> (роль, модель) по всем производителям
fam_map = {}
for v in rules["vendors"].values():
    for role, d in v["devices"].items():
        fam_map[d["family"]] = (role, d["model"])
    if v.get("isolator"):
        fam_map[v["isolator"]["family"]] = ("isolator", v["isolator"]["model"])
ring = rules["loops"].get("topology") == "ring"


def param_or_comment(el, pname, key):
    p = el.LookupParameter(pname)
    if p is not None and p.HasValue:
        val = p.AsString() if p.StorageType == DB.StorageType.String else p.AsValueString()
        if val:
            return val
    for part in apslib.comments(el).split(u";"):
        if part.startswith(key + u"="):
            return part[len(key) + 1:]
    return u""


devs, panel = [], None
for el in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_FireAlarmDevices).WhereElementIsNotElementType():
    loc = el.Location
    if not isinstance(loc, DB.LocationPoint):
        continue
    fam = el.Symbol.Family.Name
    p = loc.Point
    xyz = (apslib.to_mm(p.X), apslib.to_mm(p.Y), apslib.to_mm(p.Z))
    if fam == ven["panel"]["family"]:
        panel = xyz
        continue
    role = param_or_comment(el, u"__none__", u"role") or fam_map.get(fam, (u"other", u""))[0]
    model = fam_map.get(fam, (role, u""))[1] or u"{} : {}".format(fam, el.Name)
    lvl = doc.GetElement(el.LevelId)
    tap = param_or_comment(el, u"__none__", u"tap")
    seq = param_or_comment(el, u"__none__", u"seq")
    addr = param_or_comment(el, names["address"], u"addr")
    devs.append({
        "power_w": float(tap) if tap else 0.0,
        "role": role, "model": model,
        "level": lvl.Name if lvl else u"?", "lz": apslib.to_mm(lvl.ProjectElevation) if lvl else 0.0,
        "x": xyz[0], "y": xyz[1], "z": xyz[2],
        "loop": param_or_comment(el, names["loop"], u"loop"),
        "addr": int(addr) if addr.isdigit() else addr,
        "seq": int(seq) if seq.isdigit() else 0,
        "room": param_or_comment(el, names["room"], u"room"),
        "room_no": param_or_comment(el, u"__none__", u"rno"),
        "room_name": param_or_comment(el, u"__none__", u"rname"),
        "room_area": float(param_or_comment(el, u"__none__", u"rarea") or 0),
        "zone": param_or_comment(el, names.get("zone", u"АПС_ЗКПС"), u"zone"),
        "zkind": param_or_comment(el, u"__none__", u"zkind"),
        "ztitle": param_or_comment(el, u"__none__", u"ztitle"),
    })

if not devs:
    forms.alert(u"В модели нет устройств категории «Пожарная сигнализация».", exitscript=True)
if not any(d["loop"] for d in devs if d["role"] != "sounder"):
    forms.alert(u"У устройств не заполнены шлейф/адрес — сначала запусти «4. Шлейфы».", exitscript=True)

res = apsgeom.full_docs(devs, panel, ven, rules)
elec = res["electrics"]
pb = res["power"]
el_by_line = dict((e["line"], e) for e in elec)

# --- ЗКПС из параметров устройств (их записала кнопка «4») и автопроверка проекта
zones, zmap = [], {}
for d in devs:
    zid = d.get("zone")
    if not zid:
        continue
    if zid not in zmap:
        zmap[zid] = {"id": zid, "n": len(zmap) + 1, "level": d["level"], "lz": d["lz"], "kind": d.get("zkind") or u"rooms",
                     "title": d.get("ztitle") or u"", "rooms": [], "area_m2": 0.0, "count": 0, "items": []}
        zones.append(zmap[zid])
    z = zmap[zid]
    z["count"] += 1
    z["items"].append(d)
    if d["room"] not in z["rooms"]:
        z["rooms"].append(d["room"])
        z["area_m2"] += d.get("room_area") or 0.0
for z in zones:
    cx, cy = apsgeom._centroid(z.pop("items"))
    z["cx"], z["cy"], z["area_m2"] = apsgeom.rnd(cx, 1), apsgeom.rnd(cy, 1), apsgeom.rnd(z["area_m2"], 1)
checks = apsgeom.check_project(res, devs, zones, rules, ven)

# --- CSV (UTF-8 с BOM — Excel открывает кириллицу корректно)
folder = forms.pick_folder(title=u"Папка для кабельного журнала и спецификации")
if not folder:
    script.exit()


def write_csv(name, header, rows):
    path = os.path.join(folder, name)
    with io.open(path, "w", encoding="utf-8-sig") as f:
        f.write(sep.join(header) + u"\r\n")
        for r in rows:
            f.write(sep.join(u"{}".format(c).replace(sep, u",") for c in r) + u"\r\n")
    return path


p1 = write_csv(u"АПС_Кабельный_журнал.csv",
               [u"Обозначение", u"Линия", u"Начало", u"Конец", u"Помещение", u"Марка кабеля", u"Длина, м"],
               [[j["mark"], j["line"], j["from"], j["to"], j["room"], j["cable"], j["length_m"]] for j in res["journal"]])
p2 = write_csv(u"АПС_Спецификация.csv",
               [u"Поз.", u"Наименование и техническая характеристика", u"Тип, марка, обозначение документа",
                u"Код продукции", u"Поставщик", u"Ед. измерения", u"Кол.", u"Масса единицы, кг", u"Примечание"],
               [[s["pos"], s["name"], s["mark"], u"", s["maker"], s["unit"], s["qty"], u"", s["note"]] for s in res["spec"]])

p3 = write_csv(u"АПС_Расчёт_линий.csv",
               [u"Линия", u"Устройств", u"Кабель (подобран)", u"Длина, м", u"U нач., В", u"I дежурный, мА", u"I макс., мА",
                u"R линии (2 жилы), Ом", u"ΔU макс., В", u"U в конце, В", u"Результат"],
               [[e["line"], e["count"], e["cable"], e["length_m"], e["u0_v"], e["i_standby_ma"], e["i_max_ma"],
                 e["r_loop_ohm"], e["du_max_v"], e["u_end_max_v"],
                 u"норма" if e["ok"] else u"; ".join(e["checks"])] for e in elec])

p5 = write_csv(u"АПС_Проверка_проекта.csv", [u"Статус", u"Требование", u"Результат", u"Пункт"],
               [[k["status"], k["title"], k["detail"], k["ref"]] for k in checks])
p6 = write_csv(u"АПС_ЗКПС.csv", [u"ЗКПС", u"Уровень", u"Состав", u"Помещения", u"Площадь, м²", u"ИП, шт."],
               [[z["id"], z["level"], z["title"], u"; ".join(z["rooms"]), z["area_m2"], z["count"]] for z in zones])

p4 = write_csv(u"АПС_Расчёт_АКБ.csv", [u"Потребитель", u"I дежурный, мА", u"I тревога, мА"],
               [[r["name"], r["standby_ma"], r["alarm_ma"]] for r in pb["rows"]] +
               [[u"ИТОГО, А", pb["i_standby_a"], pb["i_alarm_a"]], [pb["formula"], u"", u""],
                [u"Принято: {} × {} В {} А·ч".format(pb["blocks"], pb["block_v"], pb["battery_ah"] or u"— (нет в ряду)"), u"", u""]])

# --- планы для AutoCAD (DXF R12, кодировка 1251; блоки APS_* переопредели своими УГО)
rooms_all = apslib.collect_rooms(doc)
lines_o, points_o = apslib.collect_obstacles(doc)
levels = apslib.host_levels(doc)
dxf_files = []
for lv in levels:
    lv_devs = [d for d in devs if d["level"] == lv.Name]
    if not lv_devs:
        continue
    lv_rooms = [r for r in rooms_all if apslib.level_for_z(levels, r["floor_z"]).Id == lv.Id]
    txt = apsgeom.dxf_plan(lv_rooms, lines_o, points_o, lv_devs, panel, zones, ring)
    name = u"АПС_план_{}.dxf".format(lv.Name)
    for ch in u'\\/:*?"<>|':
        name = name.replace(ch, u"_")
    pth = os.path.join(folder, name)
    with io.open(pth, "w", encoding="cp1251", errors="replace", newline=u"\r\n") as f:
        f.write(txt)
    dxf_files.append(pth)

# --- структурная схема на чертёжном виде (масштаб 1:1 → координаты = мм на листе)
FT = apslib.to_ft
with revit.Transaction(u"АПС: структурная схема"):
    vft = [t for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType)
           if t.ViewFamily == DB.ViewFamily.Drafting][0]
    title = u"АПС — Структурная схема ({})".format(ven["title"])
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewDrafting):
        if v.Name == title:
            doc.Delete(v.Id)
    view = DB.ViewDrafting.Create(doc, vft.Id)
    view.Name = title
    view.Scale = 1
    tnt = DB.FilteredElementCollector(doc).OfClass(DB.TextNoteType).FirstElementId()

    def line(x1, y1, x2, y2):
        doc.Create.NewDetailCurve(view, DB.Line.CreateBound(DB.XYZ(FT(x1), FT(y1), 0), DB.XYZ(FT(x2), FT(y2), 0)))

    def rect(x, y, w, h):
        line(x, y, x + w, y); line(x + w, y, x + w, y - h); line(x + w, y - h, x, y - h); line(x, y - h, x, y)

    def text(x, y, s):
        DB.TextNote.Create(doc, view.Id, DB.XYZ(FT(x), FT(y), 0), s, tnt)

    rows = res["scheme"]
    H = max(60.0, 40.0 * len(rows))
    rect(0, 0, 60, H)
    text(3, -4, u"{}\n{}".format(ven["panel"]["model"], ven.get("manufacturer", u"")))
    BOXW, GAP = 55.0, 10.0
    for i, r in enumerate(rows):
        y = -20.0 - 40.0 * i
        x = 60.0
        e = el_by_line.get(r["line"], {})
        text(x + 3, y + 9, u"{}  {}, {} м;  Iмакс {} мА;  Uкон {} В".format(
            r["line"], r["cable"], r["length_m"], e.get("i_max_ma", u"—"), e.get("u_end_max_v", u"—")))
        for g in r["groups"]:
            line(x, y, x + GAP, y)
            x += GAP
            rect(x, y + 12, BOXW, 24)
            txt = g["level"] + u"\n" + u"\n".join(u"{} — {} шт.".format(m, c) for m, c in sorted(g["models"].items()))
            text(x + 2, y + 10, txt)
            x += BOXW

out.print_md(u"## Документация АПС — {}".format(ven["title"]))
out.print_md(u"### Структурная схема\nСоздан чертёжный вид **{}** — размести его на листе. Он выгружается в DWG кнопкой «5».".format(title))
out.print_table([[r["line"], r["count"], r["cable"], r["length_m"]] for r in res["scheme"]],
                columns=[u"Линия", u"Устройств", u"Кабель", u"Длина, м"])
out.print_md(u"### Расчёт линий: токопотребление и падение напряжения ({} / СОУЭ)".format(ven["loop_name"]))
if any(e["demo"] for e in elec):
    out.print_md(u"**ВНИМАНИЕ: в aps_rules.json стоят демо-значения токов и напряжений. Перед выпуском документации заменить по паспортам.**")
out.print_table([[e["line"], e["count"], e["length_m"], e["i_standby_ma"], e["i_max_ma"], e["r_loop_ohm"],
                  e["du_max_v"], e["u_end_max_v"], u"норма" if e["ok"] else u"; ".join(e["checks"])] for e in elec],
                columns=[u"Линия", u"Устр.", u"L, м", u"Iдеж, мА", u"Iмакс, мА", u"R, Ом", u"ΔU, В", u"Uкон, В", u"Проверка"])
if ring:
    out.print_md(u"Кольцо: ΔU — худший случай по перебору места обрыва (каждая половина питается со своего конца); "
                 u"R — две жилы до самого удалённого устройства при обрыве. В норме кольцо питается с двух концов.")
else:
    out.print_md(u"Расчёт для радиальной линии. Ток участка = сумма токов всех устройств после него.")
STAT = {"ok": u"✅", "warn": u"⚠️", "fail": u"❌", "info": u"ℹ️"}
out.print_md(u"### Проверка проекта (справочно СП 484.1311500.2020 с Изм. №1, СП 6.13130.2021; для РК — сверить с СП РК 2.02-102-2022)")
out.print_table([[STAT.get(k["status"], k["status"]), k["title"], k["detail"], k["ref"]] for k in checks],
                columns=[u"", u"Требование", u"Результат", u"Пункт"])
if zones:
    out.print_md(u"ЗКПС: **{}**, файл `{}`".format(len(zones), p6))
out.print_md(u"### Резервное питание ({:.0f} ч дежурный + {:.0f} ч тревога)".format(pb["t_standby_h"], pb["t_alarm_h"]))
out.print_table([[r["name"], r["standby_ma"], r["alarm_ma"]] for r in pb["rows"]],
                columns=[u"Потребитель", u"Iдеж, мА", u"Iтрев, мА"])
out.print_md(u"`{}` → принято **{} × {} В {} А·ч**".format(pb["formula"], pb["blocks"], pb["block_v"],
                                                          pb["battery_ah"] or u"— (больше ряда, разделить на несколько РИП)"))
out.print_md(u"### Спецификация (ГОСТ 21.110)")
out.print_table([[s["pos"], s["name"], s["mark"], s["unit"], s["qty"], s["note"]] for s in res["spec"]],
                columns=[u"Поз.", u"Наименование", u"Марка", u"Ед.", u"Кол.", u"Примечание"])
out.print_md(u"Кабельный журнал: **{}** строк.\n\nФайлы:\n- `{}`\n- `{}`\n- `{}`\n- `{}`".format(len(res["journal"]), p1, p2, p3, p4))
if dxf_files:
    out.print_md(u"### Для AutoCAD\nПланы по уровням (DXF, слои АПС_*, блоки APS_*): " + u", ".join(u"`{}`".format(x) for x in dxf_files) +
                 u"\n\nОткрой в AutoCAD и сохрани как DWG. Переопредели блоки APS_SMOKE, APS_HEAT, APS_MCP, APS_SOUNDER, APS_SPEAKER, APS_PANEL, APS_ISO своими УГО — все вставки обновятся. Номера ЗКПС — на слое АПС_ЗКПС.")
out.print_md(u"Длины — оценка по ортогональным трассам с запасом из правил. После трассировки в модели сверь их с фактическими.")
