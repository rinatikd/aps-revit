# -*- coding: utf-8 -*-
"""Комплект чертежей АПС в Revit: планы этажей с шаблоном «АПС — чертёж» и лист структурной схемы.
После этого кнопка «5» выгружает листы в DWG для AutoCAD."""
__title__ = u"7. Листы\nкомплекта"
__doc__ = u"Создать планы АПС по уровням, листы и разместить виды (план + структурная схема)"

from pyrevit import revit, script, forms
from Autodesk.Revit import DB

import apslib

doc = revit.doc
out = script.get_output()
rules = apslib.load_rules(doc)
ex = rules["export"]
marker = rules["params"]["marker"]

# уровни, на которых есть устройства АПС
lv_ids = set()
for el in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_FireAlarmDevices).WhereElementIsNotElementType():
    if el.LevelId and el.LevelId != DB.ElementId.InvalidElementId:
        lv_ids.add(el.LevelId.IntegerValue)
levels = [l for l in apslib.host_levels(doc) if l.Id.IntegerValue in lv_ids]
if not levels:
    forms.alert(u"В модели нет устройств АПС — сначала кнопки 2–4.", exitscript=True)

vft = None
for t in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
    if t.ViewFamily == DB.ViewFamily.FloorPlan and (not ex.get("plan_view_type") or t.Name == ex["plan_view_type"]):
        vft = t
        break
template = None
for v in DB.FilteredElementCollector(doc).OfClass(DB.View):
    if v.IsTemplate and v.Name == ex.get("view_template"):
        template = v
        break
tb = None
for t in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_TitleBlocks).WhereElementIsElementType():
    if not ex.get("titleblock") or t.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString() == ex["titleblock"]:
        tb = t
        break
if tb is None:
    forms.alert(u"В проекте нет основной надписи (семейства штампа). Загрузи её и повтори.", exitscript=True)

rooms = apslib.collect_rooms(doc)
existing_views = dict((v.Name, v) for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewPlan) if not v.IsTemplate)
existing_sheets = dict((s.SheetNumber, s) for s in DB.FilteredElementCollector(doc).OfClass(DB.ViewSheet))


def sheet_center(sheet):
    o = sheet.Outline
    return DB.XYZ((o.Min.U + o.Max.U) / 2.0, (o.Min.V + o.Max.V) / 2.0, 0)


def make_sheet(number, name):
    if number in existing_sheets:
        doc.Delete(existing_sheets[number].Id)
    sh = DB.ViewSheet.Create(doc, tb.Id)
    sh.SheetNumber = number
    sh.Name = name
    return sh


report = []
with revit.Transaction(u"АПС: листы комплекта"):
    n = 0
    for lv in levels:
        vname = u"АПС — План {}".format(lv.Name)
        if vname in existing_views:
            doc.Delete(existing_views[vname].Id)
        view = DB.ViewPlan.Create(doc, vft.Id, lv.Id)
        view.Name = vname
        if template is not None:
            view.ViewTemplateId = template.Id
        else:
            try:
                view.Scale = int(ex.get("plan_scale", 100))
            except Exception:
                pass
        # подрезка по помещениям уровня (+1 м)
        lv_rooms = [r for r in rooms if apslib.level_for_z(apslib.host_levels(doc), r["floor_z"]).Id == lv.Id]
        if lv_rooms:
            xs = [p[0] for r in lv_rooms for p in r["poly"]]
            ys = [p[1] for r in lv_rooms for p in r["poly"]]
            try:
                bb = view.CropBox
                bb.Min = DB.XYZ(apslib.to_ft(min(xs) - 1000), apslib.to_ft(min(ys) - 1000), bb.Min.Z)
                bb.Max = DB.XYZ(apslib.to_ft(max(xs) + 1000), apslib.to_ft(max(ys) + 1000), bb.Max.Z)
                view.CropBox = bb
                view.CropBoxActive = True
                view.CropBoxVisible = False
            except Exception:
                pass
        n += 1
        num = u"{}{}".format(ex.get("sheet_prefix", u"АПС-"), n)
        sh = make_sheet(num, u"План расположения оборудования АПС. {}".format(lv.Name))
        doc.Regenerate()
        if DB.Viewport.CanAddViewToSheet(doc, sh.Id, view.Id):
            DB.Viewport.Create(doc, sh.Id, view.Id, sheet_center(sh))
        report.append([num, sh.Name, vname, u"шаблон «{}»".format(template.Name) if template else u"без шаблона (1:{})".format(ex.get("plan_scale", 100))])

    # лист структурной схемы (если создана кнопкой 6)
    scheme = None
    for v in DB.FilteredElementCollector(doc).OfClass(DB.ViewDrafting):
        if v.Name.startswith(u"АПС — Структурная схема"):
            scheme = v
            break
    if scheme is not None:
        n += 1
        num = u"{}{}".format(ex.get("sheet_prefix", u"АПС-"), n)
        sh = make_sheet(num, u"Структурная схема АПС")
        doc.Regenerate()
        if DB.Viewport.CanAddViewToSheet(doc, sh.Id, scheme.Id):
            DB.Viewport.Create(doc, sh.Id, scheme.Id, sheet_center(sh))
            report.append([num, sh.Name, scheme.Name, u""])
        else:
            report.append([num, sh.Name, scheme.Name, u"вид уже размещён на другом листе"])

out.print_md(u"## Комплект листов АПС")
out.print_table(report, columns=[u"Лист", u"Наименование", u"Вид", u"Примечание"])
if template is None:
    out.print_md(u"Шаблон вида «{}» не найден — планы созданы без него. Создай шаблон (УГО вкл., 3D-геометрия выкл., подложка полутоном) и перезапусти.".format(ex.get("view_template")))
out.print_md(u"Дальше: **5. Экспорт DWG** — выбери листы {}* и получишь чертежи для AutoCAD. "
             u"Таблицы (спецификация, журнал) — CSV из кнопки 6 или вставь их в лист вручную.".format(ex.get("sheet_prefix", u"АПС-")))
