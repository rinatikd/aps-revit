# -*- coding: utf-8 -*-
"""Расстановка дымовых/тепловых извещателей с обходом смежных сетей и уточняющим диалогом."""
__title__ = u"2. Извещатели"
__doc__ = u"Расставить точечные извещатели по нормам, задать уточняющие вопросы по спорным помещениям"

from pyrevit import revit, script, forms

import apslib
import apsgeom

doc = revit.doc
out = script.get_output()
rules = apslib.load_rules(doc)
ven = apslib.vendor(rules)
pl = rules["placement"]
marker = rules["params"]["marker"]

out.print_md(u"## Расстановка извещателей — {}".format(ven["title"]))
out.print_md(u"> {}".format(rules.get("_status", u"")))

symbols = {}
for role in ("smoke", "heat"):
    d = ven["devices"][role]
    s = apslib.find_symbol(doc, d["family"], d.get("type", u""))
    if s is None:
        forms.alert(u"Не найдено семейство «{}» ({}).\nЗагрузи его в проект или поправь имя в aps_rules.json.".format(
            d["family"], d["model"]), exitscript=True)
    symbols[role] = s

levels = apslib.host_levels(doc)
if not levels:
    forms.alert(u"В хост-модели нет уровней.", exitscript=True)

rooms = apslib.collect_rooms(doc)
lines, points = apslib.collect_obstacles(doc)
if not rooms:
    forms.alert(u"Не найдено ни одного помещения (Rooms/Spaces) ни в хосте, ни в связях.", exitscript=True)

lvl_names = sorted(set(r["level"] for r in rooms))
picked = forms.SelectFromList.show(lvl_names, title=u"Уровни для расстановки", multiselect=True, button_name=u"Далее")
if not picked:
    script.exit()
rooms = [r for r in rooms if r["level"] in picked]

# ---------- уточняющий диалог
results = apsgeom.plan_rooms(rooms, lines, points, rules)
qs = [(r, q) for r in results for q in r["questions"]]
if qs and forms.alert(u"Есть уточняющие вопросы по помещениям: {}.\nОтветить сейчас? Ответы сохранятся в файл проекта "
                      u"и будут учитываться при следующих запусках.".format(len(qs)), yes=True, no=True):
    proj = apslib.load_project(doc)
    ovr = proj.setdefault("room_overrides", {})
    SKIP, STOP = u"→ Пропустить вопрос", u"■ Закончить вопросы"
    for i, (r, q) in enumerate(qs, 1):
        labels = [o["label"] for o in q["options"]]
        choice = forms.CommandSwitchWindow.show(labels + [SKIP, STOP],
                                                message=u"Вопрос {} из {}\n\n{}".format(i, len(qs), q["text"]))
        if choice is None or choice == STOP:
            break
        if choice == SKIP:
            continue
        opt = q["options"][labels.index(choice)]
        patch = dict(opt.get("patch", {}))
        if opt.get("input"):
            val = forms.ask_for_string(default=u"{:.0f}".format(r["room"]["ceiling_h"]),
                                       prompt=u"{}, {}".format(opt["label"], opt.get("unit", u"")),
                                       title=r["label"])
            try:
                patch[opt["input"]] = float(val.replace(u",", u"."))
            except Exception:
                continue
        ovr.setdefault(r["key"], {}).update(patch)
    path = apslib.save_project(doc, proj)
    out.print_md(u"Ответы сохранены: `{}`".format(path))
    rules = apslib.load_rules(doc)
    results = apsgeom.plan_rooms(rooms, lines, points, rules)

if not forms.alert(u"Расставить извещатели на уровнях: {}?\nРанее расставленные автоматически будут заменены.".format(
        u", ".join(picked)), yes=True, no=True):
    script.exit()

# ---------- размещение
report, total, problems = [], 0, 0
with revit.Transaction(u"АПС: расстановка извещателей"):
    old = [e.Id for e in apslib.auto_instances(doc, marker, "smoke") + apslib.auto_instances(doc, marker, "heat")
           if doc.GetElement(e.LevelId) is not None and doc.GetElement(e.LevelId).Name in picked]
    # уровень извещателя — уровень хоста, а не связи; поэтому чистим и по уровням помещений
    lv_ids = set(apslib.level_for_z(levels, r["floor_z"]).Id.IntegerValue for r in rooms)
    old += [e.Id for e in apslib.auto_instances(doc, marker, "smoke") + apslib.auto_instances(doc, marker, "heat")
            if e.LevelId.IntegerValue in lv_ids and e.Id not in old]
    if old:
        doc.Delete(apslib.fam_list(old))

    for res in results:
        r = res["room"]
        if res["role"]:
            lvl = apslib.level_for_z(levels, r["floor_z"])
            ceil_z = r["floor_z"] + float(res["override"].get("ceiling_h") or r["ceiling_h"])
            z = ceil_z - pl.get("mount_below_ceiling", 0)
            for (x, y) in res["points"]:
                inst = apslib.place(doc, symbols[res["role"]], lvl, x, y, z)
                apslib.set_comments(inst, u"{};role={};room={}".format(marker, res["role"], res["label"]))
                apslib.set_text(inst, rules["params"]["room"], res["label"])
                total += 1
        if res["problem"]:
            problems += 1
        left = len(res["questions"])
        report.append([r["level"], res["label"], res["role"] or u"—", len(res["points"]),
                       res["note"] + (u" | вопросов без ответа: {}".format(left) if left else u"")])

out.print_md(u"### Результат: {} извещателей, помещений с замечаниями: {}".format(total, problems))
out.print_table(report, columns=[u"Уровень", u"Помещение", u"Тип", u"Шт.", u"Отчёт"])
out.print_md(u"Метка в «Комментариях»: `{}` — по ней скрипт заменяет свои элементы при повторном запуске.".format(marker))
