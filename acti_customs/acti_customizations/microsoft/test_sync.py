# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Tests del sincronizador de catalogo Microsoft.

Module test (fuera de doctype/) para no disparar generacion de test-records de Item.
Genera archivos .xlsx temporales; no depende del Excel real del cliente.
"""

import os
import tempfile

import frappe
import openpyxl
from frappe.tests.utils import FrappeTestCase

from acti_customs.acti_customizations.microsoft.catalog import SHEET, CatalogError
from acti_customs.acti_customizations.microsoft.materializer import ITEM_GROUP, STOCK_UOM
from acti_customs.acti_customizations.microsoft.sync import sync_microsoft_catalog

COLUMNS = [
	"ProductTitle",
	"ProductId",
	"SkuId",
	"SkuTitle",
	"TermDuration",
	"BillingPlan",
	"Segment",
	"Market",
	"Currency",
	"UnitPrice",
	"EffectiveStartDate",
	"EffectiveEndDate",
	"Tags",
	"ChangeIndicator",
]

ROW_A = {
	"ProductTitle": "Prod A",
	"ProductId": "CFQ7X1",
	"SkuId": "S1",
	"SkuTitle": "Sku A",
	"TermDuration": "P1Y",
	"BillingPlan": "Annual",
	"Segment": "Commercial",
	"Market": "MX",
	"Currency": "USD",
	"UnitPrice": 10.0,
	"EffectiveStartDate": "2026-01-01",
	"EffectiveEndDate": "9999-11-30",
	"Tags": "",
	"ChangeIndicator": "New",
}
ROW_B = {
	"ProductTitle": "Prod B",
	"ProductId": "CFQ7X2",
	"SkuId": "S2",
	"SkuTitle": "Sku B",
	"TermDuration": "P1M",
	"BillingPlan": "Monthly",
	"Segment": "Education",
	"Market": "MX",
	"Currency": "USD",
	"UnitPrice": 20.0,
	"EffectiveStartDate": "2026-01-01",
	"EffectiveEndDate": "9999-11-30",
	"Tags": "",
	"ChangeIndicator": "New",
}
KEY_A = "CFQ7X1|S1|P1Y|Annual|Commercial"
CODE_A = "MS-CFQ7X1-S1-P1Y-Annual-Commercial"


def _ensure_prereqs():
	if not frappe.db.exists("UOM", STOCK_UOM):
		frappe.get_doc({"doctype": "UOM", "uom_name": STOCK_UOM}).insert(ignore_permissions=True)
	if not frappe.db.exists("Item Group", ITEM_GROUP):
		frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": ITEM_GROUP,
				"parent_item_group": "All Item Groups",
				"is_group": 0,
			}
		).insert(ignore_permissions=True)


class TestSync(FrappeTestCase):
	def setUp(self):
		self._cleanup()
		_ensure_prereqs()
		self._tmp = []

	def tearDown(self):
		for p in getattr(self, "_tmp", []):
			if os.path.exists(p):
				os.remove(p)
		self._cleanup()

	def _cleanup(self):
		# El sync hace commit() (necesario para la carga real de 3,932), por lo que rollback
		# no basta para aislar los tests: limpiamos explicitamente Offers/Items materializados.
		for name in frappe.get_all("Item", filters={"ms_offer_key": ["is", "set"]}, pluck="name"):
			frappe.delete_doc("Item", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Microsoft Offer", pluck="name"):
			frappe.delete_doc("Microsoft Offer", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Item", "MS-CFQ7X1-1"):
			frappe.delete_doc("Item", "MS-CFQ7X1-1", force=True, ignore_permissions=True)
		frappe.db.commit()

	def _xlsx(self, rows, columns=COLUMNS, sheet=SHEET):
		fd, path = tempfile.mkstemp(suffix=".xlsx")
		os.close(fd)
		self._tmp.append(path)
		wb = openpyxl.Workbook()
		ws = wb.active
		ws.title = sheet
		ws.append(columns)
		for r in rows:
			ws.append([r.get(c, "") for c in columns])
		wb.save(path)
		return path

	# --- estructura ---
	def test_missing_columns_fail_closed(self):
		path = self._xlsx([ROW_A], columns=[c for c in COLUMNS if c != "ProductId"])
		with self.assertRaises(CatalogError):
			sync_microsoft_catalog(path, dry_run=True)

	def test_wrong_sheet_fail_closed(self):
		path = self._xlsx([ROW_A], sheet="OtraHoja")
		with self.assertRaises(CatalogError):
			sync_microsoft_catalog(path, dry_run=True)

	# --- dry run no escribe ---
	def test_dry_run_no_write(self):
		path = self._xlsx([ROW_A, ROW_B])
		rep = sync_microsoft_catalog(path, dry_run=True)
		self.assertEqual(rep["rows_read"], 2)
		self.assertEqual(rep["rows_valid"], 2)
		self.assertEqual(rep["offers_new"], 2)
		self.assertEqual(rep["items_to_create"], 2)
		self.assertNotIn("applied", rep)
		self.assertEqual(frappe.db.count("Microsoft Offer"), 0)
		self.assertEqual(frappe.db.count("Item", {"ms_offer_key": ["is", "set"]}), 0)

	# --- creacion inicial ---
	def test_initial_apply_creates(self):
		path = self._xlsx([ROW_A, ROW_B])
		rep = sync_microsoft_catalog(path, dry_run=False)
		self.assertEqual(rep["applied"]["offers_created"], 2)
		self.assertEqual(rep["applied"]["items_created"], 2)
		self.assertEqual(frappe.db.count("Microsoft Offer"), 2)
		self.assertEqual(frappe.db.count("Item", {"ms_offer_key": ["is", "set"]}), 2)
		self.assertEqual(frappe.db.get_value("Microsoft Offer", KEY_A, "item"), CODE_A)

	# --- idempotencia ---
	def test_idempotent_second_apply(self):
		path = self._xlsx([ROW_A, ROW_B])
		sync_microsoft_catalog(path, dry_run=False)
		rep2 = sync_microsoft_catalog(path, dry_run=False)
		self.assertEqual(rep2["offers_new"], 0)
		self.assertEqual(rep2["items_to_create"], 0)
		self.assertEqual(rep2["offers_to_update"], 0)
		self.assertEqual(rep2["applied"]["offers_created"], 0)
		self.assertEqual(rep2["applied"]["items_created"], 0)
		self.assertEqual(frappe.db.count("Item", {"ms_offer_key": ["is", "set"]}), 2)

	# --- actualizacion de precio: sin nuevo Item ---
	def test_price_update_no_new_item(self):
		path = self._xlsx([ROW_A])
		sync_microsoft_catalog(path, dry_run=False)
		path2 = self._xlsx([dict(ROW_A, UnitPrice=99.5)])
		rep = sync_microsoft_catalog(path2, dry_run=False)
		self.assertEqual(rep["offers_to_update"], 1)
		self.assertEqual(rep["applied"]["offers_updated"], 1)
		self.assertEqual(rep["applied"]["items_created"], 0)
		self.assertEqual(frappe.db.get_value("Microsoft Offer", KEY_A, "unit_price"), 99.5)
		self.assertEqual(frappe.db.count("Item", {"ms_offer_key": ["is", "set"]}), 1)

	# --- actualizacion de titulo (metadata no identitaria): sin nuevo Item ---
	def test_title_update_no_new_item(self):
		path = self._xlsx([ROW_A])
		sync_microsoft_catalog(path, dry_run=False)
		path2 = self._xlsx([dict(ROW_A, ProductTitle="Prod A v2", SkuTitle="Sku A v2")])
		rep = sync_microsoft_catalog(path2, dry_run=False)
		self.assertEqual(rep["applied"]["offers_updated"], 1)
		self.assertEqual(rep["applied"]["items_created"], 0)
		self.assertEqual(frappe.db.get_value("Microsoft Offer", KEY_A, "product_title"), "Prod A v2")
		self.assertEqual(frappe.db.count("Item", {"ms_offer_key": ["is", "set"]}), 1)

	# --- nueva oferta -> nuevo item ---
	def test_new_offer_creates_item(self):
		sync_microsoft_catalog(self._xlsx([ROW_A]), dry_run=False)
		rep = sync_microsoft_catalog(self._xlsx([ROW_A, ROW_B]), dry_run=False)
		self.assertEqual(rep["offers_new"], 1)
		self.assertEqual(rep["applied"]["offers_created"], 1)
		self.assertEqual(rep["applied"]["items_created"], 1)
		self.assertEqual(frappe.db.count("Item", {"ms_offer_key": ["is", "set"]}), 2)

	# --- oferta desaparecida -> inactivar, conservar item ---
	def test_disappeared_offer_inactivated(self):
		sync_microsoft_catalog(self._xlsx([ROW_A, ROW_B]), dry_run=False)
		rep = sync_microsoft_catalog(self._xlsx([ROW_A]), dry_run=False)  # falta B
		self.assertEqual(rep["offers_to_inactivate"], 1)
		self.assertEqual(rep["applied"]["offers_inactivated"], 1)
		self.assertEqual(
			frappe.db.get_value("Microsoft Offer", "CFQ7X2|S2|P1M|Monthly|Education", "is_active"), 0
		)
		# Item de B se conserva.
		self.assertTrue(frappe.db.exists("Item", "MS-CFQ7X2-S2-P1M-Monthly-Education"))

	# --- legacy no se reutiliza ---
	def test_legacy_item_not_reused(self):
		legacy = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "MS-CFQ7X1-1",
				"item_name": "Legacy coarse",
				"item_group": ITEM_GROUP,
				"stock_uom": STOCK_UOM,
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
		sync_microsoft_catalog(self._xlsx([ROW_A]), dry_run=False)
		self.assertTrue(frappe.db.exists("Item", CODE_A))
		self.assertNotEqual(CODE_A, legacy.name)
		self.assertFalse(frappe.db.get_value("Item", legacy.name, "ms_offer_key"))
