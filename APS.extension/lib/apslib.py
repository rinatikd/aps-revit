# -*- coding: utf-8 -*-
"""
apslib — работа с Revit API для АПС-инструментов.
Совместимость: Revit 2021+ , pyRevit (IronPython 2.7 по умолчанию или CPython 3).
Внутренние единицы Revit — футы; наружу всё отдаётся в миллиметрах.
"""
from __future__ import division
import os
import io
import json
import math

from Autodesk.Revit import DB
from System.Collections.Generic import List

FT = 304.8


def to_mm(v):
    return v * FT


def to_ft(v):
    return v / FT


HERE = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(HERE, "aps_rules.json")


def project_rules_path(doc):
    """Файл ответов диалога и настроек проекта: рядом с .rvt, иначе в %APPDATA%\\APS."""
    title = doc.Title.replace(u".rvt", u"")
    folder = os.path.dirname(doc.PathName) if doc.PathName and os.path.isdir(os.path.dirname(doc.PathName)) else \
        os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "APS")
    if not os.path.isdir(folder):
        os.makedirs(folder)
    return os.path.join(folder, title + u".aps.json")


def load_rules(doc=None):
    """Базовые правила (lib/aps_rules.json) + настройки и ответы проекта (<модель>.aps.json)."""
    with io.open(RULES_PATH, "r", encoding="utf-8") as f:
        rules = json.load(f)
    rules.setdefault("room_overrides", {})
    if doc is not None:
        apply_project(rules, load_project(doc))
    return rules


def apply_project(rules, proj):
    """Файл проекта: {"wizard_answers": {id: № варианта}, "room_overrides": {...}, "extra": {...}}."""
    import apsgeom
    ans = proj.get("wizard_answers", {})
    for q in rules.get("wizard", []):
        if q["id"] in ans:
            k = int(ans[q["id"]])
            if 0 <= k < len(q["options"]):
                apsgeom.apply_patch(rules, q["options"][k]["patch"])
    rules["room_overrides"].update(proj.get("room_overrides", {}))
    if proj.get("extra"):
        apsgeom.apply_patch(rules, proj["extra"])
    return rules


def load_project(doc):
    pp = project_rules_path(doc)
    if os.path.exists(pp):
        with io.open(pp, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_project(doc, data):
    pp = project_rules_path(doc)
    txt = json.dumps(data, ensure_ascii=False, indent=2)
    if not isinstance(txt, type(u"")):
        txt = txt.decode("utf-8")
    with io.open(pp, "w", encoding="utf-8") as f:
        f.write(txt)
    return pp


def vendor(rules):
    return rules["vendors"][rules["active_vendor"]]


# ---------------------------------------------------------------- источники

def iter_sources(doc):
    """(имя, документ, трансформация в координаты хоста) — хост и все загруженные связи."""
    yield doc.Title, doc, DB.Transform.Identity
    for li in DB.FilteredElementCollector(doc).OfClass(DB.RevitLinkInstance):
        ldoc = li.GetLinkDocument()
        if ldoc is None:
            continue
        yield ldoc.Title, ldoc, li.GetTotalTransform()


def pname(el, bip):
    p = el.get_Parameter(bip)
    if p is None:
        return u""
    return p.AsString() or p.AsValueString() or u""


def type_name(el):
    try:
        t = el.Document.GetElement(el.GetTypeId())
        if t is None:
            return u""
        fam = t.get_Parameter(DB.BuiltInParameter.SYMBOL_FAMILY_NAME_PARAM)
        nm = t.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
        return u"{} : {}".format(fam.AsString() if fam else u"", nm.AsString() if nm else u"")
    except Exception:
        return u""


# ---------------------------------------------------------------- помещения

def _loop_points(loop, tr):
    pts = []
    for seg in loop:
        c = seg.GetCurve()
        tess = list(c.Tessellate())
        for p in tess[:-1]:
            q = tr.OfPoint(p)
            pts.append((to_mm(q.X), to_mm(q.Y)))
    return pts


def _poly_area(pts):
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def make_ceiling_finder(doc):
    """Луч вверх из точки помещения до ближайшего потолка/перекрытия/кровли (с учётом связей)."""
    view3d = None
    for v in DB.FilteredElementCollector(doc).OfClass(DB.View3D):
        if not v.IsTemplate and not v.IsPerspective:
            view3d = v
            if v.Name in ("{3D}", u"{3D}"):
                break
    if view3d is None:
        return None
    flt = DB.LogicalOrFilter(List[DB.ElementFilter]([
        DB.ElementCategoryFilter(DB.BuiltInCategory.OST_Ceilings),
        DB.ElementCategoryFilter(DB.BuiltInCategory.OST_Floors),
        DB.ElementCategoryFilter(DB.BuiltInCategory.OST_Roofs)]))
    ri = DB.ReferenceIntersector(flt, DB.FindReferenceTarget.Face, view3d)
    ri.FindReferencesInRevitLinks = True

    def find(x_mm, y_mm, z_mm):
        origin = DB.XYZ(to_ft(x_mm), to_ft(y_mm), to_ft(z_mm))
        ctx = ri.FindNearest(origin, DB.XYZ.BasisZ)
        if ctx is None:
            return None
        return z_mm + to_mm(ctx.Proximity)
    return find


APT_PARAMS = [u"ADSK_Номер квартиры", u"Номер квартиры", u"Квартира", u"Apartment", u"Unit Number"]


def collect_rooms(doc, apt_params=None):
    """Помещения (Rooms) из хоста и связей + пространства (Spaces) хоста, если помещений нет.
    apt_params — имена параметров помещения с номером квартиры (первый заполненный идёт в поле apartment)."""
    opts = DB.SpatialElementBoundaryOptions()
    opts.SpatialElementBoundaryLocation = DB.SpatialElementBoundaryLocation.Finish
    finder = make_ceiling_finder(doc)
    apt_params = apt_params or APT_PARAMS
    rooms = []
    cats = [DB.BuiltInCategory.OST_Rooms]
    for src, sdoc, tr in iter_sources(doc):
        for r in DB.FilteredElementCollector(sdoc).OfCategory(cats[0]).WhereElementIsNotElementType():
            item = _room_item(r, src, tr, opts, finder, apt_params)
            if item:
                rooms.append(item)
    if not rooms:
        for r in DB.FilteredElementCollector(doc).OfCategory(DB.BuiltInCategory.OST_MEPSpaces).WhereElementIsNotElementType():
            item = _room_item(r, doc.Title, DB.Transform.Identity, opts, finder, apt_params)
            if item:
                rooms.append(item)
    return rooms


def _apartment(r, apt_params):
    for n in apt_params:
        p = r.LookupParameter(n)
        if p is not None and p.HasValue:
            v = p.AsString() if p.StorageType == DB.StorageType.String else p.AsValueString()
            if v:
                return v.strip()
    return u""


def _room_item(r, src, tr, opts, finder, apt_params=None):
    try:
        if r.Area <= 0 or r.Location is None:
            return None
        loops = r.GetBoundarySegments(opts)
        if not loops:
            return None
        polys = [_loop_points(l, tr) for l in loops]
        polys = [p for p in polys if len(p) >= 3]
        if not polys:
            return None
        polys.sort(key=_poly_area, reverse=True)
        lp = tr.OfPoint(r.Location.Point)
        floor_z = to_mm(lp.Z)
        ceil_z = None
        if finder:
            ceil_z = finder(to_mm(lp.X), to_mm(lp.Y), floor_z + 300.0)
        if ceil_z is None or ceil_z - floor_z < 1500:
            ceil_z = floor_z + to_mm(r.UnboundedHeight)
        return {
            "source": src,
            "id": r.Id.IntegerValue,
            "name": pname(r, DB.BuiltInParameter.ROOM_NAME),
            "number": pname(r, DB.BuiltInParameter.ROOM_NUMBER),
            "apartment": _apartment(r, apt_params or APT_PARAMS),
            "level": r.Level.Name if r.Level else u"",
            "area_m2": round(_poly_area(polys[0]) / 1e6, 2),
            "floor_z": round(floor_z, 1),
            "ceiling_z": round(ceil_z, 1),
            "ceiling_h": round(ceil_z - floor_z, 1),
            "poly": [[round(x, 1), round(y, 1)] for x, y in polys[0]],
            "holes": [[[round(x, 1), round(y, 1)] for x, y in p] for p in polys[1:]],
        }
    except Exception:
        return None


# ---------------------------------------------------------------- смежные сети

LINE_CATS = [
    (DB.BuiltInCategory.OST_DuctCurves, "duct"),
    (DB.BuiltInCategory.OST_FlexDuctCurves, "duct"),
    (DB.BuiltInCategory.OST_PipeCurves, "pipe"),
    (DB.BuiltInCategory.OST_CableTray, "cable_tray"),
    (DB.BuiltInCategory.OST_Conduit, "conduit"),
]
POINT_CATS = [
    (DB.BuiltInCategory.OST_DuctTerminal, "air_terminal"),
    (DB.BuiltInCategory.OST_LightingFixtures, "light"),
    (DB.BuiltInCategory.OST_Sprinklers, "sprinkler"),
]
SIZE_PARAMS = [
    DB.BuiltInParameter.RBS_CURVE_WIDTH_PARAM,
    DB.BuiltInParameter.RBS_CURVE_DIAMETER_PARAM,
    DB.BuiltInParameter.RBS_PIPE_OUTER_DIAMETER,
    DB.BuiltInParameter.RBS_CABLETRAY_WIDTH_PARAM,
    DB.BuiltInParameter.RBS_CONDUIT_OUTER_DIAM_PARAM,
]


def _bbox_mm(el, tr):
    bb = el.get_BoundingBox(None)
    if bb is None:
        return None
    a, b = tr.OfPoint(bb.Min), tr.OfPoint(bb.Max)
    return (to_mm(min(a.X, b.X)), to_mm(min(a.Y, b.Y)), to_mm(min(a.Z, b.Z)),
            to_mm(max(a.X, b.X)), to_mm(max(a.Y, b.Y)), to_mm(max(a.Z, b.Z)))


def collect_obstacles(doc):
    lines, points = [], []
    for src, sdoc, tr in iter_sources(doc):
        for bic, kind in LINE_CATS:
            for el in DB.FilteredElementCollector(sdoc).OfCategory(bic).WhereElementIsNotElementType():
                loc = el.Location
                if not isinstance(loc, DB.LocationCurve):
                    continue
                bb = _bbox_mm(el, tr)
                if bb is None:
                    continue
                c = loc.Curve
                p1, p2 = tr.OfPoint(c.GetEndPoint(0)), tr.OfPoint(c.GetEndPoint(1))
                w = 0.0
                for bip in SIZE_PARAMS:
                    p = el.get_Parameter(bip)
                    if p is not None and p.HasValue and p.AsDouble() > 0:
                        w = to_mm(p.AsDouble())
                        break
                if w <= 0:
                    w = min(bb[3] - bb[0], bb[4] - bb[1])
                lines.append({
                    "kind": kind, "source": src,
                    "x1": round(to_mm(p1.X), 1), "y1": round(to_mm(p1.Y), 1),
                    "x2": round(to_mm(p2.X), 1), "y2": round(to_mm(p2.Y), 1),
                    "hw": round(w / 2.0, 1),
                    "z_top": round(bb[5], 1), "z_bot": round(bb[2], 1),
                    "h": round(bb[5] - bb[2], 1),
                    "type": type_name(el),
                })
        for bic, kind in POINT_CATS:
            for el in DB.FilteredElementCollector(sdoc).OfCategory(bic).WhereElementIsNotElementType():
                bb = _bbox_mm(el, tr)
                if bb is None:
                    continue
                points.append({
                    "kind": kind, "source": src,
                    "x": round((bb[0] + bb[3]) / 2.0, 1), "y": round((bb[1] + bb[4]) / 2.0, 1),
                    "r": round(max(bb[3] - bb[0], bb[4] - bb[1]) / 2.0, 1),
                    "z_top": round(bb[5], 1), "z_bot": round(bb[2], 1),
                })
    return lines, points


def obstacles_for_room(room, lines, points, zone):
    import apsgeom
    return apsgeom.obstacles_for_room(room, lines, points, zone)


# ---------------------------------------------------------------- размещение

def host_levels(doc):
    lv = list(DB.FilteredElementCollector(doc).OfClass(DB.Level))
    lv.sort(key=lambda l: l.ProjectElevation)
    return lv


def level_for_z(levels, z_mm):
    best = None
    for l in levels:
        if to_mm(l.ProjectElevation) <= z_mm + 50:
            best = l
    return best or (levels[0] if levels else None)


def find_symbol(doc, family_name, type_name_=u""):
    for s in DB.FilteredElementCollector(doc).OfClass(DB.FamilySymbol):
        if s.Family is not None and s.Family.Name == family_name:
            if not type_name_:
                return s
            p = s.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM)
            if p and p.AsString() == type_name_:
                return s
    return None


def set_offset(inst, offset_mm):
    for bip in (DB.BuiltInParameter.INSTANCE_ELEVATION_PARAM,
                DB.BuiltInParameter.INSTANCE_FREE_HOST_OFFSET_PARAM):
        p = inst.get_Parameter(bip)
        if p is not None and not p.IsReadOnly:
            p.Set(to_ft(offset_mm))
            return True
    return False


def place(doc, symbol, level, x_mm, y_mm, z_abs_mm):
    if not symbol.IsActive:
        symbol.Activate()
        doc.Regenerate()
    pt = DB.XYZ(to_ft(x_mm), to_ft(y_mm), level.ProjectElevation)
    inst = doc.Create.NewFamilyInstance(pt, symbol, level, DB.Structure.StructuralType.NonStructural)
    set_offset(inst, z_abs_mm - to_mm(level.ProjectElevation))
    return inst


def set_text(inst, name, value):
    p = inst.LookupParameter(name)
    if p is None or p.IsReadOnly:
        return False
    if p.StorageType == DB.StorageType.String:
        p.Set(u"{}".format(value))
    elif p.StorageType == DB.StorageType.Integer:
        p.Set(int(value))
    elif p.StorageType == DB.StorageType.Double:
        p.Set(float(value))
    else:
        return False
    return True


def comments(inst):
    p = inst.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    return (p.AsString() or u"") if p else u""


def set_comments(inst, text):
    p = inst.get_Parameter(DB.BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is not None and not p.IsReadOnly:
        p.Set(text)


def auto_instances(doc, marker, role=None):
    """Экземпляры, расставленные этими скриптами (метка в Комментариях: APS_AUTO;role=smoke;...)."""
    out = []
    for el in DB.FilteredElementCollector(doc).OfClass(DB.FamilyInstance):
        c = comments(el)
        if c.startswith(marker):
            if role is None or (u"role=" + role) in c:
                out.append(el)
    return out


def fam_list(ids):
    return List[DB.ElementId](ids)
