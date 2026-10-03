# -*- coding: utf-8 -*-
"""Разведка: собирает помещения, высоты потолков и смежные сети (с учётом связей) в aps_recon.json.
Ничего не меняет в модели."""
__title__ = u"1. Разведка"
__doc__ = u"Собрать помещения, потолки и смежные сети в aps_recon.json (модель не меняется)"

import io
import os
import json
from collections import Counter

from pyrevit import revit, script, forms
from Autodesk.Revit import DB

import apslib

doc = revit.doc
out = script.get_output()
rules = apslib.load_rules(doc)

out.print_md(u"## Разведка модели: {}".format(doc.Title))

# связи
srcs = []
for name, sdoc, tr in apslib.iter_sources(doc):
    srcs.append(name)
out.print_md(u"**Источники (хост + загруженные связи):** {}".format(u", ".join(srcs)))

with forms.ProgressBar(title=u"Помещения и потолки…") as pb:
    pb.update_progress(1, 3)
    rooms = apslib.collect_rooms(doc)
    pb.update_progress(2, 3)
    lines, points = apslib.collect_obstacles(doc)
    pb.update_progress(3, 3)

# уровни хоста
levels = [{"name": l.Name, "z": round(apslib.to_mm(l.ProjectElevation), 1)} for l in apslib.host_levels(doc)]

# семейства АПС, загруженные в хост
fa = []
for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
    try:
        if s.Category and s.Category.Id.IntegerValue == int(DB.BuiltInCategory.OST_FireAlarmDevices):
            fa.append(u"{} : {}".format(s.Family.Name, s.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()))
    except Exception:
        pass

# общие параметры
names = rules["params"]
probe = None
for el in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_FireAlarmDevices).WhereElementIsNotElementType():
    probe = el
    break
params_ok = {}
for key in ("loop", "address", "room"):
    params_ok[names[key]] = bool(probe and probe.LookupParameter(names[key]))

# уже размещённые устройства АПС и прибор (для предпросмотра документации в HTML)
fam_map = {}
for v in rules["vendors"].values():
    for role, d in v["devices"].items():
        fam_map[d["family"]] = role
panel_fams = [v["panel"]["family"] for v in rules["vendors"].values()]
devices, panel = [], None
for el in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_FireAlarmDevices).WhereElementIsNotElementType():
    loc = el.Location
    if not isinstance(loc, DB.LocationPoint):
        continue
    pt = loc.Point
    xyz = [round(apslib.to_mm(pt.X), 1), round(apslib.to_mm(pt.Y), 1), round(apslib.to_mm(pt.Z), 1)]
    fam = el.Symbol.Family.Name
    if fam in panel_fams:
        panel = xyz
        continue
    role = fam_map.get(fam)
    if role is None:
        continue
    lvl = doc.GetElement(el.LevelId)
    devices.append({"role": role, "x": xyz[0], "y": xyz[1], "z": xyz[2],
                    "level": lvl.Name if lvl else u"", "room": apslib.comments(el).split(u"room=")[-1] if u"room=" in apslib.comments(el) else u""})

data = {
    "model": doc.Title,
    "revit": doc.Application.VersionNumber,
    "sources": srcs,
    "levels": levels,
    "rooms": rooms,
    "obstacles": {"lines": lines, "points": points},
    "fire_alarm_families": fa,
    "devices": devices,
    "panel": panel,
    "shared_params_found": params_ok,
}

folder = forms.pick_folder(title=u"Куда сохранить aps_recon.json")
if not folder:
    folder = os.path.join(os.path.expanduser("~"), "Desktop")
path = os.path.join(folder, "aps_recon.json")
with io.open(path, "w", encoding="utf-8") as f:
    txt = json.dumps(data, ensure_ascii=False, indent=1)
    if not isinstance(txt, type(u"")):
        txt = txt.decode("utf-8")
    f.write(txt)

# сводка
out.print_md(u"### Итог")
out.print_table([
    [u"Помещений", len(rooms)],
    [u"Линейных элементов смежников", len(lines)],
    [u"Точечных элементов смежников", len(points)],
    [u"Уровней в хосте", len(levels)],
    [u"Семейств АПС в хосте", len(fa)],
], columns=[u"Что", u"Сколько"])

cnt = Counter([o["kind"] for o in lines] + [o["kind"] for o in points])
out.print_table([[k, v] for k, v in sorted(cnt.items())], columns=[u"Тип смежника", u"Кол-во"])

low = [r for r in rooms if r["ceiling_h"] < 2200 or r["ceiling_h"] > 12000]
if low:
    out.print_md(u"**Внимание:** у {} помещений подозрительная высота потолка (<2.2 м или >12 м) — проверь 3D-вид и потолки.".format(len(low)))
if not fa:
    out.print_md(u"**Нет семейств категории «Пожарная сигнализация» в модели** — загрузи семейства из rules (`{}`).".format(rules["active_vendor"]))
miss = [k for k, v in params_ok.items() if not v]
if miss:
    out.print_md(u"Не найдены общие параметры: {} — будут использоваться Комментарии.".format(u", ".join(miss)))

out.print_md(u"Файл сохранён: `{}`. Открой HTML-руководство и загрузи этот файл в «Предпросмотр».".format(path))
