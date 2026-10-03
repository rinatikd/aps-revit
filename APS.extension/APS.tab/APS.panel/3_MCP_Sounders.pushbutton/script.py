# -*- coding: utf-8 -*-
"""ИПР у эвакуационных выходов и оповещатели в коридорах/холлах."""
__title__ = u"3. ИПР и\nоповещение"
__doc__ = u"ИПР у выходов; звуковые оповещатели или громкоговорители речевого оповещения по расчёту уровня звука"

import math

from pyrevit import revit, script, forms
from Autodesk.Revit import DB

import apslib
import apsgeom

doc = revit.doc
out = script.get_output()
rules = apslib.load_rules(doc)
ven = apslib.vendor(rules)
mcp = rules["mcp"]
snd = rules["sounders"]
marker = rules["params"]["marker"]


def sym(role):
    d = ven["devices"][role]
    s = apslib.find_symbol(doc, d["family"], d.get("type", u""))
    if s is None:
        forms.alert(u"Не найдено семейство «{}» ({}).".format(d["family"], d["model"]), exitscript=True)
    return s


def has_kw(name, kws):
    low = (name or u"").lower()
    return any(k.lower() in low for k in kws)


def room_name(r):
    return apslib.pname(r, DB.BuiltInParameter.ROOM_NAME) if r is not None else u""


levels = apslib.host_levels(doc)
s_mcp, s_snd = sym("mcp"), sym("sounder")
do_mcp = forms.alert(u"Ставить ИПР у выходов?", yes=True, no=True)
do_snd = snd.get("enabled", True) and forms.alert(u"Ставить оповещатели в коридорах/холлах?", yes=True, no=True)

report = []
placed_mcp = []  # (x, y, level_name)

with revit.Transaction(u"АПС: ИПР и оповещатели"):
    if do_mcp:
        for old in apslib.auto_instances(doc, marker, "mcp"):
            doc.Delete(old.Id)
        for src, sdoc, tr in apslib.iter_sources(doc):
            for d in DB.FilteredElementCollector(sdoc).OfCategory(DB.BuiltInCategory.OST_Doors).WhereElementIsNotElementType():
                try:
                    fr, to = d.FromRoom, d.ToRoom
                except Exception:
                    continue
                nf, nt = room_name(fr), room_name(to)
                exterior = (fr is None) != (to is None)
                to_exit = has_kw(nf, mcp["exit_room_keywords"]) != has_kw(nt, mcp["exit_room_keywords"])
                if not (exterior or to_exit):
                    continue
                # «своя» сторона — помещение, которое не выход/не улица
                if fr is None or has_kw(nf, mcp["exit_room_keywords"]):
                    own = to
                else:
                    own = fr
                if own is None:
                    continue
                loc = d.Location
                if not isinstance(loc, DB.LocationPoint):
                    continue
                p = tr.OfPoint(loc.Point)
                hand = tr.OfVector(d.HandOrientation).Normalize()
                face = tr.OfVector(d.FacingOrientation).Normalize()
                width = 900.0
                wp = d.Symbol.get_Parameter(DB.BuiltInParameter.DOOR_WIDTH) or d.get_Parameter(DB.BuiltInParameter.DOOR_WIDTH)
                if wp is not None and wp.AsDouble() > 0:
                    width = apslib.to_mm(wp.AsDouble())
                wall_t = 200.0
                if isinstance(d.Host, DB.Wall):
                    wall_t = apslib.to_mm(d.Host.Width)
                # с какой стороны двери помещение own
                test = p + face.Multiply(apslib.to_ft(wall_t / 2 + 300))
                inv = tr.Inverse
                side = face if own.IsPointInRoom(inv.OfPoint(DB.XYZ(test.X, test.Y, p.Z + apslib.to_ft(1000)))) else face.Negate()
                off = width / 2 + mcp["offset_from_door"]
                q = p + hand.Multiply(apslib.to_ft(off)) + side.Multiply(apslib.to_ft(wall_t / 2 + 20))
                x, y = apslib.to_mm(q.X), apslib.to_mm(q.Y)
                floor_z = apslib.to_mm(tr.OfPoint(own.Location.Point).Z)
                lvl = apslib.level_for_z(levels, floor_z)
                if any(abs(x - a) < 1000 and abs(y - b) < 1000 and lv == lvl.Name for a, b, lv in placed_mcp):
                    continue
                inst = apslib.place(doc, s_mcp, lvl, x, y, floor_z + mcp["height"])
                # развернуть лицом в помещение
                ang = math.atan2(side.Y, side.X)
                base = {"+Y": math.pi / 2, "-Y": -math.pi / 2, "+X": 0.0, "-X": math.pi}.get(mcp["family_front_axis"], math.pi / 2)
                axis = DB.Line.CreateBound(DB.XYZ(q.X, q.Y, 0), DB.XYZ(q.X, q.Y, 1))
                DB.ElementTransformUtils.RotateElement(doc, inst.Id, axis, ang - base)
                lbl = u"{} {}".format(apslib.pname(own, DB.BuiltInParameter.ROOM_NUMBER), room_name(own)).strip()
                apslib.set_comments(inst, u"{};role=mcp;room={}".format(marker, lbl))
                apslib.set_text(inst, rules["params"]["room"], lbl)
                placed_mcp.append((x, y, lvl.Name))
                report.append([lvl.Name, u"ИПР", lbl, u"у двери в «{}»".format(nt if own is fr else nf) if (nf or nt) else u"наружный выход"])

    rooms = apslib.collect_rooms(doc)

    if do_snd:
        for old in apslib.auto_instances(doc, marker, "sounder"):
            doc.Delete(old.Id)
        for r in rooms:
            if not has_kw(r["name"], snd["room_keywords"]):
                continue
            poly = [tuple(p) for p in r["poly"]]
            holes = [[tuple(p) for p in h] for h in r["holes"]]
            x0, y0, x1, y1 = apsgeom.bbox(poly)
            L, B = x1 - x0, y1 - y0
            n = max(1, int(math.ceil(max(L, B) / snd["spacing"])))
            lvl = apslib.level_for_z(levels, r["floor_z"])
            k = 0
            for i in range(n):
                t = (2 * i + 1) / (2.0 * n)
                x, y = (x0 + L * t, (y0 + y1) / 2) if L >= B else ((x0 + x1) / 2, y0 + B * t)
                if not apsgeom.inside_room(x, y, poly, holes):
                    continue
                inst = apslib.place(doc, s_snd, lvl, x, y, r["ceiling_z"] - snd["mount_below_ceiling"])
                lbl = u"{} {}".format(r["number"], r["name"]).strip()
                apslib.set_comments(inst, u"{};role=sounder;room={}".format(marker, lbl))
                k += 1
            report.append([r["level"], u"Оповещатель", u"{} {}".format(r["number"], r["name"]), u"{} шт.".format(k)])

# --- речевое оповещение: громкоговорители по расчёту уровня звука
vc = rules.get("voice", {})
voice_rep = []
if vc.get("enabled") and forms.alert(u"Расставить громкоговорители речевого оповещения (расчёт уровня звука)?", yes=True, no=True):
    s_spk = sym("speaker")
    lines_o, points_o = apslib.collect_obstacles(doc)
    with revit.Transaction(u"АПС: речевое оповещение"):
        for old in apslib.auto_instances(doc, marker, "speaker"):
            doc.Delete(old.Id)
        for v in apsgeom.plan_voice(rooms, lines_o, points_o, rules):
            r = v["room"]
            lvl = apslib.level_for_z(levels, r["floor_z"])
            for (x, y) in v["points"]:
                inst = apslib.place(doc, s_spk, lvl, x, y, r["ceiling_z"])
                apslib.set_comments(inst, u"{};role=speaker;tap={};room={}".format(marker, v["tap_w"], v["label"]))
                apslib.set_text(inst, rules["params"]["room"], v["label"])
            voice_rep.append([r["level"], v["label"], len(v["points"]), v["tap_w"], v["spl_min"], v["spl_max"],
                              v["need_db"], u"; ".join(v["issues"]) or u"норма"])

# --- проверка расстояний между ИПР: каждая точка коридора должна быть не дальше max/2 от ИПР
warn = []
half = mcp["max_distance"] / 2.0
for r in rooms:
    if not has_kw(r["name"], snd["room_keywords"]):
        continue
    mine = [(a, b) for a, b, lv in placed_mcp if lv == apslib.level_for_z(levels, r["floor_z"]).Name]
    poly = [tuple(p) for p in r["poly"]]
    x0, y0, x1, y1 = apsgeom.bbox(poly)
    far = 0
    for xx in range(int(x0), int(x1), 1000):
        for yy in range(int(y0), int(y1), 1000):
            if apsgeom.point_in_poly(xx, yy, poly) and (not mine or min(math.hypot(xx - a, yy - b) for a, b in mine) > half):
                far += 1
    if far:
        warn.append([r["level"], u"{} {}".format(r["number"], r["name"]), u"есть зоны дальше {:.0f} м от ИПР".format(half / 1000)])

out.print_md(u"## ИПР и оповещатели — {}".format(ven["title"]))
out.print_table(report, columns=[u"Уровень", u"Устройство", u"Помещение", u"Примечание"])
if voice_rep:
    out.print_md(u"### Речевое оповещение (уровень звука на высоте {} мм)".format(vc.get("listener_height", 1500)))
    out.print_table(voice_rep, columns=[u"Уровень", u"Помещение", u"Шт.", u"Отвод, Вт", u"Lмин, дБА", u"Lмакс, дБА", u"Требуется", u"Итог"])
    out.print_md(u"> {}".format(vc.get("_status", u"")))
if warn:
    out.print_md(u"### Проверка расстояний до ИПР")
    out.print_table(warn, columns=[u"Уровень", u"Помещение", u"Замечание"])
out.print_md(u"Высоту, отступ от двери и критерий «выхода» настраивай в `aps_rules.json → mcp`. Оповещатели ставятся упрощённо (по оси коридора) — тип и шаг СОУЭ задаёт проектировщик.")
