# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Tests del selector/cotizador sobre Item (ADR-0003). Module test."""

import frappe
from frappe.tests.utils import FrappeTestCase

from acti_customs.acti_customizations.microsoft.materializer import ITEM_GROUP, upsert_item
from acti_customs.acti_customizations.microsoft.quoter import (
	QuoterError,
	add_license_as_cost,
	add_license_to_quotation,
	build_required_row,
	next_step,
	price_summary,
	resolve_path,
	roundup2,
)
from acti_customs.acti_customizations.microsoft.test_materializer import _prereqs


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

	# --- frontera de costo: delega en erpnext_proposals; fail-closed si no está ---
	def test_add_to_quotation_pendiente_resolver(self):
		if _proposals_installed():
			self.skipTest("erpnext_proposals presente: la resolucion de costo se valida en ese entorno.")
		q = self._quotation()
		if q is None:
			self.skipTest("Site sin infraestructura de venta.")
		with self.assertRaises(QuoterError):
			add_license_to_quotation(q.name, self.a_monthly_com, qty=1, margin_pct=20)

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


def _proposals_installed():
	try:
		import erpnext_proposals

		return True
	except ImportError:
		return False
