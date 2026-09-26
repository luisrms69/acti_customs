# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Tests del sincronizador nativo Excel -> Item + Item Price + Item Default (ADR-0003).

Module test. Genera .xlsx temporales con las columnas reales del catálogo NCE (incluida ERP Price,
para verificar que se IGNORA). Las pruebas de `apply` requieren una Company en el site (Item Default);
en un site pelón (CI sin setup wizard) se omiten y el pipeline se valida en un site configurado.
"""

import os
import tempfile

import frappe
import openpyxl
from frappe.tests.utils import FrappeTestCase

from acti_customs.acti_customizations.microsoft.catalog import SHEET
from acti_customs.acti_customizations.microsoft.materializer import ITEM_GROUP, STOCK_UOM
from acti_customs.acti_customizations.microsoft.pricing import PRICE_LIST
from acti_customs.acti_customizations.microsoft.sync import sync_microsoft_catalog
from acti_customs.acti_customizations.microsoft.test_materializer import _prereqs

COLUMNS = [
	"ChangeIndicator",
	"ProductTitle",
	"ProductId",
	"SkuId",
	"SkuTitle",
	"Publisher",
	"SkuDescription",
	"UnitOfMeasure",
	"TermDuration",
	"BillingPlan",
	"Market",
	"Currency",
	"UnitPrice",
	"EffectiveStartDate",
	"EffectiveEndDate",
	"Tags",
	"ERP Price",
	"Segment",
]
ROW_A = {
	"ProductTitle": "Office 365 E3",
	"ProductId": "PA",
	"SkuId": "1",
	"SkuTitle": "Sku A",
	"TermDuration": "P1Y",
	"BillingPlan": "Monthly",
	"Market": "MX",
	"Currency": "USD",
	"UnitPrice": 120,
	"EffectiveStartDate": "2026-01-01",
	"EffectiveEndDate": "9999-11-30",
	"Tags": "License",
	"ERP Price": 999.99,
	"Segment": "Commercial",
}
ROW_B = {
	"ProductTitle": "Office 365 E5",
	"ProductId": "PB",
	"SkuId": "2",
	"SkuTitle": "Sku B",
	"TermDuration": "P1Y",
	"BillingPlan": "Annual",
	"Market": "MX",
	"Currency": "USD",
	"UnitPrice": 200,
	"EffectiveStartDate": "2026-01-01",
	"EffectiveEndDate": "9999-11-30",
	"Tags": "License",
	"ERP Price": 888.88,
	"Segment": "Education",
}
CODE_A = "MS-PA-1-P1Y-Monthly-Commercial"
CODE_B = "MS-PB-2-P1Y-Annual-Education"


class TestSync(FrappeTestCase):
	def setUp(self):
		self._tmp = []
		self._cleanup()
		_prereqs()
		self._has_company = bool(frappe.db.get_value("Company", {}, "name"))

	def tearDown(self):
		for p in self._tmp:
			if os.path.exists(p):
				os.remove(p)
		self._cleanup()

	def _cleanup(self):
		for name in frappe.get_all("Item Price", filters={"price_list": PRICE_LIST}, pluck="name"):
			frappe.delete_doc("Item Price", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Item", filters={"item_group": ITEM_GROUP}, pluck="name"):
			frappe.delete_doc("Item", name, force=True, ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- limpieza de test

	def _xlsx(self, rows):
		fd, path = tempfile.mkstemp(suffix=".xlsx")
		os.close(fd)
		self._tmp.append(path)
		wb = openpyxl.Workbook()
		ws = wb.active
		ws.title = SHEET
		ws.append(COLUMNS)
		for r in rows:
			ws.append([r.get(c, "") for c in COLUMNS])
		wb.save(path)
		return path

	def _apply(self, rows):
		return sync_microsoft_catalog(self._xlsx(rows), dry_run=False)

	def _price(self, code):
		rows = frappe.get_all(
			"Item Price",
			filters={"item_code": code, "price_list": PRICE_LIST},
			fields=["price_list_rate", "valid_from", "valid_upto"],
			order_by="valid_from asc",
		)
		return rows

	# --- dry run (no requiere Company) ---
	def test_dry_run_no_escribe(self):
		rep = sync_microsoft_catalog(self._xlsx([ROW_A, ROW_B]), dry_run=True)
		self.assertEqual(rep["rows_valid"], 2)
		self.assertEqual(rep["items_new"], 2)
		self.assertNotIn("applied", rep)
		self.assertEqual(frappe.db.count("Item", {"item_group": ITEM_GROUP}), 0)

	# --- apply (requiere Company) ---
	def test_apply_crea_item_price_itemdefault(self):
		if not self._has_company:
			self.skipTest("Site sin Company; apply se valida en site configurado.")
		self._apply([ROW_A, ROW_B])
		self.assertTrue(frappe.db.exists("Item", CODE_A))
		self.assertTrue(frappe.db.exists("Item", CODE_B))
		# /12: P1Y+Monthly -> 120/12 = 10 ; P1Y+Annual -> 200
		self.assertEqual(self._price(CODE_A)[0].price_list_rate, 10.0)
		self.assertEqual(self._price(CODE_B)[0].price_list_rate, 200.0)
		# Item Default apunta a la Price List Microsoft
		company = frappe.db.get_value("Company", {}, "name")
		it = frappe.get_doc("Item", CODE_A)
		self.assertTrue(
			any(d.company == company and d.default_price_list == PRICE_LIST for d in it.item_defaults)
		)

	def test_erp_price_ignorado_y_unitprice_no_paralelo(self):
		if not self._has_company:
			self.skipTest("Site sin Company.")
		self._apply([ROW_A])
		# el costo persistido es el /12 (10), NO ERP Price (999.99) NI UnitPrice crudo (120)
		self.assertEqual(self._price(CODE_A)[0].price_list_rate, 10.0)
		it = frappe.get_doc("Item", CODE_A)
		# no hay campo económico paralelo en el Item (ms_currency/ms_offer_label eliminados)
		self.assertFalse(it.get("ms_currency"))
		self.assertNotIn(999.99, [self._price(CODE_A)[0].price_list_rate])

	def test_idempotente(self):
		if not self._has_company:
			self.skipTest("Site sin Company.")
		self._apply([ROW_A, ROW_B])
		self._apply([ROW_A, ROW_B])
		self.assertEqual(frappe.db.count("Item", {"item_group": ITEM_GROUP}), 2)
		self.assertEqual(frappe.db.count("Item Price", {"item_code": CODE_A, "price_list": PRICE_LIST}), 1)

	def test_desaparecida_disable_y_cierra_precio(self):
		if not self._has_company:
			self.skipTest("Site sin Company.")
		self._apply([ROW_A, ROW_B])
		self._apply([ROW_A])  # falta B
		self.assertEqual(frappe.db.get_value("Item", CODE_B, "disabled"), 1)
		# su Item Price abierto se cerró (valid_upto no vacío) — conservado, no borrado
		self.assertTrue(frappe.db.exists("Item Price", {"item_code": CODE_B, "price_list": PRICE_LIST}))
		self.assertTrue(self._price(CODE_B)[0].valid_upto)

	def test_reactivacion(self):
		if not self._has_company:
			self.skipTest("Site sin Company.")
		self._apply([ROW_A, ROW_B])
		self._apply([ROW_A])  # B desaparece -> disabled
		self._apply([ROW_A, ROW_B])  # B reaparece
		self.assertEqual(frappe.db.get_value("Item", CODE_B, "disabled"), 0)
