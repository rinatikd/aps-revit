# -*- coding: utf-8 -*-
"""Пакетный экспорт листов АПС в DWG с настройкой экспорта (слои, УГО)."""
__title__ = u"5. Экспорт\nDWG"
__doc__ = u"Выгрузить выбранные листы в DWG по настройке экспорта из aps_rules.json"

from pyrevit import revit, script, forms
from Autodesk.Revit import DB

import apslib

doc = revit.doc
out = script.get_output()
rules = apslib.load_rules(doc)
setup = rules["export"]["dwg_setup"]

sheets = forms.select_sheets(title=u"Листы для экспорта в DWG", use_selection=True)
if not sheets:
    script.exit()
folder = forms.pick_folder(title=u"Папка для DWG")
if not folder:
    script.exit()

opts = DB.DWGExportOptions.GetPredefinedOptions(doc, setup)
if opts is None:
    forms.alert(u"Настройка экспорта «{}» не найдена — использую стандартную.\n"
                u"Создай её: Файл → Экспорт → Параметры → Экспорт в DWG/DXF.".format(setup))
    opts = DB.DWGExportOptions()
opts.MergedViews = True

done, failed = [], []
for s in sheets:
    name = u"{} - {}".format(s.SheetNumber, s.Name)
    for ch in u'\\/:*?"<>|':
        name = name.replace(ch, u"_")
    try:
        ok = doc.Export(folder, name, apslib.List[DB.ElementId]([s.Id]), opts)
        (done if ok else failed).append(name)
    except Exception as ex:
        failed.append(u"{} ({})".format(name, ex))

out.print_md(u"## Экспорт DWG: {} готово, {} ошибок".format(len(done), len(failed)))
for n in done:
    out.print_md(u"- {}.dwg".format(n))
for n in failed:
    out.print_md(u"- **ошибка:** {}".format(n))
out.print_md(u"Папка: `{}`".format(folder))
