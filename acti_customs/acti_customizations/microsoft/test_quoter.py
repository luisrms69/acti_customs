# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Tests del selector/cotizador sobre Item (ADR-0003). Module test."""

from collections import namedtuple
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import flt

from acti_customs.acti_customizations.microsoft.materializer import ITEM_GROUP, STOCK_UOM, upsert_item
from acti_customs.acti_customizations.microsoft.quoter import (
	QuoterError,
	add_license_as_cost,
	add_license_to_quotation,
	build_required_row,
	get_price_preview,
	next_step,
	price_summary,
	require_whole_qty,
	resolve_cost,
	resolve_path,
	roundup2,
)
from acti_customs.acti_customizations.microsoft.test_materializer import _prereqs

# Imita el ExternalCost NamedTuple del resolver de erpnext_proposals (amount ya en target_currency).
_EC = namedtuple("EC", ["amount", "source", "source_amount", "source_currency", "normalized_currency"])

# Contexto económico explícito del formulario (Quotation nueva/sin persistir).
_NEW_CTX = {"company": "ACME", "currency": "MXN", "transaction_date": "2026-09-28"}


def _fake_resolver(amount, source, currency="USD"):
	"""Devuelve un resolver que ignora args y responde un ExternalCost fijo (para inyectar en tests)."""

	def _r(item_code, uom=None, transaction_date=None, company=None, target_currency=None):
		return _EC(amount, source, amount, "USD", target_currency or currency)

	return _r


def _row(**kw):
	base = {"product_title": "Office 365 E3", "product_id": "PA", "sku_title": "Sku A", "sku_id": "1"}
	base.update(kw)
	return base


class TestQuoter(FrappeTestCase):
	def setUp(self):
		self._quotations = []
		self._cleanup()
		_prereqs()
		self.a_annual_com = upsert_item(
			_row(term_duration="P1Y", billing_plan="Annual", segment="Commercial", unit_price=120)
		)
		self.a_monthly_com = upsert_item(
			_row(term_duration="P1Y", billing_plan="Monthly", segment="Commercial", unit_price=120)
		)
		self.a_annual_edu = upsert_item(
			_row(term_duration="P1Y", billing_plan="Annual", segment="Education", unit_price=200)
		)
		self.trial = upsert_item(
			_row(
				product_title="Prod B",
				product_id="PB",
				sku_title="Sku B",
				sku_id="2",
				term_duration="P1M",
				billing_plan="None",
				segment="Commercial",
				unit_price=0,
			)
		)

	def tearDown(self):
		self._cleanup()

	def _cleanup(self):
		for qn in getattr(self, "_quotations", []):
			if frappe.db.exists("Quotation", qn):
				frappe.delete_doc("Quotation", qn, force=True, ignore_permissions=True)
		for name in frappe.get_all("Item", filters={"item_group": ITEM_GROUP}, pluck="name"):
			frappe.delete_doc("Item", name, force=True, ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- limpieza de test

	# --- selector sobre Item (sin Microsoft Offer) ---
	def test_primer_paso_producto(self):
		r = next_step({})
		self.assertEqual(r["field"], "product_title")
		self.assertEqual({o["value"] for o in r["options"]}, {"Office 365 E3", "Prod B"})

	def test_prompt_billing_para_prod_a(self):
		r = next_step({"product_title": "Office 365 E3"})
		self.assertEqual(r["field"], "billing_plan")
		self.assertEqual({o["value"] for o in r["options"]}, {"Annual", "Monthly"})

	def test_resuelve_tras_billing(self):
		r = next_step({"product_title": "Office 365 E3", "billing_plan": "Monthly"})
		self.assertIn("resolved", r)
		self.assertEqual(r["resolved"]["item"], self.a_monthly_com)

	def test_resolve_path_cambia_anterior_descarta_dependientes(self):
		r = resolve_path({"product_title": "Prod B", "billing_plan": "Monthly"})  # Monthly inválido en Prod B
		self.assertIn("resolved", r)
		self.assertEqual(r["resolved"]["item"], self.trial)

	def test_trial_labels(self):
		r = resolve_path({"product_title": "Prod B"})
		self.assertIn("resolved", r)
		self.assertTrue(r["resolved"]["is_trial"])
		self.assertEqual(r["resolved"]["compromiso"], "Prueba 1 mes")
		self.assertEqual(r["resolved"]["facturacion"], "")

	def test_selector_no_crea_item(self):
		before = frappe.db.count("Item")
		next_step({"product_title": "Office 365 E3"})
		resolve_path({"product_title": "Prod B"})
		self.assertEqual(frappe.db.count("Item"), before)

	def test_sin_dependencia_microsoft_offer(self):
		# El selector resuelve consultando Item (no Microsoft Offer): funciona aunque el DocType
		# viejo no esté presente en el código (los datos viejos se reconstruyen desde Excel).
		r = resolve_path({"product_title": "Prod B"})
		self.assertIn("resolved", r)
		self.assertEqual(r["resolved"]["item"], self.trial)

	def _legacy_item(self):
		"""Item legacy/manual en el mismo Item Group pero SIN ms_product_id (no NCE)."""
		doc = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "LEGACY-NO-NCE-SEL",
				"item_name": "Legacy no NCE (selector)",
				"item_group": ITEM_GROUP,
				"stock_uom": STOCK_UOM,
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
		return doc.name

	def test_selector_excluye_items_sin_ms_product_id(self):
		# Mismo criterio NCE que el sync (_plan): el selector solo considera Items con ms_product_id set.
		self._legacy_item()
		# 1) el legacy NO aparece como opción de primer paso (no infla la lista de Producto)...
		r = next_step({})
		self.assertEqual(r["field"], "product_title")
		values = {o["value"] for o in r["options"]}
		self.assertEqual(values, {"Office 365 E3", "Prod B"})  # solo los NCE reales; sin opción en blanco
		self.assertNotIn("", values)  # ms_product_title NULL del legacy no crea opción vacía
		self.assertNotIn("Legacy no NCE (selector)", values)
		# 2) ...y los Items NCE siguen resolviéndose igual (sin cambio de comportamiento).
		self.assertEqual(
			next_step({"product_title": "Office 365 E3", "billing_plan": "Monthly"})["resolved"]["item"],
			self.a_monthly_com,
		)
		self.assertEqual(resolve_path({"product_title": "Prod B"})["resolved"]["item"], self.trial)

	def _shared_skuid_items(self):
		"""Dos ofertas que comparten product_title+sku_title pero difieren en sku_id (NO visible) y term."""
		a = upsert_item(
			_row(
				product_title="Prod C",
				product_id="PC",
				sku_title="Sku C",
				sku_id="10",
				term_duration="P1M",
				billing_plan="Monthly",
				segment="Commercial",
				unit_price=50,
			)
		)
		b = upsert_item(
			_row(
				product_title="Prod C",
				product_id="PC",
				sku_title="Sku C",
				sku_id="20",
				term_duration="P1Y",
				billing_plan="Annual",
				segment="Commercial",
				unit_price=120,
			)
		)
		return a, b

	def test_sku_id_ambiguo_no_congela_gui(self):
		# Regresión (bloqueador GUI): un sku_title con >1 sku_id es una ambigüedad en una dimensión
		# NO visible. El JS solo envía dimensiones VISIBLE (product_title/sku_title/term/billing/segment);
		# resolve_path NO debe emitir un paso sku_id/product_id (el GUI no puede presentarlo) ni congelarse:
		# difiere el disambiguador interno y pide una dimensión VISIBLE.
		a, b = self._shared_skuid_items()
		r = resolve_path({"product_title": "Prod C", "sku_title": "Sku C"})
		self.assertNotIn("resolved", r)
		self.assertNotIn("error", r)
		fields = [s["field"] for s in r["steps"]]
		self.assertNotIn("sku_id", fields)  # dimensión no-visible: nunca se expone como paso
		self.assertNotIn("product_id", fields)
		amb = [s for s in r["steps"] if s.get("ambiguous")]
		self.assertTrue(amb and amb[0]["field"] == "term_duration")  # avanza a compromiso (visible)
		# al elegir la dimensión visible, la oferta correcta resuelve (sku_id se fija solo)
		r2 = resolve_path({"product_title": "Prod C", "sku_title": "Sku C", "term_duration": "P1Y"})
		self.assertIn("resolved", r2)
		self.assertEqual(r2["resolved"]["item"], b)
		# y el camino P1M resuelve la otra oferta
		r3 = resolve_path({"product_title": "Prod C", "sku_title": "Sku C", "term_duration": "P1M"})
		self.assertEqual(r3["resolved"]["item"], a)

	def test_next_step_difiere_dimension_no_visible_ambigua(self):
		# next_step (API paralela) también difiere sku_id ambiguo y pide la dimensión visible.
		self._shared_skuid_items()
		r = next_step({"product_title": "Prod C", "sku_title": "Sku C"})
		self.assertNotIn("resolved", r)
		self.assertEqual(r.get("field"), "term_duration")  # no "sku_id"

	# --- pricing bruto puro (costo como entrada; no recalcula /12) ---
	def _summary(self, item, **kw):
		base = {
			"item": item,
			"display": "X",
			"sku_title": "S",
			"compromiso": "c",
			"facturacion": "f",
			"is_trial": False,
			"segment": "Commercial",
		}
		base.update(kw)
		return base

	def test_price_summary_margen_bruto(self):
		s = price_summary(self._summary(self.a_monthly_com), cost=504, qty=2, margin_pct=20)
		self.assertEqual(s["cost_unit"], 504.0)
		self.assertEqual(s["price_unit"], 630.0)  # ROUNDUP(504/0.8,2)
		self.assertEqual(s["amount"], 1260.0)

	def test_price_summary_trial_cero(self):
		s = price_summary(self._summary(self.trial, is_trial=True), cost=0, qty=5, margin_pct=20)
		self.assertEqual(s["price_unit"], 0.0)
		self.assertEqual(s["amount"], 0.0)

	def test_roundup(self):
		self.assertEqual(roundup2(11.7647), 11.77)

	def test_price_summary_margen_invalido(self):
		with self.assertRaises(QuoterError):
			price_summary(self._summary(self.a_annual_com), cost=10, qty=1, margin_pct=100)

	# --- frontera de costo: delega en resolve_external_cost (resolver inyectado) ---
	_PATCH = "acti_customs.acti_customizations.microsoft.quoter._get_resolver"

	def test_resolve_cost_usd_a_usd(self):
		with patch(self._PATCH, return_value=_fake_resolver(504.0, "buying_item_price", "USD")):
			self.assertEqual(resolve_cost(self.a_monthly_com, "2026-09-26", "USD", "ACME"), 504.0)

	def test_resolve_cost_usd_a_mxn(self):
		# el resolver YA devuelve amount en la moneda objetivo (MXN); acti_customs solo lo consume
		with patch(self._PATCH, return_value=_fake_resolver(8568.0, "buying_item_price", "MXN")):
			self.assertEqual(resolve_cost(self.a_monthly_com, "2026-09-26", "MXN", "ACME"), 8568.0)

	def test_resolve_cost_sin_tipo_cambio_failclosed(self):
		with patch(self._PATCH, return_value=_fake_resolver(None, "sin_tipo_cambio")):
			with self.assertRaises(QuoterError):
				resolve_cost(self.a_monthly_com, "2026-09-26", "MXN", "ACME")

	def test_resolve_cost_ambiguo_failclosed(self):
		with patch(self._PATCH, return_value=_fake_resolver(None, "ambiguo_price_list")):
			with self.assertRaises(QuoterError):
				resolve_cost(self.a_monthly_com, "2026-09-26", "MXN", "ACME")

	def test_resolve_cost_buying_item_price_cero_valido(self):
		# Item Price real con rate 0 (p. ej. Trial) → el resolver lo devuelve como buying_item_price 0.
		with patch(self._PATCH, return_value=_fake_resolver(0.0, "buying_item_price")):
			self.assertEqual(resolve_cost(self.trial, "2026-09-26", "USD", "ACME"), 0.0)

	def test_resolve_cost_sin_costo_failclosed(self):
		# sin_costo = Item comprable SIN fuente de costo → error SIEMPRE (sin excepción Trial).
		with patch(self._PATCH, return_value=_fake_resolver(0.0, "sin_costo")):
			with self.assertRaises(QuoterError):
				resolve_cost(self.a_annual_com, "2026-09-26", "USD", "ACME")

	def test_resolve_cost_sin_costo_failclosed_incluso_trial(self):
		# Aun un Item Trial: si el resolver dice sin_costo (no hay Item Price), fail-closed (no workaround).
		with patch(self._PATCH, return_value=_fake_resolver(0.0, "sin_costo")):
			with self.assertRaises(QuoterError):
				resolve_cost(self.trial, "2026-09-26", "USD", "ACME")

	def test_resolve_cost_no_purchase_cero(self):
		# no_purchase: el Item explícitamente no es comprable → 0 legítimo.
		with patch(self._PATCH, return_value=_fake_resolver(0.0, "no_purchase")):
			self.assertEqual(resolve_cost(self.a_annual_com, "2026-09-26", "USD", "ACME"), 0.0)

	# --- cantidad entera (licencias Microsoft, sin fracciones) ---
	def test_require_whole_qty_acepta_enteros(self):
		for n in (1, 2, 10):
			self.assertEqual(require_whole_qty(n), n)
			self.assertEqual(require_whole_qty(float(n)), n)  # 2.0 == entero
		self.assertIsInstance(require_whole_qty(3), int)

	def test_require_whole_qty_rechaza_fraccion_y_cero(self):
		for bad in (1.5, 0.1, 2.99, 3.5):
			with self.assertRaises(QuoterError):
				require_whole_qty(bad)
		for bad in (0, -1):
			with self.assertRaises(QuoterError):
				require_whole_qty(bad)

	def test_qty_3_5_nunca_se_convierte_en_3(self):
		# 3.5 debe LANZAR, no devolver 3: prohibida la coerción/truncado silencioso (el bug del Int).
		try:
			result = require_whole_qty(3.5)
		except QuoterError:
			result = "raised"
		self.assertEqual(result, "raised")
		self.assertNotEqual(result, 3)

	def test_add_to_quotation_end_to_end(self):
		q = self._quotation()
		if q is None:
			self.skipTest("Site sin infraestructura de venta.")
		with patch(self._PATCH, return_value=_fake_resolver(504.0, "buying_item_price", q.currency)):
			res = add_license_to_quotation(q.name, self.a_monthly_com, qty=2, margin_pct=20)
		q.reload()
		self.assertEqual(len(q.items), 1)
		self.assertEqual(q.items[0].rate, 630.0)  # ROUNDUP(504/(1-0.20),2)
		self.assertEqual(res["amount"], 1260.0)

	def test_add_to_quotation_rechaza_fraccion(self):
		# 'Agregar a cotización' con 3.5 licencias → QuoterError (guard antes de resolver costo).
		# No se agrega NINGUNA línea: ni 3.5 ni un 3 truncado.
		q = self._quotation()
		if q is None:
			self.skipTest("Site sin infraestructura de venta.")
		with self.assertRaises(QuoterError):
			add_license_to_quotation(q.name, self.a_monthly_com, qty=3.5, margin_pct=20)
		q.reload()
		self.assertEqual(len(q.items), 0)
		self.assertNotIn(3.0, [flt(i.qty) for i in q.items])  # jamás se coerciona a 3

	def test_add_to_quotation_acepta_enteros_e2e(self):
		# 'Agregar a cotización' sigue funcionando con 1, 2 y 10 (enteros). Items distintos por fila
		# (ERPNext rechaza el mismo item repetido salvo Selling Setting específico).
		q = self._quotation()
		if q is None:
			self.skipTest("Site sin infraestructura de venta.")
		casos = [(self.a_monthly_com, 1), (self.a_annual_com, 2), (self.a_annual_edu, 10)]
		with patch(self._PATCH, return_value=_fake_resolver(100.0, "buying_item_price", q.currency)):
			for item, n in casos:
				res = add_license_to_quotation(q.name, item, qty=n, margin_pct=20)
				self.assertEqual(res["qty"], n)
		q.reload()
		self.assertEqual(len(q.items), 3)
		self.assertEqual({flt(i.qty) for i in q.items}, {1.0, 2.0, 10.0})

	# --- get_price_preview: contexto persistido (v0.3.0) vs contexto explícito (Quotation nueva) ---
	def test_get_price_preview_persistida_sigue_funcionando(self):
		# v0.3.0: con Quotation persistida el contexto se deriva de la BD.
		q = self._quotation()
		if q is None:
			self.skipTest("Site sin infraestructura de venta.")
		with patch(self._PATCH, return_value=_fake_resolver(504.0, "buying_item_price", q.currency)):
			s = get_price_preview(self.a_monthly_com, qty=2, margin_pct=20, quotation=q.name)
		self.assertEqual(s["cost_unit"], 504.0)
		self.assertEqual(s["price_unit"], 630.0)  # ROUNDUP(504/0.8,2)

	def test_get_price_preview_contexto_explicito_sin_quotation(self):
		# Quotation nueva (no existe en BD): el preview usa company/currency/transaction_date del formulario.
		with patch(self._PATCH, return_value=_fake_resolver(504.0, "buying_item_price", "MXN")):
			s = get_price_preview(self.a_monthly_com, qty=2, margin_pct=20, **_NEW_CTX)
		self.assertEqual(s["cost_unit"], 504.0)
		self.assertEqual(s["price_unit"], 630.0)

	def test_get_price_preview_failclosed_sin_company(self):
		with self.assertRaises(QuoterError):
			get_price_preview(
				self.a_monthly_com, qty=2, margin_pct=20, currency="MXN", transaction_date="2026-09-28"
			)

	def test_get_price_preview_failclosed_sin_currency(self):
		with self.assertRaises(QuoterError):
			get_price_preview(
				self.a_monthly_com, qty=2, margin_pct=20, company="ACME", transaction_date="2026-09-28"
			)

	def test_get_price_preview_failclosed_sin_fecha(self):
		with self.assertRaises(QuoterError):
			get_price_preview(self.a_monthly_com, qty=2, margin_pct=20, company="ACME", currency="MXN")

	def test_get_price_preview_rate0_legitimo(self):
		# buying_item_price rate 0 (p. ej. Trial) sigue siendo costo 0 legítimo, no error.
		with patch(self._PATCH, return_value=_fake_resolver(0.0, "buying_item_price", "MXN")):
			s = get_price_preview(self.trial, qty=5, margin_pct=20, **_NEW_CTX)
		self.assertEqual(s["cost_unit"], 0.0)
		self.assertEqual(s["price_unit"], 0.0)

	def test_get_price_preview_fx_via_resolver(self):
		# El costo (y su conversión FX) sigue viniendo del resolver existente: amount del resolver → cost_unit.
		with patch(self._PATCH, return_value=_fake_resolver(8568.0, "buying_item_price", "MXN")):
			s = get_price_preview(self.a_monthly_com, qty=1, margin_pct=0, **_NEW_CTX)
		self.assertEqual(s["cost_unit"], 8568.0)

	def test_get_price_preview_sin_costo_failclosed(self):
		# sin_costo sigue siendo fail-closed también en el flujo de Quotation nueva.
		with patch(self._PATCH, return_value=_fake_resolver(0.0, "sin_costo", "MXN")):
			with self.assertRaises(QuoterError):
				get_price_preview(self.a_monthly_com, qty=2, margin_pct=20, **_NEW_CTX)

	# --- required_items: item/qty/uom ---
	def test_build_required_row_solo_item_qty_uom(self):
		row = build_required_row(self.a_annual_com, 3)
		self.assertEqual(set(row.keys()), {"item", "qty", "uom"})
		self.assertEqual(row["item"], self.a_annual_com)
		self.assertEqual(row["qty"], 3.0)

	def test_add_as_cost_fail_closed_sin_required_items(self):
		q = self._quotation()
		if q is None:
			self.skipTest("Site sin infraestructura de venta.")
		if q.meta.has_field("required_items"):
			self.skipTest("Site con erpnext_proposals: se valida en vivo.")
		with self.assertRaises(QuoterError):
			add_license_as_cost(q.name, self.a_annual_com, qty=2)

	def _quotation(self):
		company = frappe.db.get_value("Company", {}, "name")
		customer = frappe.db.get_value("Customer", {})
		price_list = frappe.db.get_value("Price List", {"selling": 1}, "name")
		if not (company and customer and price_list):
			return None
		cur = frappe.db.get_value("Company", company, "default_currency")
		q = frappe.get_doc(
			{
				"doctype": "Quotation",
				"quotation_to": "Customer",
				"party_name": customer,
				"company": company,
				"currency": cur,
				"conversion_rate": 1.0,
				"selling_price_list": price_list,
				"price_list_currency": cur,
				"plc_conversion_rate": 1.0,
				"ignore_pricing_rule": 1,
				"disable_rounded_total": 1,
				"order_type": "Sales",
			}
		)
		for f in (
			"total",
			"base_total",
			"grand_total",
			"base_grand_total",
			"rounded_total",
			"base_rounded_total",
		):
			q.set(f, 0)
		q.flags.ignore_mandatory = True
		q.insert(ignore_permissions=True)
		self._quotations.append(q.name)
		return q
