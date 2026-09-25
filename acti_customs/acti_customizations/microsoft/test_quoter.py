# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Tests del selector/cotizador Microsoft (Bloque 2). Module test (sin generacion de
test-records de Item). Crea un catalogo pequeño de prueba; rollback por test."""

import frappe
from frappe.tests.utils import FrappeTestCase

from acti_customs.acti_customizations.microsoft.materializer import ITEM_GROUP, STOCK_UOM, materialize_item
from acti_customs.acti_customizations.microsoft.quoter import (
	QuoterError,
	add_license_as_cost,
	add_license_to_quotation,
	build_required_row,
	compute_cost,
	next_step,
	price_summary,
	resolve_path,
	roundup2,
)


def _prereqs():
	if not frappe.db.exists("UOM", STOCK_UOM):
		frappe.get_doc({"doctype": "UOM", "uom_name": STOCK_UOM}).insert(ignore_permissions=True)
	if not frappe.db.exists("Item Group", ITEM_GROUP):
		# El site de CI (erpnext sin setup wizard) puede no tener la raíz "All Item Groups".
		parent = frappe.db.get_value("Item Group", {"is_group": 1}, "name")
		if not parent:
			root = frappe.get_doc(
				{"doctype": "Item Group", "item_group_name": "All Item Groups", "is_group": 1}
			)
			root.insert(ignore_permissions=True)
			parent = root.name
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": ITEM_GROUP,
				"parent_item_group": parent,
				"is_group": 0,
			}
		).insert(ignore_permissions=True)


def _offer(materialize=True, **kw):
	data = dict(
		{
			"doctype": "Microsoft Offer",
			"market": "MX",
			"currency": "USD",
			"effective_start_date": "2025-01-01",
			"effective_end_date": "9999-11-30",
			"is_active": 1,
		},
		**kw,
	)
	off = frappe.get_doc(data).insert(ignore_permissions=True)
	if materialize:
		materialize_item(off.name)
	return off.name


class TestQuoter(FrappeTestCase):
	def setUp(self):
		self._quotations = []
		self._cleanup()
		_prereqs()
		# Catalogo de prueba.
		self.o_annual_com = _offer(
			product_title="Prod A",
			product_id="PA",
			sku_title="Sku A",
			sku_id="1",
			term_duration="P1Y",
			billing_plan="Annual",
			segment="Commercial",
			unit_price=120,
		)
		self.o_monthly_com = _offer(
			product_title="Prod A",
			product_id="PA",
			sku_title="Sku A",
			sku_id="1",
			term_duration="P1Y",
			billing_plan="Monthly",
			segment="Commercial",
			unit_price=120,
		)
		self.o_annual_edu = _offer(
			product_title="Prod A",
			product_id="PA",
			sku_title="Sku A",
			sku_id="1",
			term_duration="P1Y",
			billing_plan="Annual",
			segment="Education",
			unit_price=200,
		)
		self.o_trial = _offer(
			product_title="Prod B",
			product_id="PB",
			sku_title="Sku B",
			sku_id="2",
			term_duration="P1M",
			billing_plan="None",
			segment="Commercial",
			unit_price=0,
			tags="License;Trial",
		)
		# Inactiva y expirada (no deben aparecer).
		_offer(
			product_title="Prod Inact",
			product_id="PI",
			sku_title="Sku I",
			sku_id="9",
			term_duration="P1Y",
			billing_plan="Annual",
			segment="Commercial",
			unit_price=50,
			is_active=0,
		)
		_offer(
			product_title="Prod Exp",
			product_id="PE",
			sku_title="Sku E",
			sku_id="8",
			term_duration="P1Y",
			billing_plan="Annual",
			segment="Commercial",
			unit_price=50,
			effective_start_date="2023-01-01",
			effective_end_date="2024-01-01",
		)

	def tearDown(self):
		self._cleanup()

	def _cleanup(self):
		# add_license hace save() (que puede commitear), por lo que rollback no basta:
		# limpieza explicita de quotations de prueba, ofertas e items materializados.
		for qn in getattr(self, "_quotations", []):
			if frappe.db.exists("Quotation", qn):
				frappe.delete_doc("Quotation", qn, force=True, ignore_permissions=True)
		for name in frappe.get_all("Item", filters={"ms_offer_key": ["is", "set"]}, pluck="name"):
			frappe.delete_doc("Item", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Microsoft Offer", pluck="name"):
			frappe.delete_doc("Microsoft Offer", name, force=True, ignore_permissions=True)
		frappe.db.commit()

	# --- resolucion progresiva ---
	def test_first_step_prompts_product(self):
		r = next_step({})
		self.assertEqual(r["field"], "product_title")
		vals = {o["value"] for o in r["options"]}
		self.assertIn("Prod A", vals)
		self.assertIn("Prod B", vals)

	def test_inactive_expired_excluded(self):
		vals = {o["value"] for o in next_step({})["options"]}
		self.assertNotIn("Prod Inact", vals)
		self.assertNotIn("Prod Exp", vals)

	def test_autoselect_chain_resolves(self):
		r = next_step({"product_title": "Prod B"})
		self.assertIn("resolved", r)
		self.assertEqual(r["resolved"]["offer_key"], self.o_trial)
		# se autoseleccionaron todas las dimensiones
		for k in ("product_id", "sku_title", "sku_id", "term_duration", "billing_plan", "segment"):
			self.assertTrue(r["selected"][k])

	def test_chained_filter_prompts_billing(self):
		r = next_step({"product_title": "Prod A"})
		self.assertEqual(r["field"], "billing_plan")
		self.assertEqual({o["value"] for o in r["options"]}, {"Annual", "Monthly"})

	def test_resolve_after_billing(self):
		r = next_step({"product_title": "Prod A", "billing_plan": "Monthly"})
		self.assertIn("resolved", r)
		self.assertEqual(r["resolved"]["offer_key"], self.o_monthly_com)

	def test_prompt_segment_when_two(self):
		r = next_step({"product_title": "Prod A", "billing_plan": "Annual"})
		self.assertEqual(r["field"], "segment")
		self.assertEqual({o["value"] for o in r["options"]}, {"Commercial", "Education"})

	def test_invalid_combo_error(self):
		r = next_step({"product_title": "Prod A", "segment": "Charity"})
		self.assertIn("error", r)

	def test_selector_never_creates_item(self):
		before = frappe.db.count("Item")
		next_step({"product_title": "Prod A"})
		next_step({"product_title": "Prod B"})
		self.assertEqual(frappe.db.count("Item"), before)

	# --- pricing ---
	def _od(self, **kw):
		return dict({"item": "X", "sku_title": "S", "segment": "Commercial", "tags": None}, **kw)

	def test_pricing_p1y_monthly(self):
		s = price_summary(
			self._od(term_duration="P1Y", billing_plan="Monthly", unit_price=120), qty=3, margin_pct=20
		)
		self.assertEqual(s["cost_unit"], 10.0)
		self.assertEqual(s["price_unit"], 12.5)
		self.assertEqual(s["amount"], 37.5)

	def test_pricing_other_combo(self):
		s = price_summary(
			self._od(term_duration="P1Y", billing_plan="Annual", unit_price=120), qty=1, margin_pct=20
		)
		self.assertEqual(s["cost_unit"], 120.0)
		self.assertEqual(s["price_unit"], 150.0)

	def test_pricing_trial_zero(self):
		s = price_summary(
			self._od(term_duration="P1M", billing_plan="None", unit_price=0, tags="License;Trial"),
			qty=5,
			margin_pct=30,
		)
		self.assertEqual(s["cost_unit"], 0.0)
		self.assertEqual(s["price_unit"], 0.0)
		self.assertEqual(s["amount"], 0.0)

	def test_pricing_roundup(self):
		self.assertEqual(roundup2(11.7647), 11.77)
		s = price_summary(
			self._od(term_duration="P1Y", billing_plan="Annual", unit_price=10), qty=1, margin_pct=15
		)
		self.assertEqual(s["price_unit"], 11.77)

	def test_pricing_invalid_margin_and_qty(self):
		with self.assertRaises(QuoterError):
			price_summary(
				self._od(term_duration="P1Y", billing_plan="Annual", unit_price=10), qty=1, margin_pct=100
			)
		with self.assertRaises(QuoterError):
			price_summary(
				self._od(term_duration="P1Y", billing_plan="Annual", unit_price=10), qty=0, margin_pct=20
			)

	# --- alta en Quotation ---
	def _quotation(self):
		# Usa Company/Customer/Price List reales del site (no valores inventados). En un site sin
		# setup wizard (p. ej. el site aislado de CI con ERPNext recién instalado) no existe
		# infraestructura de venta; en ese caso las pruebas de Quotation se omiten (se validan en un
		# site con ERPNext configurado / en vivo), en vez de fabricar una Company (cascada pesada).
		company = frappe.db.get_value("Company", {"name": "_Test Company"}) or frappe.db.get_value(
			"Company", {}
		)
		customer = frappe.db.get_value("Customer", {})
		price_list = frappe.db.get_value("Price List", {"selling": 1}, "name")
		if not (company and customer and price_list):
			self.skipTest(
				"Site sin infraestructura de venta (Company/Customer/Price List) — se valida en vivo."
			)
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
		# ERPNext `calculate_taxes_and_totals` hace early-return con items vacíos y deja los
		# totales en None; `set_total_in_words` (validate) haría abs(None) -> TypeError. El
		# cotizador agrega la primera línea DESPUÉS de crear el draft, así que inicializamos
		# los totales de un draft vacío a 0 (valor correcto para 0 líneas) para poder insertarlo.
		for f in (
			"total",
			"base_total",
			"grand_total",
			"base_grand_total",
			"rounded_total",
			"base_rounded_total",
		):
			q.set(f, 0)
		# La tabla `items` es mandatoria en Quotation; el draft de prueba se crea vacío a
		# propósito (add_license_to_quotation agrega la primera y única línea), por eso se
		# omite la validación de mandatorios solo al insertar el draft de prueba.
		q.flags.ignore_mandatory = True
		q.insert(ignore_permissions=True)
		self._quotations.append(q.name)
		return q

	def test_add_license_appends_quotation_item(self):
		q = self._quotation()
		items_before = frappe.db.count("Item")
		res = add_license_to_quotation(q.name, self.o_monthly_com, qty=2, margin_pct=20)
		q.reload()
		self.assertEqual(len(q.items), 1)
		item_code = frappe.db.get_value("Microsoft Offer", self.o_monthly_com, "item")
		self.assertEqual(q.items[0].item_code, item_code)
		self.assertEqual(q.items[0].qty, 2)
		self.assertEqual(q.items[0].rate, 12.5)
		self.assertEqual(res["price_unit"], 12.5)
		# el selector NO crea Items.
		self.assertEqual(frappe.db.count("Item"), items_before)

	def test_add_license_fail_closed_without_item(self):
		# oferta sin Item materializado -> fail-closed
		ok = _offer(
			materialize=False,
			product_title="Prod C",
			product_id="PC",
			sku_title="Sku C",
			sku_id="3",
			term_duration="P1Y",
			billing_plan="Annual",
			segment="Commercial",
			unit_price=10,
		)
		q = self._quotation()
		with self.assertRaises(QuoterError):
			add_license_to_quotation(q.name, ok, qty=1, margin_pct=20)

	# --- resolucion editable (resolve_path) ---
	def test_resolve_path_first_step(self):
		r = resolve_path({})
		fields = {s["field"] for s in r["steps"]}
		self.assertIn("product_title", fields)
		vals = {o["value"] for s in r["steps"] if s["field"] == "product_title" for o in s["options"]}
		self.assertEqual(vals, {"Prod A", "Prod B"})

	def test_resolve_path_prompts_billing_for_prod_a(self):
		r = resolve_path({"product_title": "Prod A"})
		self.assertNotIn("resolved", r)
		billing = next(s for s in r["steps"] if s["field"] == "billing_plan")
		self.assertTrue(billing["ambiguous"])
		self.assertEqual({o["value"] for o in billing["options"]}, {"Annual", "Monthly"})

	def test_resolve_path_resolves_after_billing(self):
		r = resolve_path({"product_title": "Prod A", "billing_plan": "Monthly"})
		self.assertIn("resolved", r)
		self.assertEqual(r["resolved"]["offer_key"], self.o_monthly_com)

	def test_resolve_path_change_earlier_drops_dependents(self):
		# Cambiar a Prod B con un billing_plan anterior invalido (Monthly) -> se descarta y resuelve trial.
		r = resolve_path({"product_title": "Prod B", "billing_plan": "Monthly"})
		self.assertIn("resolved", r)
		self.assertEqual(r["resolved"]["offer_key"], self.o_trial)
		self.assertEqual(r["selected"].get("billing_plan"), "None")

	def test_resolve_path_trial_labels(self):
		r = resolve_path({"product_title": "Prod B"})
		self.assertIn("resolved", r)
		self.assertTrue(r["resolved"]["is_trial"])
		self.assertEqual(r["resolved"]["compromiso"], "Prueba 1 mes")
		self.assertEqual(r["resolved"]["facturacion"], "")

	# --- presentacion trial en el resumen de precio ---
	def test_price_summary_trial_labels(self):
		s = price_summary(
			self._od(term_duration="P1M", billing_plan="None", unit_price=0, tags="License;Trial"),
			qty=1,
			margin_pct=20,
		)
		self.assertEqual(s["compromiso"], "Prueba 1 mes")
		self.assertEqual(s["facturacion"], "")
		self.assertTrue(s["is_trial"])

	# --- Agregar como costo: fila required_items solo item/qty/uom ---
	def test_build_required_row_only_item_qty_uom(self):
		off = frappe.get_doc("Microsoft Offer", self.o_monthly_com)
		row = build_required_row(off, 3)
		self.assertEqual(set(row.keys()), {"item", "qty", "uom"})
		self.assertEqual(row["item"], off.item)
		self.assertEqual(row["qty"], 3.0)
		self.assertEqual(row["uom"], frappe.db.get_value("Item", off.item, "stock_uom"))
		# NO escribe costo/precio/margen ni metadata economica.
		for forbidden in (
			"frozen_cost_rate",
			"frozen_cost_source",
			"economic_behavior",
			"rate",
			"cost",
			"margin_pct",
		):
			self.assertNotIn(forbidden, row)

	def test_add_as_cost_never_creates_item(self):
		before = frappe.db.count("Item")
		build_required_row(frappe.get_doc("Microsoft Offer", self.o_annual_com), 2)
		self.assertEqual(frappe.db.count("Item"), before)

	def test_add_as_cost_fail_closed_without_required_items_field(self):
		# En un site SIN erpnext_proposals, Quotation no tiene la tabla required_items -> fail-closed.
		q = self._quotation()
		if q.meta.has_field("required_items"):
			self.skipTest("Site con erpnext_proposals: la tabla required_items existe (se valida en vivo).")
		with self.assertRaises(QuoterError):
			add_license_as_cost(q.name, self.o_monthly_com, qty=2)

	# --- destinos MUTUAMENTE EXCLUYENTES (o items, o required_items; nunca ambos) ---
	def test_sale_adds_only_quotation_item(self):
		q = self._quotation()
		req_before = len(q.get("required_items") or [])
		add_license_to_quotation(q.name, self.o_annual_com, qty=1, margin_pct=20)
		q.reload()
		self.assertEqual(len(q.items), 1)  # exactamente una linea de venta
		self.assertEqual(len(q.get("required_items") or []), req_before)  # required_items intacta

	def test_cost_adds_only_required_item(self):
		q = self._quotation()
		if not q.meta.has_field("required_items"):
			self.skipTest("Site sin erpnext_proposals: la exclusion en 'costo' se valida en vivo.")
		items_before = len(q.items)
		req_before = len(q.get("required_items") or [])
		add_license_as_cost(q.name, self.o_annual_com, qty=3)
		q.reload()
		self.assertEqual(len(q.get("required_items") or []), req_before + 1)  # exactamente una fila de costo
		self.assertEqual(len(q.items), items_before)  # items sin cambios
