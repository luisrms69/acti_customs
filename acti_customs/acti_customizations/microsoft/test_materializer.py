# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Tests del materializador Item (ADR-0003). Module test (no genera test-records de Item)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from acti_customs.acti_customizations.microsoft.materializer import (
	ITEM_GROUP,
	STOCK_UOM,
	item_code_for,
	upsert_item,
)

ROW = {
	"product_id": "CFQ7X1",
	"sku_id": "S1",
	"term_duration": "P1Y",
	"billing_plan": "Annual",
	"segment": "Commercial",
	"product_title": "Office 365 E3",
	"sku_title": "Office 365 E3 Sku",
	"sku_description": "Descripcion larga del SKU.",
	"tags": "License",
	"unit_price": 120,
}
CODE = "MS-CFQ7X1-S1-P1Y-Annual-Commercial"


def _prereqs():
	if not frappe.db.exists("UOM", STOCK_UOM):
		frappe.get_doc({"doctype": "UOM", "uom_name": STOCK_UOM}).insert(ignore_permissions=True)
	if not frappe.db.exists("Item Group", ITEM_GROUP):
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


class TestMaterializer(FrappeTestCase):
	def setUp(self):
		self._cleanup()
		_prereqs()

	def tearDown(self):
		self._cleanup()

	def _cleanup(self):
		for name in frappe.get_all("Item", filters={"item_group": ITEM_GROUP}, pluck="name"):
			frappe.delete_doc("Item", name, force=True, ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- limpieza de test

	def test_item_code_determinista(self):
		self.assertEqual(item_code_for(ROW), CODE)

	def test_crea_item_con_campos_correctos(self):
		self.assertEqual(upsert_item(ROW), CODE)
		it = frappe.get_doc("Item", CODE)
		self.assertEqual(it.item_group, ITEM_GROUP)
		self.assertEqual(it.stock_uom, STOCK_UOM)
		self.assertEqual(it.is_stock_item, 0)
		self.assertEqual(it.is_sales_item, 1)
		self.assertEqual(it.is_purchase_item, 1)
		self.assertEqual(it.ms_product_id, "CFQ7X1")
		self.assertEqual(it.ms_sku_id, "S1")
		self.assertEqual(it.ms_term_duration, "P1Y")
		self.assertEqual(it.ms_billing_plan, "Annual")
		self.assertEqual(it.ms_segment, "Commercial")
		self.assertEqual(it.ms_product_title, "Office 365 E3")
		self.assertEqual(it.ms_sku_title, "Office 365 E3 Sku")
		self.assertEqual(it.item_name, "Office 365 E3 Sku | 1 año | anual | Commercial")
		self.assertEqual(it.description, "Descripcion larga del SKU.")

	def test_idempotente(self):
		upsert_item(ROW)
		upsert_item(ROW)
		self.assertEqual(frappe.db.count("Item", {"item_code": CODE}), 1)

	def test_reactivacion(self):
		upsert_item(ROW)
		frappe.db.set_value("Item", CODE, "disabled", 1)
		upsert_item(ROW)
		self.assertEqual(frappe.db.get_value("Item", CODE, "disabled"), 0)

	def test_actualiza_metadata_mutable(self):
		upsert_item(ROW)
		upsert_item(dict(ROW, sku_title="Office 365 E3 Sku v2"))
		self.assertEqual(
			frappe.db.get_value("Item", CODE, "item_name"),
			"Office 365 E3 Sku v2 | 1 año | anual | Commercial",
		)
		# item_code (identidad) NO cambia
		self.assertEqual(frappe.db.count("Item", {"item_group": ITEM_GROUP}), 1)
