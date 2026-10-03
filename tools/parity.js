// Прогон JS-порта apsgeom (из APS_Revit.html) на демо-этаже в нескольких вариантах правил.
// node tools/parity.js APS_Revit.html APS.extension/lib/aps_rules.json out.json
"use strict";
const fs = require("fs");
const [htmlPath, rulesPath, outPath] = process.argv.slice(2);
const html = fs.readFileSync(htmlPath, "utf8");
const a = html.indexOf("const G = (() => {"), b = html.indexOf("if (typeof module", a);
const G = new Function(html.slice(a, b) + "; return G;")();
const demo = JSON.parse(html.match(/<script type="application\/json" id="demoData">([\s\S]*?)<\/script>/)[1]);
const base = JSON.parse(fs.readFileSync(rulesPath, "utf8"));
const clone = (o) => JSON.parse(JSON.stringify(o));
const wiz = (rules, id, k) => { const q = rules.wizard.find(q => q.id === id); G.applyPatch(rules, clone(q.options[k].patch)); };

const VARIANTS = [
  ["rubezh_ring_iso", r => {}],
  ["rubezh_radial_iso_sp484", r => { wiz(r, "topology", 1); wiz(r, "norms", 1); }],
  ["bolid_radial_noiso_common", r => { wiz(r, "vendor", 1); wiz(r, "topology", 2); wiz(r, "scope", 1); }],
  ["legacy_no_zones", r => { G.applyPatch(r, { zones: { enabled: false }, isolators: { enabled: false }, loops: { topology: "radial" } }); }],
  ["rubezh_ring_small_cap", r => { G.applyPatch(r, { vendors: { rubezh: { max_addresses_per_loop: 20 } } }); }],
];

function buildDevices(rules, level) {
  const v = rules.vendors[rules.active_vendor], rooms = demo.rooms.filter(r => r.level === level), devs = [];
  const results = G.planRooms(rooms, demo.obstacles.lines, demo.obstacles.points, rules);
  for (const r of results) if (r.role) for (const [x, y] of r.points)
    devs.push({ role: r.role, model: v.devices[r.role].model, level: r.room.level, lz: r.room.floor_z, x, y, z: r.room.ceiling_z, room: r.label,
      room_no: r.room.number || "", room_name: r.room.name || "", room_apt: r.room.apartment || "", room_area: +(r.room.area_m2 || 0) });
  const fz = Math.min(...rooms.map(r => r.floor_z)), cz = Math.max(...rooms.map(r => r.ceiling_z));
  const ext = (demo.devices || []).filter(d => d.z >= fz - 100 && d.z <= cz + 100 && (d.role === "mcp" || d.role === "sounder"));
  for (const d of ext) devs.push({ role: d.role, model: v.devices[d.role].model, level, lz: fz, x: d.x, y: d.y, z: d.z, room: d.room || "", ext: true });
  if (rules.sounders.enabled !== false && !ext.some(d => d.role === "sounder")) {
    const s = rules.sounders;
    for (const r of rooms) {
      if (!s.room_keywords.some(k => (r.name || "").toLowerCase().includes(k.toLowerCase()))) continue;
      const [x0, y0, x1, y1] = G.bbox(r.poly), L = x1 - x0, B = y1 - y0, n = Math.max(1, Math.ceil(Math.max(L, B) / s.spacing));
      for (let i = 0; i < n; i++) {
        const t = (2 * i + 1) / (2 * n), x = L >= B ? x0 + L * t : (x0 + x1) / 2, y = L >= B ? (y0 + y1) / 2 : y0 + B * t;
        if (G.insideRoom(x, y, r.poly, r.holes || [])) devs.push({ role: "sounder", model: v.devices.sounder.model, level: r.level, lz: r.floor_z, x, y, z: r.ceiling_z - (s.mount_below_ceiling || 0), room: `${r.number} ${r.name}` });
      }
    }
  }
  return { devs, rooms };
}

const cases = [];
for (const level of [...new Set(demo.rooms.map(r => r.level))]) for (const [name, patch] of VARIANTS) {
  const rules = clone(base); patch(rules);
  const v = rules.vendors[rules.active_vendor];
  const { devs, rooms } = buildDevices(rules, level);
  const devsIn = clone(devs), panel = demo.panel || null;
  const start = panel ? [panel[0], panel[1]] : [Math.min(...devs.map(d => d.x)), Math.min(...devs.map(d => d.y))];
  const onLoop = Object.entries(v.devices).filter(([, d]) => d.on_loop !== false).map(([k]) => k);
  const cap = Math.floor(v.max_addresses_per_loop * (v.loop_fill_ratio || 1));
  const zones = G.assignZones(devs, rules, start);
  const planned = (rules.zones || {}).enabled || (rules.isolators || {}).enabled;
  const nLoops = planned ? G.planLoops(devs, start, cap, v.loop_name, onLoop, rules, v) : G.assignLoops(devs, start, cap, v.loop_name, onLoop);
  const docs = G.fullDocs(devs, panel, v, rules), checks = G.checkProject(docs, devs, zones, rules, v);
  const dxf = G.dxfPlan(rooms, demo.obstacles.lines, demo.obstacles.points, devs, panel, zones, (rules.loops || {}).topology === "ring");
  cases.push({ name: `${level} / ${name}`, rules, rooms, panel, start, cap, onLoop, planned, devs_in: devsIn,
    out: { n_loops: nLoops, zones, devs, docs, checks, dxf } });
}
fs.writeFileSync(outPath, JSON.stringify({ obstacles: demo.obstacles, cases }));
console.log("cases:", cases.length);
for (const c of cases) console.log(c.name, "loops", c.out.n_loops, "zones", c.out.zones.length, "iso", c.out.devs.filter(d => d.role === "isolator").length,
  "checks", c.out.checks.map(k => k.status[0]).join(""));
