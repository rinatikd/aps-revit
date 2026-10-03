# -*- coding: utf-8 -*-
"""
apsgeom — чистая 2D-геометрия и алгоритм расстановки извещателей.
Без зависимостей от Revit: работает в IronPython 2.7, CPython 3 и тестируется вне Revit.
Все величины — в миллиметрах, координаты — в системе хост-модели.

Комната:   poly  = [(x, y), ...]             внешний контур
           holes = [[(x, y), ...], ...]      внутренние контуры (колонны, шахты)
Препятствия:
           points = [{"x":, "y":, "r":, "kind":}]                 диффузоры, светильники, спринклеры
           lines  = [{"x1":, "y1":, "x2":, "y2":, "hw":, "kind":, "h":}]  воздуховоды, лотки, трубы
"""
from __future__ import division
import math


# ---------- базовая геометрия ----------

def bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def point_in_poly(x, y, poly):
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            xc = (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
            if x < xc:
                inside = not inside
        j = i
    return inside


def inside_room(x, y, poly, holes):
    if not point_in_poly(x, y, poly):
        return False
    for h in holes or []:
        if point_in_poly(x, y, h):
            return False
    return True


def dist_point_seg(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 < 1e-9:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def dist_to_edges(x, y, poly, holes):
    best = 1e18
    for loop in [poly] + list(holes or []):
        n = len(loop)
        for i in range(n):
            x1, y1 = loop[i]
            x2, y2 = loop[(i + 1) % n]
            d = dist_point_seg(x, y, x1, y1, x2, y2)
            if d < best:
                best = d
    return best


def seg_len_inside(x1, y1, x2, y2, poly, step=200.0):
    """Приближённая длина отрезка, лежащая внутри полигона (для поиска делящих препятствий)."""
    L = math.hypot(x2 - x1, y2 - y1)
    if L < 1e-6:
        return 0.0
    n = max(2, int(L / step))
    inside = 0
    for i in range(n):
        t = (i + 0.5) / n
        if point_in_poly(x1 + t * (x2 - x1), y1 + t * (y2 - y1), poly):
            inside += 1
    return L * inside / n


# ---------- правила ----------

def pick_row(table, ceiling_h):
    """Строка таблицы норм по высоте потолка. None — если высота вне таблицы."""
    for row in sorted(table, key=lambda r: r["h_max"]):
        if ceiling_h <= row["h_max"]:
            return row
    return None


def room_key(level, number, name):
    return u"{}|{}|{}".format(level or u"", number or u"", name or u"")


def classify_room(name, room_rules, default, default_action="place", override=None):
    """
    Возвращает (действие, роль, источник): действие 'skip' | 'place';
    источник: 'override' (ответ в диалоге), 'rule' (ключевое слово), 'default' (правило не найдено).
    """
    if override and override.get("action"):
        if override["action"] == "skip":
            return "skip", None, "override"
        return "place", override.get("detector", default), "override"
    low = (name or u"").lower()
    for rr in room_rules:
        for kw in rr.get("match", []):
            if kw.lower() in low:
                if rr.get("action") == "skip":
                    return "skip", None, "rule"
                return "place", rr.get("detector", default), "rule"
    if default_action == "skip":
        return "skip", None, "default"
    return "place", default, "default"


def side_of(x, y, o):
    return (o["x2"] - o["x1"]) * (y - o["y1"]) - (o["y2"] - o["y1"]) * (x - o["x1"]) > 0


# ---------- препятствия ----------

KIND_RU = {u"air_terminal": u"воздухораспределитель", u"light": u"светильник", u"sprinkler": u"спринклер",
           u"duct": u"воздуховод", u"pipe": u"трубопровод", u"cable_tray": u"кабельный лоток",
           u"conduit": u"короб/труба кабельная"}


def kind_ru(k):
    return KIND_RU.get(k, k or u"препятствие")


def make_checker(poly, holes, obst_points, obst_lines, wall_min, clear):
    """Функция ok(x, y) -> (bool, причина)."""
    def ok(x, y):
        if not inside_room(x, y, poly, holes):
            return False, u"вне помещения"
        if dist_to_edges(x, y, poly, holes) < wall_min:
            return False, u"ближе к стене, чем допускается"
        for o in obst_points:
            c = clear.get(o.get("kind", ""), clear.get("default_point", 0))
            if math.hypot(x - o["x"], y - o["y"]) < o.get("r", 0) + c:
                return False, kind_ru(o.get("kind"))
        for o in obst_lines:
            c = clear.get(o.get("kind", ""), clear.get("default_line", 0))
            if dist_point_seg(x, y, o["x1"], o["y1"], o["x2"], o["y2"]) < o.get("hw", 0) + c:
                return False, kind_ru(o.get("kind"))
        return True, u""
    return ok


def relocate(x, y, ok, max_shift, step=100.0, angles=16):
    good, why = ok(x, y)
    if good:
        return (x, y), None
    r = step
    while r <= max_shift + 1e-6:
        for k in range(angles):
            a = 2 * math.pi * k / angles
            nx, ny = x + r * math.cos(a), y + r * math.sin(a)
            if ok(nx, ny)[0]:
                return (nx, ny), why
        r += step
    return None, why


# ---------- основной алгоритм ----------

def plan_room(poly, holes, ceiling_h, row, obst_points, obst_lines, cfg):
    """
    Расстановка точечных извещателей в одном помещении.
    row  — строка норм: {"spacing":, "wall_max":, "area":}  (мм, мм, м2)
    cfg  — {"wall_min":, "min_per_room":, "max_shift":, "sample_step":, "clear": {...},
            "partition_height":}
    Возвращает dict: points=[(x,y)], shifted=n, issues=[str]
    """
    issues = []
    S = float(row["spacing"])
    W = float(row["wall_max"])
    A = float(row.get("area", 0)) * 1e6  # м2 -> мм2
    minx, miny, maxx, maxy = bbox(poly)
    L, B = maxx - minx, maxy - miny
    room_area = area(poly) - sum(area(h) for h in holes or [])

    need_by_area = int(math.ceil(room_area / A - 1e-9)) if A > 0 else 1
    need = max(int(cfg.get("min_per_room", 1)), need_by_area, 1)

    def ncount(length):
        return max(1, int(math.ceil(length / S - 1e-9)), int(math.ceil(length / (2 * W) - 1e-9)))

    nx, ny = ncount(L), ncount(B)

    ok = make_checker(poly, holes, obst_points, obst_lines,
                      float(cfg.get("wall_min", 100)), cfg.get("clear", {}))
    max_shift = float(cfg.get("max_shift", 1500))

    # 1. регулярная сетка; если точек меньше требуемого — уплотняем по длинной оси
    for _ in range(50):
        cands = []
        for i in range(nx):
            for j in range(ny):
                cands.append((minx + L * (2 * i + 1) / (2.0 * nx),
                              miny + B * (2 * j + 1) / (2.0 * ny)))
        cands = [c for c in cands if inside_room(c[0], c[1], poly, holes)]
        if len(cands) >= need:
            break
        if L >= B:
            nx += 1
        else:
            ny += 1

    # 2. обход препятствий
    placed, shifted = [], 0
    for (x, y) in cands:
        p, why = relocate(x, y, ok, max_shift)
        if p is None:
            issues.append(u"точка ({:.0f}; {:.0f}) не размещена: {}".format(x, y, why))
            continue
        if why:
            shifted += 1
        placed.append(p)

    # 3. проверка покрытия и добор: каждая точка помещения должна быть
    #    в пределах половины диагонали ячейки сетки от извещателя
    R = S * math.sqrt(2) / 2.0
    step = float(cfg.get("sample_step", 500))
    samples = []
    yy = miny + step / 2
    while yy < maxy:
        xx = minx + step / 2
        while xx < maxx:
            if inside_room(xx, yy, poly, holes):
                samples.append((xx, yy))
            xx += step
        yy += step

    def uncovered():
        return [s for s in samples
                if not any(math.hypot(s[0] - p[0], s[1] - p[1]) <= R for p in placed)]

    added = 0
    for _ in range(30):
        unc = uncovered()
        if not unc:
            break
        # кандидат: непокрытая точка, рядом с которой больше всего непокрытых
        best, best_n = None, -1
        for s in unc[::max(1, len(unc) // 60)]:
            n = sum(1 for t in unc if math.hypot(s[0] - t[0], s[1] - t[1]) <= R)
            if n > best_n:
                best, best_n = s, n
        p, why = relocate(best[0], best[1], ok, max_shift)
        if p is None:
            issues.append(u"зона около ({:.0f}; {:.0f}) не покрыта: {}".format(best[0], best[1], why))
            samples = [s for s in samples if math.hypot(s[0] - best[0], s[1] - best[1]) > R]
            continue
        placed.append(p)
        added += 1

    if len(placed) < need:
        issues.append(u"расставлено {} из требуемых {}".format(len(placed), need))

    # 4. препятствия, которые могут делить помещение на зоны (как балки)
    ph = float(cfg.get("partition_height", 0) or 0)
    partitions = []
    if ph > 0 and not cfg.get("no_split"):
        for o in obst_lines:
            if o.get("h", 0) >= ph:
                inside_len = seg_len_inside(o["x1"], o["y1"], o["x2"], o["y2"], poly)
                if inside_len >= 0.5 * min(L, B):
                    partitions.append(o)
                    issues.append(u"{} высотой {:.0f} мм пересекает помещение — проверить деление на зоны".format(
                        kind_ru(o.get("kind")), o.get("h", 0)))

    return {"points": placed, "shifted": shifted, "added": added,
            "need": need, "issues": issues, "partitions": partitions}


# ---------- шлейфы ----------

def order_nearest(points, start):
    """Порядок обхода 'ближайший сосед'. points=[(id, x, y)], start=(x, y)."""
    rest = list(points)
    out = []
    cx, cy = start
    while rest:
        k = min(range(len(rest)), key=lambda i: abs(rest[i][1] - cx) + abs(rest[i][2] - cy))
        p = rest.pop(k)
        out.append(p)
        cx, cy = p[1], p[2]
    return out


def chunk(seq, n):
    n = max(1, int(n))
    return [seq[i:i + n] for i in range(0, len(seq), n)]


def manhattan_len(path):
    s = 0.0
    for a, b in zip(path, path[1:]):
        s += abs(a[0] - b[0]) + abs(a[1] - b[1])
    return s


# ---------- документация: кабельный журнал, спецификация, структурная схема ----------

def rnd(x, n=0):
    """Округление «половина вверх» — одинаково в Python 2/3 и JavaScript."""
    k = 10 ** n
    return math.floor(x * k + 0.5) / k


def _num(s):
    d = u"".join(ch for ch in u"{}".format(s) if ch.isdigit())
    return int(d) if d else 0


def seg_cable_mm(a, b, lp):
    """Длина кабеля между двумя точками (x, y, z) мм: ортогональная трасса + спуски + запас."""
    L = abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2]) + 2 * lp.get("drop_per_device", 0)
    return L * (1 + lp.get("cable_reserve", 0))


def build_docs(devs, panel, ven, rules, line_cable=None):
    """
    devs  = [{"role":, "model":, "level":, "lz":, "x":, "y":, "z":, "loop":, "addr":, "room":}]
    panel = (x, y, z) или None
    line_cable = {линия: марка кабеля} — результат подбора сечения (второй проход)
    Возвращает {"journal": [...], "spec": [...], "scheme": [...]}
    """
    line_cable = line_cable or {}
    lp = rules["loops"]
    dc = rules["documentation"]
    pref = dc.get("cable_prefix", u"К")
    pname_ = ven["panel"]["model"]
    if panel is None and devs:
        panel = (min(d["x"] for d in devs), min(d["y"] for d in devs), min(d["z"] for d in devs))

    journal, scheme = [], []
    cable_tot = {}
    k = 0

    def add_cable(mark, mm):
        cable_tot[mark] = cable_tot.get(mark, 0.0) + mm

    # адресные линии
    loops = {}
    for d in devs:
        if d.get("loop"):
            loops.setdefault(d["loop"], []).append(d)
    for lid in sorted(loops, key=_num):
        items = sorted(loops[lid], key=lambda d: _num(d.get("addr")))
        prev, prev_name = panel, pname_
        total = 0.0
        cab = line_cable.get(lid, ven["loop_cable"])
        for d in items:
            k += 1
            L = seg_cable_mm(prev, (d["x"], d["y"], d["z"]), lp)
            total += L
            add_cable(cab, L)
            to = u"{} адр. {}".format(d["model"], d.get("addr", u""))
            journal.append({"mark": u"{}{}".format(pref, k), "line": lid, "from": prev_name, "to": to,
                            "room": d.get("room", u""), "cable": cab,
                            "length_m": rnd(L / 1000.0, 1)})
            prev, prev_name = (d["x"], d["y"], d["z"]), to
        groups = {}
        for d in items:
            g = groups.setdefault((d["lz"], d["level"]), {})
            g[d["model"]] = g.get(d["model"], 0) + 1
        scheme.append({"line": lid, "kind": "loop", "cable": cab, "length_m": rnd(total / 1000.0, 1),
                       "count": len(items),
                       "groups": [{"level": lv, "models": groups[(z, lv)]} for (z, lv) in sorted(groups)]})

    # неадресные линии: звуковые оповещатели (СОУЭ) и громкоговорители речевого оповещения (РО)
    for role, prefix, kind, default_cab in (("sounder", u"СОУЭ", "sounder", ven["sounder_cable"]),
                                           ("speaker", u"РО", "voice", ven.get("voice_cable", ven["sounder_cable"]))):
        snd = [d for d in devs if d["role"] == role]
        by_lv = {}
        for d in snd:
            by_lv.setdefault((d["lz"], d["level"]), []).append(d)
        for i, key in enumerate(sorted(by_lv), 1):
            items = by_lv[key]
            order = order_nearest([(j, d["x"], d["y"]) for j, d in enumerate(items)], (panel[0], panel[1]))
            lid = u"{}{}".format(prefix, i)
            prev, prev_name, total = panel, pname_, 0.0
            cab = line_cable.get(lid, default_cab)
            for n, o in enumerate(order, 1):
                d = items[o[0]]
                d["line"] = lid
                k += 1
                L = seg_cable_mm(prev, (d["x"], d["y"], d["z"]), lp)
                total += L
                add_cable(cab, L)
                to = u"{} №{}".format(d["model"], n)
                journal.append({"mark": u"{}{}".format(pref, k), "line": lid, "from": prev_name, "to": to,
                                "room": d.get("room", u""), "cable": cab,
                                "length_m": rnd(L / 1000.0, 1)})
                prev, prev_name = (d["x"], d["y"], d["z"]), to
            models = {}
            for d in items:
                models[d["model"]] = models.get(d["model"], 0) + 1
            row = {"line": lid, "kind": kind, "cable": cab, "length_m": rnd(total / 1000.0, 1),
                   "count": len(items), "groups": [{"level": key[1], "models": models}]}
            if role == "speaker":
                row["power_w"] = sum(d.get("power_w", 0) for d in items)
            scheme.append(row)

    # спецификация (ГОСТ 21.110): оборудование, затем материалы
    spec = []
    n_loops = len(loops)
    per = max(1, int(ven.get("loops_per_panel", 1)))
    n_panels = max(1, int(math.ceil(n_loops / float(per)))) if n_loops else (1 if devs else 0)
    if n_panels:
        spec.append({"group": u"Оборудование", "name": u"Прибор / контроллер адресной линии",
                     "mark": pname_, "maker": ven.get("manufacturer", u""), "unit": u"шт", "qty": n_panels,
                     "note": u"{} лин. по {} адр.".format(n_loops, ven["max_addresses_per_loop"])})
    titles = {"smoke": u"Извещатель пожарный дымовой адресный", "heat": u"Извещатель пожарный тепловой адресный",
              "mcp": u"Извещатель пожарный ручной адресный", "sounder": u"Оповещатель пожарный",
              "speaker": u"Оповещатель речевой (громкоговоритель)"}
    cnt = {}
    for d in devs:
        key = (d["role"], d["model"])
        cnt[key] = cnt.get(key, 0) + 1
    order_roles = ["smoke", "heat", "mcp", "sounder", "speaker"]
    for (role, model) in sorted(cnt, key=lambda k: (order_roles.index(k[0]) if k[0] in order_roles else 9, k[1])):
        spec.append({"group": u"Оборудование", "name": titles.get(role, u"Устройство АПС"), "mark": model,
                     "maker": ven.get("manufacturer", u""), "unit": u"шт", "qty": cnt[(role, model)], "note": u""})
    voice_w = sum(r.get("power_w", 0) for r in scheme if r["kind"] == "voice")
    if voice_w:
        amp = ven.get("voice_amp", {})
        need_w = voice_w * rules.get("voice", {}).get("amp_reserve", 1.25)
        n_amp = int(math.ceil(need_w / float(amp.get("power_w", 100) or 100)))
        spec.append({"group": u"Оборудование", "name": u"Прибор / усилитель речевого оповещения",
                     "mark": amp.get("model", u""), "maker": ven.get("manufacturer", u""), "unit": u"шт", "qty": n_amp,
                     "note": u"нагрузка {} Вт × {} = {} Вт".format(rnd(voice_w, 1), rules.get("voice", {}).get("amp_reserve", 1.25), rnd(need_w, 1))})
    total_m = 0
    for mark in sorted(cable_tot):
        m = int(math.ceil(cable_tot[mark] / 1000.0))
        total_m += m
        spec.append({"group": u"Материалы", "name": u"Кабель огнестойкий", "mark": mark, "maker": u"",
                     "unit": u"м", "qty": m, "note": u"с запасом {:.0%}".format(lp.get("cable_reserve", 0))})
    for mat in dc.get("materials_per_device", []):
        q = sum(v for (role, _), v in cnt.items() if role in mat.get("roles", [])) * mat.get("qty", 1)
        if q:
            spec.append({"group": u"Материалы", "name": mat["name"], "mark": mat.get("mark", u""), "maker": u"",
                         "unit": mat.get("unit", u"шт"), "qty": q, "note": u""})
    fx = dc.get("cable_fixing_per_m")
    if fx and total_m:
        spec.append({"group": u"Материалы", "name": fx["name"], "mark": fx.get("mark", u""), "maker": u"",
                     "unit": fx.get("unit", u"шт"), "qty": int(math.ceil(total_m * fx.get("per_m", 0))), "note": u""})
    for i, row in enumerate(spec, 1):
        row["pos"] = i
    return {"journal": journal, "spec": spec, "scheme": scheme}


def assign_loops(devs, start, cap, loop_name, on_loop_roles):
    """То же, что кнопка «4. Шлейфы»: по уровням, ближайший сосед, деление по ёмкости. Меняет devs на месте."""
    by_level = {}
    for d in devs:
        if d["role"] in on_loop_roles:
            by_level.setdefault((d["lz"], d["level"]), []).append(d)
    n = 0
    for key in sorted(by_level):
        items = by_level[key]
        order = order_nearest([(i, d["x"], d["y"]) for i, d in enumerate(items)], start)
        for part in chunk(order, cap):
            n += 1
            for a, p in enumerate(part, 1):
                items[p[0]]["loop"] = u"{}{}".format(loop_name, n)
                items[p[0]]["addr"] = a
    return n


# ---------- электрический расчёт линий ----------

def line_electrics(seg_m, cur_standby_ma, cur_max_ma, r_ohm_km, u0, u_min, i_max_ma=None, r_max_ohm=None):
    """
    Радиальная линия (худший случай; для кольца — обрыв у прибора).
    seg_m[i]   — длина кабеля от предыдущей точки до устройства i, м
    cur_*_ma[i] — ток устройства i, мА
    Ток на участке i = сумма токов всех устройств от i до конца. Две жилы: R = 2·r·L.
    """
    n = len(seg_m)
    tail_s, tail_m = [0.0] * (n + 1), [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        tail_s[i] = tail_s[i + 1] + cur_standby_ma[i]
        tail_m[i] = tail_m[i + 1] + cur_max_ma[i]
    du_s = du_m = 0.0
    r_loop = 0.0
    for i in range(n):
        r = 2.0 * r_ohm_km * seg_m[i] / 1000.0
        r_loop += r
        du_s += r * tail_s[i] / 1000.0
        du_m += r * tail_m[i] / 1000.0
    res = {
        "i_standby_ma": rnd(tail_s[0], 2), "i_max_ma": rnd(tail_m[0], 2),
        "r_loop_ohm": rnd(r_loop, 2), "du_standby_v": rnd(du_s, 3), "du_max_v": rnd(du_m, 3),
        "u_end_max_v": rnd(u0 - du_m, 2), "checks": [],
    }
    ok = True
    if u0 - du_m < u_min:
        ok = False
        res["checks"].append(u"U в конце {:.2f} В < {:.2f} В".format(u0 - du_m, u_min))
    if i_max_ma and tail_m[0] > i_max_ma:
        ok = False
        res["checks"].append(u"ток {:.1f} мА > {:.1f} мА".format(tail_m[0], i_max_ma))
    if r_max_ohm and r_loop > r_max_ohm:
        ok = False
        res["checks"].append(u"R линии {:.1f} Ом > {:.1f} Ом".format(r_loop, r_max_ohm))
    res["ok"] = ok
    return res


def _cands(rules):
    c = rules.get("cable", {})
    ms = c.get("min_section_mm2", 0)
    return [x for x in sorted(c.get("candidates", []), key=lambda x: x["section"]) if x["section"] >= ms]


def select_cable(seg_m, cs, cm, rules, u0, u_min, i_max=None, r_max=None):
    """Минимальное сечение из rules.cable.candidates, при котором линия проходит все проверки."""
    last = None
    for c in _cands(rules):
        e = line_electrics(seg_m, cs, cm, c["r_ohm_km"], u0, u_min, i_max, r_max)
        e["cable"], e["section"] = c["mark"], c["section"]
        last = e
        if e["ok"]:
            return e
    if last is not None:
        last["checks"].append(u"даже максимальное сечение не проходит — разделить линию или добавить источник питания")
    return last


def electrics_for_docs(docs, devs, ven, rules):
    """Подбор сечения и расчёт для каждой линии из build_docs по строкам кабельного журнала."""
    el = ven.get("electrical", {})
    sl = rules.get("sounder_line", {})
    out = []
    for r in docs["scheme"]:
        seg_m = [j["length_m"] for j in docs["journal"] if j["line"] == r["line"]]
        if r["kind"] == "loop":
            items = sorted([d for d in devs if d.get("loop") == r["line"]], key=lambda d: _num(d.get("addr")))
            dc = el.get("device_current_ma", {})
            cs = [dc.get(d["role"], {}).get("standby", 0.0) for d in items]
            cm = [dc.get(d["role"], {}).get("max", 0.0) for d in items]
            u0 = el.get("loop_voltage_v", 0)
            e = select_cable(seg_m, cs, cm, rules, u0, el.get("min_end_voltage_v", 0),
                             el.get("loop_max_current_ma"), el.get("max_loop_resistance_ohm"))
            e["demo"] = bool(el.get("demo"))
        elif r["kind"] == "voice":
            vc = rules.get("voice", {})
            u0 = vc.get("line_voltage_v", 100)
            items = [d for d in devs if d["role"] == "speaker" and d.get("line") == r["line"]]
            cm = [1000.0 * d.get("power_w", 0) / u0 for d in items] or [0.0] * len(seg_m)
            e = select_cable(seg_m, [0.0] * len(cm), cm, rules, u0, vc.get("min_end_voltage_v", 90))
            e["demo"] = True
        else:
            c = sl.get("device_current_ma", 0.0)
            u0 = sl.get("voltage_v", 0)
            e = select_cable(seg_m, [0.0] * len(seg_m), [c] * len(seg_m), rules, u0, sl.get("min_end_voltage_v", 0))
            e["demo"] = True
        e["u0_v"] = u0
        e["kind"] = r["kind"]
        e["line"] = r["line"]
        e["length_m"] = r["length_m"]
        e["count"] = r["count"]
        out.append(e)
    return out


def power_budget(elec, docs, ven, rules):
    """
    Ёмкость резервной АКБ: C = k · (Iдеж·Tдеж + Iтрев·Tтрев).
    Ток адресных линий пересчитывается к напряжению АКБ через мощность и КПД преобразователя.
    """
    pw = rules.get("power", {})
    el = ven.get("electrical", {})
    ub = float(pw.get("battery_voltage_v", 24))
    eta = float(pw.get("converter_efficiency", 0.8)) or 1.0
    n_panels = 0
    for s in docs["spec"]:
        if s["name"].startswith(u"Прибор"):
            n_panels = s["qty"]
    pc = el.get("panel_current_ma", {})
    rows = [{"name": u"{} × {}".format(ven["panel"]["model"], n_panels),
             "standby_ma": pc.get("standby", 0) * n_panels, "alarm_ma": pc.get("alarm", 0) * n_panels}]
    for e in elec:
        if e["kind"] == "loop":
            k = e["u0_v"] / (ub * eta)
            rows.append({"name": u"{} (пересчёт {:.0f}→{:.0f} В, КПД {:.0%})".format(e["line"], e["u0_v"], ub, eta),
                         "standby_ma": rnd(e["i_standby_ma"] * k, 2), "alarm_ma": rnd(e["i_max_ma"] * k, 2)})
        elif e["kind"] == "voice":
            continue
        else:
            rows.append({"name": e["line"], "standby_ma": 0.0, "alarm_ma": e["i_max_ma"]})
    amp = ven.get("voice_amp", {})
    voice_w = sum(r.get("power_w", 0) for r in docs["scheme"] if r["kind"] == "voice")
    if voice_w:
        n_amp = 0
        for s in docs["spec"]:
            if s["name"].startswith(u"Прибор / усилитель речевого"):
                n_amp = s["qty"]
        eff = float(amp.get("efficiency", 0.6)) or 1.0
        rows.append({"name": u"Речевое оповещение: {} × {} ({} Вт, КПД {:.0%})".format(n_amp, amp.get("model", u""), rnd(voice_w, 1), eff),
                     "standby_ma": float(amp.get("standby_ma", 0)) * n_amp,
                     "alarm_ma": rnd(float(amp.get("standby_ma", 0)) * n_amp + 1000.0 * voice_w / (ub * eff), 2)})
    for x in pw.get("extra_consumers", []):
        if x.get("standby_ma") or x.get("alarm_ma"):
            rows.append({"name": x["name"], "standby_ma": x.get("standby_ma", 0), "alarm_ma": x.get("alarm_ma", 0)})
    i_st = sum(r["standby_ma"] for r in rows) / 1000.0
    i_al = sum(r["alarm_ma"] for r in rows) / 1000.0
    t_st, t_al = float(pw.get("standby_hours", 24)), float(pw.get("alarm_hours", 3))
    kf = float(pw.get("aging_factor", 1.25))
    c = kf * (i_st * t_st + i_al * t_al)
    std = [a for a in pw.get("standard_batteries_ah", []) if a >= c]
    pick = std[0] if std else None
    nblk = max(1, int(rnd(ub / float(pw.get("battery_block_v", 12)))))
    return {"rows": rows, "i_standby_a": rnd(i_st, 3), "i_alarm_a": rnd(i_al, 3),
            "t_standby_h": t_st, "t_alarm_h": t_al, "k": kf, "c_required_ah": rnd(c, 2),
            "battery_ah": pick, "blocks": nblk, "block_v": pw.get("battery_block_v", 12), "battery_v": ub,
            "formula": u"C = {} × ({:.3f} А × {:.0f} ч + {:.3f} А × {:.0f} ч) = {:.2f} А·ч".format(
                kf, i_st, t_st, i_al, t_al, c)}


def full_docs(devs, panel, ven, rules):
    """Двухпроходная сборка: журнал → подбор сечения → журнал/спецификация с выбранными кабелями → АКБ."""
    d1 = build_docs(devs, panel, ven, rules)
    elec = electrics_for_docs(d1, devs, ven, rules)
    d2 = build_docs(devs, panel, ven, rules, dict((e["line"], e["cable"]) for e in elec if e.get("cable")))
    pb = power_budget(elec, d2, ven, rules)
    if pb["battery_ah"]:
        d2["spec"].insert(1, {"group": u"Оборудование", "name": u"Батарея аккумуляторная {} В".format(pb["block_v"]),
                              "mark": u"{} А·ч (по расчёту)".format(pb["battery_ah"]), "maker": u"", "unit": u"шт",
                              "qty": pb["blocks"], "note": u"для РИП {:.0f} В; Cтреб = {} А·ч".format(pb["battery_v"], pb["c_required_ah"])})
        for i, row in enumerate(d2["spec"], 1):
            row["pos"] = i
    d2["electrics"] = elec
    d2["power"] = pb
    return d2


# ---------- этаж целиком + уточняющий диалог ----------

def obstacles_for_room(room, lines, points, zone):
    """Препятствия в зоне потолка помещения (в плане — в габарите помещения с запасом 2 м)."""
    x0, y0, x1, y1 = bbox(room["poly"])
    pad = 2000.0
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    cz, fz = room["ceiling_z"], room["floor_z"]

    def in_zone(o):
        return o["z_top"] >= cz - zone and o["z_bot"] <= cz + 50 and o["z_top"] > fz

    pts = [o for o in points if x0 <= o["x"] <= x1 and y0 <= o["y"] <= y1 and in_zone(o)]
    lns = [o for o in lines
           if max(o["x1"], o["x2"]) >= x0 and min(o["x1"], o["x2"]) <= x1
           and max(o["y1"], o["y2"]) >= y0 and min(o["y1"], o["y2"]) <= y1 and in_zone(o)]
    return pts, lns


def find_partitions(poly, lines, ph):
    x0, y0, x1, y1 = bbox(poly)
    m = min(x1 - x0, y1 - y0)
    return [o for o in lines if ph > 0 and o.get("h", 0) >= ph
            and seg_len_inside(o["x1"], o["y1"], o["x2"], o["y2"], poly) >= 0.5 * m]


def clip_halfplane(poly, o, side):
    """Часть полигона по одну сторону от прямой, проходящей через ось препятствия (Сазерленд–Ходжмен)."""
    def f(p):
        return (o["x2"] - o["x1"]) * (p[1] - o["y1"]) - (o["y2"] - o["y1"]) * (p[0] - o["x1"])
    sgn = 1.0 if side else -1.0
    res = []
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        fa, fb = sgn * f(a), sgn * f(b)
        if fa >= 0:
            res.append((a[0], a[1]))
        if (fa >= 0) != (fb >= 0):
            t = fa / (fa - fb)
            res.append((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
    return res if len(res) >= 3 and area(res) > 1e4 else None


def split_poly(poly, split_lines):
    parts = [poly]
    for o in split_lines:
        nxt = []
        for p in parts:
            for side in (True, False):
                c = clip_halfplane(p, o, side)
                if c:
                    nxt.append(c)
        parts = nxt
    return parts


def plan_rooms(rooms, lines, points, rules):
    """
    Расстановка по списку помещений с учётом ответов диалога (rules.room_overrides).
    Возвращает список результатов; у каждого есть 'questions' — уточняющие вопросы.
    """
    pl = rules["placement"]
    ob = rules["obstacles"]
    ovr_all = rules.get("room_overrides", {}) or {}
    out = []
    for r in rooms:
        key = room_key(r.get("level"), r.get("number"), r.get("name"))
        ovr = ovr_all.get(key, {})
        label = u"{} {}".format(r.get("number") or u"", r.get("name") or u"").strip()
        item = {"room": r, "key": key, "label": label, "role": None, "points": [], "problem": False,
                "note": u"", "questions": [], "override": ovr, "row": None}
        if r.get("area_m2", 0) < pl.get("skip_rooms_smaller_m2", 0):
            item["note"] = u"меньше минимальной площади"
            out.append(item)
            continue
        action, role, src = classify_room(r.get("name"), rules.get("room_rules", []), pl["default_detector"],
                                          pl.get("default_action", "place"), ovr)
        item["source"] = src
        if src == "default" and not any(k.lower() in (r.get("name") or u"").lower() for k in pl.get("known_rooms", [])):
            item["questions"].append({
                "kind": "room_type",
                "text": u"Помещение «{}» не распознано по названию. Как его защищать?".format(label),
                "options": [{"label": u"Дымовой", "patch": {"action": "place", "detector": "smoke"}},
                            {"label": u"Тепловой", "patch": {"action": "place", "detector": "heat"}},
                            {"label": u"Не защищать", "patch": {"action": "skip"}}]})
        if action == "skip":
            item["note"] = u"не защищается ({})".format(u"ответ в диалоге" if src == "override" else u"по правилу")
            out.append(item)
            continue
        item["role"] = role
        h = float(ovr.get("ceiling_h") or r["ceiling_h"])
        row = pick_row(rules["detectors"][role]["table"], h)
        if row is None:
            item["problem"] = True
            item["note"] = u"высота {:.0f} мм вне таблицы норм".format(h)
            item["questions"].append({
                "kind": "height",
                "text": u"«{}»: высота потолка {:.0f} мм вне таблицы норм. Как поступить?".format(label, h),
                "options": [{"label": u"Указать высоту вручную", "input": "ceiling_h", "unit": u"мм"},
                            {"label": u"Не защищать точечными (линейные — вручную)", "patch": {"action": "skip"}}]})
            out.append(item)
            continue
        item["row"] = row
        pts, lns = obstacles_for_room(r, lines, points, ob["zone_below_ceiling"])
        cfg = {"wall_min": pl["wall_min"], "min_per_room": ovr.get("min_per_room", pl["min_per_room"]),
               "max_shift": ovr.get("max_shift", pl["max_shift"]), "sample_step": pl["sample_step"],
               "clear": ob["clear"], "partition_height": ob["partition_height"]}
        parts = [r["poly"]]
        if ovr.get("split_zones") is True:
            parts = split_poly(r["poly"], find_partitions(r["poly"], lns, ob["partition_height"]))
            cfg["no_split"] = True
        elif ovr.get("split_zones") is False:
            cfg["no_split"] = True
        res = None
        for part in parts:   # каждая зона рассчитывается как отдельное помещение
            rp = plan_room(part, r.get("holes") or [], h, row, pts, lns, cfg)
            if res is None:
                res = rp
            else:
                for k in ("points", "issues", "partitions"):
                    res[k] = res[k] + rp[k]
                for k in ("shifted", "added", "need"):
                    res[k] += rp[k]
        if len(parts) > 1:
            res["issues"] = res["issues"]
            res["zones"] = len(parts)
        item["points"] = res["points"]
        item["res"] = res
        notes = []
        if res["shifted"]:
            notes.append(u"сдвинуто из-за смежников: {}".format(res["shifted"]))
        notes += res["issues"]
        if res.get("zones"):
            notes.append(u"рассчитано по {} зонам".format(res["zones"]))
        if ovr.get("manual"):
            notes.append(u"отмечено для ручной доработки")
        item["note"] = u"; ".join(notes) or u"ок"
        item["problem"] = bool(res["issues"]) or bool(ovr.get("manual"))
        if res["partitions"]:
            o = res["partitions"][0]
            item["questions"].append({
                "kind": "split",
                "text": u"«{}»: {} высотой {:.0f} мм пересекает потолок. Делит ли он помещение на зоны?".format(
                    label, kind_ru(o.get("kind")), o.get("h", 0)),
                "options": [{"label": u"Да — защищать каждую зону", "patch": {"split_zones": True}},
                            {"label": u"Нет", "patch": {"split_zones": False}}]})
        if any((u"не размещена" in s or u"не покрыта" in s) for s in res["issues"]) and not ovr.get("manual"):
            item["questions"].append({
                "kind": "blocked",
                "text": u"«{}»: часть зоны не удалось защитить из-за смежных сетей. Что сделать?".format(label),
                "options": [{"label": u"Разрешить сдвиг до 2,5 м", "patch": {"max_shift": 2500}},
                            {"label": u"Оставить для ручной доработки", "patch": {"manual": True}}]})
        out.append(item)
    return out


def apply_patch(rules, patch):
    """Применить ответ мастера/диалога к правилам. '$room_rules': {id: {...}} правит записи room_rules по id."""
    for k, v in patch.items():
        if k == "$room_rules":
            for rid, fields in v.items():
                for rr in rules.get("room_rules", []):
                    if rr.get("id") == rid:
                        rr.update(fields)
                        if fields.get("action") == "skip":
                            rr.pop("detector", None)
        elif isinstance(v, dict) and isinstance(rules.get(k), dict) and k != "room_overrides":
            apply_patch(rules[k], v)
        else:
            rules[k] = v
    return rules


# ---------- речевое оповещение ----------

def spl_at(px, py, speakers, tap_w, spl1, dz_mm):
    """Уровень звука в точке (дБА) — энергетическая сумма всех громкоговорителей; r не меньше 1 м."""
    e = 0.0
    for (sx, sy) in speakers:
        r = max(1.0, math.sqrt((px - sx) ** 2 + (py - sy) ** 2 + dz_mm ** 2) / 1000.0)
        e += 10 ** ((spl1 + 10 * math.log10(tap_w) - 20 * math.log10(r)) / 10.0)
    return 10 * math.log10(e) if e > 0 else -999.0


def place_speakers(poly, holes, ceiling_h, vc, obst_points, obst_lines, clear, wall_min=100.0):
    """
    Потолочные громкоговорители: перебор шага сетки (от большего к меньшему) и отводов мощности
    (от меньшего к большему); принимается первый вариант, где во всех точках на высоте слушателя
    уровень >= max(required_db_min, noise_db + margin_db) и <= max_db.
    """
    need = max(float(vc.get("required_db_min", 75)), float(vc.get("noise_db", 50)) + float(vc.get("margin_db", 15)))
    dz = max(500.0, ceiling_h - float(vc.get("listener_height", 1500)))
    spl1 = float(vc.get("speaker_spl_1w_1m", 90))
    taps = sorted(vc.get("taps_w", [1]))
    minx, miny, maxx, maxy = bbox(poly)
    L, B = maxx - minx, maxy - miny
    step = float(vc.get("sample_step", 1000))
    samples = []
    yy = miny + step / 2
    while yy < maxy:
        xx = minx + step / 2
        while xx < maxx:
            if inside_room(xx, yy, poly, holes):
                samples.append((xx, yy))
            xx += step
        yy += step
    if not samples:
        samples = [((minx + maxx) / 2, (miny + maxy) / 2)]
    ok = make_checker(poly, holes, obst_points, obst_lines, wall_min, clear)
    s = float(vc.get("spacing_max", 12000))
    smin = float(vc.get("spacing_min", 2000))
    last = None
    while s >= smin - 1e-6:
        nx = max(1, int(math.ceil(L / s - 1e-9)))
        ny = max(1, int(math.ceil(B / s - 1e-9)))
        pts = []
        for i in range(nx):
            for j in range(ny):
                x, y = minx + L * (2 * i + 1) / (2.0 * nx), miny + B * (2 * j + 1) / (2.0 * ny)
                if inside_room(x, y, poly, holes):
                    p, _ = relocate(x, y, ok, 1500.0)
                    if p is not None:
                        pts.append(p)
        if pts:
            for t in taps:
                lv = [spl_at(a, b, pts, t, spl1, dz) for (a, b) in samples]
                mn, mx = min(lv), max(lv)
                last = (pts, t, mn, mx)
                if mn >= need and mx <= float(vc.get("max_db", 120)):
                    return {"points": pts, "tap_w": t, "spl_min": rnd(mn, 1), "spl_max": rnd(mx, 1),
                            "need_db": need, "issues": []}
        s -= 500.0
    pts, t, mn, mx = last if last else ([], taps[-1], 0, 0)
    return {"points": pts, "tap_w": t, "spl_min": rnd(mn, 1), "spl_max": rnd(mx, 1), "need_db": need,
            "issues": [u"требуемый уровень {:.0f} дБА не достигнут (мин. {:.1f}) — нужен более мощный громкоговоритель или настенные".format(need, mn)]}


def plan_voice(rooms, lines, points, rules):
    """Речевое оповещение по помещениям; результат на помещение: points, tap_w, spl_min/max, issues."""
    vc = rules.get("voice", {})
    if not vc.get("enabled"):
        return []
    pl = rules["placement"]
    out = []
    for r in rooms:
        name = (r.get("name") or u"").lower()
        hit = any(k.lower() in name for k in vc.get("room_keywords", []))
        if not hit and vc.get("all_protected_rooms"):
            key = room_key(r.get("level"), r.get("number"), r.get("name"))
            action, _, _ = classify_room(r.get("name"), rules.get("room_rules", []), pl["default_detector"],
                                         "place", (rules.get("room_overrides") or {}).get(key))
            hit = action == "place"
        if not hit:
            continue
        pts, lns = obstacles_for_room(r, lines, points, rules["obstacles"]["zone_below_ceiling"])
        res = place_speakers(r["poly"], r.get("holes") or [], float(r["ceiling_h"]), vc, pts, lns,
                             rules["obstacles"]["clear"], pl.get("wall_min", 100))
        res["room"] = r
        res["label"] = u"{} {}".format(r.get("number") or u"", r.get("name") or u"").strip()
        out.append(res)
    return out


# ---------- DXF для AutoCAD (R12, ASCII, кодировка 1251) ----------

DXF_LAYERS = [(u"АПС_Помещения", 8), (u"АПС_Смежники", 9), (u"АПС_Извещатели", 1), (u"АПС_ИПР", 6),
              (u"АПС_Оповещатели", 4), (u"АПС_Речевое", 5), (u"АПС_Шлейфы", 3), (u"АПС_Марки", 7), (u"АПС_Прибор", 2)]
DXF_ROLE = {"smoke": ("APS_SMOKE", u"АПС_Извещатели"), "heat": ("APS_HEAT", u"АПС_Извещатели"),
            "mcp": ("APS_MCP", u"АПС_ИПР"), "sounder": ("APS_SOUNDER", u"АПС_Оповещатели"),
            "speaker": ("APS_SPEAKER", u"АПС_Речевое"), "panel": ("APS_PANEL", u"АПС_Прибор")}


def _f(v):
    s = u"{:.3f}".format(v).rstrip(u"0").rstrip(u".")
    return u"0" if s in (u"-0", u"") else s


class Dxf(object):
    """Минимальный писатель DXF R12. Блоки-заглушки APS_* переопредели своими УГО — вставки обновятся."""

    def __init__(self):
        self.ent = []

    def _e(self, *pairs):
        for c, v in pairs:
            self.ent.append(u"{}\n{}".format(c, v))

    def line(self, x1, y1, x2, y2, layer):
        self._e((0, u"LINE"), (8, layer), (10, _f(x1)), (20, _f(y1)), (30, u"0"), (11, _f(x2)), (21, _f(y2)), (31, u"0"))

    def poly(self, pts, layer, closed=False):
        n = len(pts)
        for i in range(n if closed else n - 1):
            a, b = pts[i], pts[(i + 1) % n]
            self.line(a[0], a[1], b[0], b[1], layer)

    def circle(self, x, y, r, layer):
        self._e((0, u"CIRCLE"), (8, layer), (10, _f(x)), (20, _f(y)), (30, u"0"), (40, _f(r)))

    def text(self, x, y, h, s, layer):
        self._e((0, u"TEXT"), (8, layer), (10, _f(x)), (20, _f(y)), (30, u"0"), (40, _f(h)), (1, s))

    def insert(self, block, x, y, layer, rot=0.0):
        self._e((0, u"INSERT"), (8, layer), (2, block), (10, _f(x)), (20, _f(y)), (30, u"0"), (50, _f(rot)))

    @staticmethod
    def _blocks():
        out = []

        def blk(name, ents):
            out.append(u"0\nBLOCK\n8\n0\n2\n{}\n70\n0\n10\n0\n20\n0\n30\n0\n3\n{}".format(name, name))
            out.extend(ents)
            out.append(u"0\nENDBLK\n8\n0")

        def c(r):
            return u"0\nCIRCLE\n8\n0\n10\n0\n20\n0\n30\n0\n40\n{}".format(_f(r))

        def l(x1, y1, x2, y2):
            return u"0\nLINE\n8\n0\n10\n{}\n20\n{}\n30\n0\n11\n{}\n21\n{}\n31\n0".format(_f(x1), _f(y1), _f(x2), _f(y2))

        def t(s, h=200):
            return u"0\nTEXT\n8\n0\n10\n{}\n20\n{}\n30\n0\n40\n{}\n1\n{}".format(_f(-h * 0.35), _f(-h / 2), _f(h), s)

        sq = [l(-250, -250, 250, -250), l(250, -250, 250, 250), l(250, 250, -250, 250), l(-250, 250, -250, -250)]
        blk("APS_SMOKE", [c(250), t(u"Д")])
        blk("APS_HEAT", [c(250), t(u"Т")])
        blk("APS_MCP", sq + [t(u"Р")])
        blk("APS_SOUNDER", [l(-250, -200, 250, -200), l(250, -200, 0, 250), l(0, 250, -250, -200)])
        blk("APS_SPEAKER", [c(250), l(-150, -150, 150, 150), l(-150, 150, 150, -150)])
        blk("APS_PANEL", [l(-400, -250, 400, -250), l(400, -250, 400, 250), l(400, 250, -400, 250),
                          l(-400, 250, -400, -250), t(u"П", 250)])
        return out

    def text_out(self):
        hdr = [u"0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n9\n$DWGCODEPAGE\n3\nANSI_1251\n9\n$INSUNITS\n70\n4\n0\nENDSEC"]
        tab = [u"0\nSECTION\n2\nTABLES",
               u"0\nTABLE\n2\nLTYPE\n70\n1\n0\nLTYPE\n2\nCONTINUOUS\n70\n0\n3\nSolid line\n72\n65\n73\n0\n40\n0\n0\nENDTAB",
               u"0\nTABLE\n2\nLAYER\n70\n{}".format(len(DXF_LAYERS) + 1),
               u"0\nLAYER\n2\n0\n70\n0\n62\n7\n6\nCONTINUOUS"]
        for name, col in DXF_LAYERS:
            tab.append(u"0\nLAYER\n2\n{}\n70\n0\n62\n{}\n6\nCONTINUOUS".format(name, col))
        tab += [u"0\nENDTAB", u"0\nTABLE\n2\nSTYLE\n70\n1\n0\nSTYLE\n2\nSTANDARD\n70\n0\n40\n0\n41\n1\n50\n0\n71\n0\n42\n2.5\n3\ntxt\n4\n\n0\nENDTAB", u"0\nENDSEC"]
        blocks = [u"0\nSECTION\n2\nBLOCKS"] + self._blocks() + [u"0\nENDSEC"]
        ents = [u"0\nSECTION\n2\nENTITIES"] + self.ent + [u"0\nENDSEC", u"0\nEOF"]
        return u"\n".join(hdr + tab + blocks + ents) + u"\n"


def dxf_plan(rooms, lines, points, devs, panel):
    """План уровня для AutoCAD: помещения, смежники, устройства (блоки), шлейфы, марки адресов. Единицы — мм."""
    d = Dxf()
    for r in rooms:
        d.poly(r["poly"], u"АПС_Помещения", True)
        for h in r.get("holes") or []:
            d.poly(h, u"АПС_Помещения", True)
        x0, y0, x1, y1 = bbox(r["poly"])
        d.text(x0 + 150, y1 - 450, 250, u"{} {}".format(r.get("number") or u"", r.get("name") or u"").strip(), u"АПС_Помещения")
    if rooms:
        X0, Y0, X1, Y1 = bbox([p for r in rooms for p in r["poly"]])
        for o in lines:
            if max(o["x1"], o["x2"]) >= X0 and min(o["x1"], o["x2"]) <= X1 and max(o["y1"], o["y2"]) >= Y0 and min(o["y1"], o["y2"]) <= Y1:
                dx, dy = o["x2"] - o["x1"], o["y2"] - o["y1"]
                L = math.hypot(dx, dy) or 1.0
                nx, ny = -dy / L * o.get("hw", 0), dx / L * o.get("hw", 0)
                d.poly([(o["x1"] + nx, o["y1"] + ny), (o["x2"] + nx, o["y2"] + ny),
                        (o["x2"] - nx, o["y2"] - ny), (o["x1"] - nx, o["y1"] - ny)], u"АПС_Смежники", True)
        for o in points:
            if X0 <= o["x"] <= X1 and Y0 <= o["y"] <= Y1:
                d.circle(o["x"], o["y"], max(o.get("r", 0), 80), u"АПС_Смежники")
    for dv in devs:
        blk, layer = DXF_ROLE.get(dv["role"], ("APS_SMOKE", u"АПС_Извещатели"))
        d.insert(blk, dv["x"], dv["y"], layer)
        mark = u"{}.{}".format(dv["loop"], dv["addr"]) if dv.get("loop") else (dv.get("line") or u"")
        if dv.get("power_w"):
            mark += u" {}Вт".format(_f(dv["power_w"]))
        if mark:
            d.text(dv["x"] + 300, dv["y"] + 300, 200, mark, u"АПС_Марки")
    if panel:
        d.insert("APS_PANEL", panel[0], panel[1], u"АПС_Прибор")
    loops = {}
    for dv in devs:
        if dv.get("loop"):
            loops.setdefault(dv["loop"], []).append(dv)
    start = (panel[0], panel[1]) if panel else None
    for lid in sorted(loops, key=_num):
        items = sorted(loops[lid], key=lambda q: _num(q.get("addr")))
        prev = start or (items[0]["x"], items[0]["y"])
        for it in items:
            d.line(prev[0], prev[1], it["x"], prev[1], u"АПС_Шлейфы")
            d.line(it["x"], prev[1], it["x"], it["y"], u"АПС_Шлейфы")
            prev = (it["x"], it["y"])
    return d.text_out()
