# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Regresión del reporte de Microsoft Catalog Sync (Dry Run/Apply) en el navegador.

Defecto reproducido: con v0.4.0/v0.4.1 el helper de presentación era una función top-level
"suelta" (`function render_sync_report`) y el `.catch` del handler tragaba en silencio cualquier
excepción → Dry Run no mostraba NADA (ni error ni reporte). El fix expone el helper bajo el namespace
`acti_customs.ms_catalog_sync.render_report` (alcanzable desde el controlador en el bundle del desk,
como hace `quotation_microsoft.js` con `acti_customs.ms`), lo hace defensivo (nunca lanza) y hace que
el handler SIEMPRE muestre un `msgprint` (éxito, respuesta vacía o error).

Los tests cargan el JS real del controlador en Node (stubbeando `frappe`/`__`):
  - `render_report` aislado: definido en el namespace + nunca lanza (null/{}/dry/apply).
  - handler real de Dry Run: ejercita el botón capturado de `frm.add_custom_button` con una respuesta
    de `frappe.call` simulada (éxito / vacía / rechazo) y verifica que `frappe.msgprint` se invoca con
    el contenido correcto en cada caso. No basta con probar `render_report` aislado.
"""

import json
import os
import shutil
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

_APP = frappe.get_app_path("acti_customs")
JS_FILE = os.path.join(
	_APP, "acti_customizations", "doctype", "microsoft_catalog_sync", "microsoft_catalog_sync.js"
)

_DRY_PAYLOAD = """{ dry_run: true, sheet: "Jan_NCE", price_list: "Microsoft NCE - Compra",
  target_company: "C", rows_read: 3932, rows_valid: 3930, items_new: 120, items_existing: 3808,
  items_reactivated: 0, items_needing_transition: 0, items_to_retire: 2, errors: [],
  details: { new: ["MS-A"], reactivated: [], to_retire: ["MS-X"], needs_transition: [] } }"""

# --- Harness 1: render_report aislado ---
_RENDER_HARNESS = r"""
const fs = require("fs");
global.frappe = {
  provide: (ns) => { const p = ns.split("."); let o = global; for (const x of p) { o[x] = o[x] || {}; o = o[x]; } return o; },
  ui: { form: { on: () => {} } },
  defaults: { get_default: () => null },
  utils: { escape_html: (s) => String(s == null ? "" : s), cint: (n) => { n = parseInt(n, 10); return isNaN(n) ? 0 : n; } },
};
global.__ = (s) => s;
eval(fs.readFileSync(process.argv[1], "utf8"));
const RR = global.acti_customs && global.acti_customs.ms_catalog_sync && global.acti_customs.ms_catalog_sync.render_report;
const out = { defined: typeof RR === "function", cases: {} };
if (out.defined) {
  const dry = __DRY__;
  const apply = Object.assign({}, dry, { applied: { items_created: 120, items_updated: 3808, items_reactivated: 0,
    prices_upserted: 3928, item_defaults_set: 3928, items_retired: 2, row_errors: [] } });
  for (const [n, p] of [["dry", dry], ["apply", apply], ["null", null], ["empty", {}]]) {
    try { const o = RR(p); out.cases[n] = { ok: !!(o && typeof o.message === "string" && o.message.length > 0) }; }
    catch (e) { out.cases[n] = { ok: false, threw: e.message }; }
  }
}
process.stdout.write(JSON.stringify(out));
""".replace("__DRY__", _DRY_PAYLOAD)

# --- Harness 2: handler REAL de Dry Run (botón → frappe.call simulado → frappe.msgprint) ---
_HANDLER_HARNESS = r"""
const fs = require("fs");
let msgprintCalls = [];
let callBehavior = () => Promise.resolve({ message: {} });
let formHandlers = null;
global.frappe = {
  provide: (ns) => { const p = ns.split("."); let o = global; for (const x of p) { o[x] = o[x] || {}; o = o[x]; } return o; },
  ui: { form: { on: (dt, h) => { formHandlers = h; } } },
  dom: { freeze: () => {}, unfreeze: () => {} },
  defaults: { get_default: () => null },
  confirm: (m, cb) => cb && cb(),
  utils: { escape_html: (s) => String(s == null ? "" : s), cint: (n) => { n = parseInt(n, 10); return isNaN(n) ? 0 : n; } },
  call: (opts) => callBehavior(opts),
  msgprint: (a) => { msgprintCalls.push(a); },
};
global.__ = (s) => s;
eval(fs.readFileSync(process.argv[1], "utf8"));

const buttons = {};
const frm = {
  doc: { catalog_file: "/private/files/catalogo.xlsx", target_company: "C" },
  add_custom_button: (label, cb) => { buttons[label] = cb; },
  set_value: () => {},
  reload_doc: () => Promise.resolve(),
  is_new: () => false,
};
formHandlers.refresh(frm);
const dryRun = buttons["Dry Run"];
const flush = () => new Promise((r) => setImmediate(r));
const dry = __DRY__;

(async () => {
  const out = { button_registered: typeof dryRun === "function" };

  // 1) Éxito: debe invocar msgprint con el reporte (indicator azul, mensaje presente, título Dry Run).
  msgprintCalls = []; callBehavior = () => Promise.resolve({ message: dry });
  dryRun(); await flush(); await flush(); await flush();
  out.success = {
    calls: msgprintCalls.length,
    indicator: (msgprintCalls[0] || {}).indicator,
    hasMessage: typeof (msgprintCalls[0] || {}).message === "string" && (msgprintCalls[0] || {}).message.length > 0,
    titleHasDryRun: String((msgprintCalls[0] || {}).title || "").includes("Dry Run"),
  };

  // 2) Respuesta vacía: aviso explícito (nunca silencio).
  msgprintCalls = []; callBehavior = () => Promise.resolve({ message: null });
  dryRun(); await flush(); await flush(); await flush();
  out.empty = {
    calls: msgprintCalls.length,
    indicator: (msgprintCalls[0] || {}).indicator,
    message: String((msgprintCalls[0] || {}).message || ""),
  };

  // 3) Rechazo (error de backend): mensaje de error comprensible con el detalle.
  msgprintCalls = []; callBehavior = () => Promise.reject(new Error("boom-500"));
  dryRun(); await flush(); await flush(); await flush();
  out.error = {
    calls: msgprintCalls.length,
    indicator: (msgprintCalls[0] || {}).indicator,
    title: String((msgprintCalls[0] || {}).title || ""),
    message: String((msgprintCalls[0] || {}).message || ""),
  };

  process.stdout.write(JSON.stringify(out));
})();
""".replace("__DRY__", _DRY_PAYLOAD)


def _run_node(harness):
	if not shutil.which("node"):
		return None
	r = subprocess.run(["node", "-e", harness, JS_FILE], capture_output=True, text=True)
	if r.returncode != 0:
		raise AssertionError(f"harness node falló: {r.stderr}")
	return json.loads(r.stdout)


class TestCatalogSyncReportRender(FrappeTestCase):
	def setUp(self):
		self.result = _run_node(_RENDER_HARNESS)
		if self.result is None:
			self.skipTest("node no disponible")

	def test_render_report_definido_en_namespace(self):
		# Con el código viejo (función suelta) este símbolo del namespace NO existiría.
		self.assertTrue(
			self.result["defined"],
			"acti_customs.ms_catalog_sync.render_report debe quedar definido al cargar el controlador",
		)

	def test_render_report_siempre_devuelve_mensaje_y_nunca_lanza(self):
		for case in ("dry", "apply", "null", "empty"):
			c = self.result["cases"].get(case, {})
			self.assertTrue(
				c.get("ok"),
				f"render_report({case}) debe devolver un mensaje no vacío sin lanzar; obtuvo: {c}",
			)


class TestCatalogSyncDryRunHandler(FrappeTestCase):
	"""Prueba el handler REAL del botón Dry Run, no render_report aislado."""

	def setUp(self):
		self.out = _run_node(_HANDLER_HARNESS)
		if self.out is None:
			self.skipTest("node no disponible")
		self.assertTrue(self.out["button_registered"], "El botón Dry Run debe registrarse en refresh()")

	def test_dry_run_exitoso_invoca_msgprint_con_reporte(self):
		s = self.out["success"]
		self.assertEqual(s["calls"], 1, "Dry Run exitoso debe invocar msgprint exactamente una vez")
		self.assertEqual(s["indicator"], "blue", "El reporte Dry Run usa indicador azul")
		self.assertTrue(s["hasMessage"], "El msgprint debe llevar el HTML del reporte")
		self.assertTrue(s["titleHasDryRun"], "El título debe identificar el Dry Run")

	def test_dry_run_respuesta_vacia_muestra_aviso(self):
		e = self.out["empty"]
		self.assertEqual(e["calls"], 1, "Respuesta vacía debe mostrar un aviso (nunca silencio)")
		self.assertEqual(e["indicator"], "orange")
		self.assertIn("no devolvió", e["message"])

	def test_dry_run_error_muestra_mensaje_comprensible(self):
		er = self.out["error"]
		self.assertEqual(er["calls"], 1, "Un rechazo del backend debe mostrar un mensaje de error")
		self.assertEqual(er["indicator"], "red")
		self.assertIn("error", er["title"].lower())
		self.assertIn("boom-500", er["message"])
