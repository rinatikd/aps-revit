# -*- coding: utf-8 -*-
"""Мастер настройки проекта АПС: вопросы из aps_rules.json → wizard, ответы — в <модель>.aps.json."""
__title__ = u"0. Мастер"
__doc__ = u"Диалог настройки проекта: производитель, состав защиты, алгоритм, питание, кабель"

from pyrevit import revit, script, forms

import apslib

doc = revit.doc
out = script.get_output()
base = apslib.load_rules()          # без проектных ответов — чтобы показать все варианты
proj = apslib.load_project(doc)
answers = proj.get("wizard_answers", {})

STOP = u"■ Закончить (сохранить ответы)"
KEEP = u"• Оставить текущий ответ"

for q in base.get("wizard", []):
    labels = [o["label"] for o in q["options"]]
    cur = answers.get(q["id"])
    msg = q["text"]
    if cur is not None and 0 <= int(cur) < len(labels):
        msg += u"\n\nСейчас: {}".format(labels[int(cur)])
        choice = forms.CommandSwitchWindow.show(labels + [KEEP, STOP], message=msg)
    else:
        choice = forms.CommandSwitchWindow.show(labels + [STOP], message=msg)
    if choice is None or choice == STOP:
        break
    if choice == KEEP:
        continue
    answers[q["id"]] = labels.index(choice)

proj["wizard_answers"] = answers
path = apslib.save_project(doc, proj)

rules = apslib.load_rules(doc)
ven = apslib.vendor(rules)
out.print_md(u"## Настройки проекта сохранены")
rows = []
for q in base.get("wizard", []):
    k = answers.get(q["id"])
    rows.append([q["text"], q["options"][int(k)]["label"] if k is not None else u"— (по умолчанию)"])
out.print_table(rows, columns=[u"Вопрос", u"Ответ"])
out.print_md(u"Производитель: **{}**, линия **{}** до {} адресов, резерв {:.0%}.".format(
    ven["title"], ven["loop_name"], ven["max_addresses_per_loop"], 1 - ven.get("loop_fill_ratio", 1)))
out.print_md(u"Файл проекта: `{}`. Ответы по отдельным помещениям добавляются туда из кнопки «2. Извещатели».".format(path))
