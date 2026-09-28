# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Tests de pricing nativo (Price List + Item Price + Item Default). ADR-0003."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import getdate

from acti_customs.acti_customizations.microsoft.materializer import ITEM_GROUP, STOCK_UOM, upsert_item
from acti_customs.acti_customizations.microsoft.pricing import (
	PRICE_LIST,
	PRICE_LIST_CURRENCY,
	PricingError,
	close_open_item_prices,
	ensure_price_list,
	set_item_default_price_list,
	upsert_buying_item_price,
)
from acti_customs.acti_customizations.microsoft.test_materializer import ROW, _prereqs

CODE = "MS-CFQ7X1-S1-P1Y-Annual-Commercial"


class TestPricing(FrappeTestCase):
	def setUp(self):
		self._cleanup()
		_prereqs()
		upsert_item(ROW)

	def tearDown(self):
		self._cleanup()

	def _cleanup(self):
		for name in frappe.get_all("Item Price", filters={"price_list": PRICE_LIST}, pluck="name"):
			frappe.delete_doc("Item Price", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Item", filters={"item_group": ITEM_GROUP}, pluck="name"):
			frappe.delete_doc("Item", name, force=True, ignore_permissions=True)
		if frappe.db.exists("Price List", PRICE_LIST):
			frappe.delete_doc("Price List", PRICE_LIST, force=True, ignore_permissions=True)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit -- limpieza de test

	def test_ensure_price_list_crea_buying_usd(self):
		ensure_price_list()
		d = frappe.db.get_value(
			"Price List", PRICE_LIST, ["buying", "selling", "currency", "enabled"], as_dict=True
		)
		self.assertEqual((d.buying, d.selling, d.currency, d.enabled), (1, 0, PRICE_LIST_CURRENCY, 1))

	def test_ensure_price_list_failclosed_incompatible(self):
		frappe.get_doc(
			{
				"doctype": "Price List",
				"price_list_name": PRICE_LIST,
				"buying": 0,
				"selling": 1,
				"currency": "MXN",
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(PricingError):
			ensure_price_list()

	def test_item_price_usd(self):
		upsert_buying_item_price(CODE, 10.0, STOCK_UOM, "2025-01-01", "9999-11-30")
		rows = frappe.get_all(
			"Item Price",
			filters={"item_code": CODE, "price_list": PRICE_LIST},
			fields=["price_list_rate", "currency", "uom"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].price_list_rate, 10.0)
		self.assertEqual(rows[0].currency, PRICE_LIST_CURRENCY)
		self.assertEqual(rows[0].uom, STOCK_UOM)

	def test_idempotente(self):
		upsert_buying_item_price(CODE, 10.0, STOCK_UOM, "2025-01-01", "9999-11-30")
		upsert_buying_item_price(CODE, 10.0, STOCK_UOM, "2025-01-01", "9999-11-30")
		self.assertEqual(frappe.db.count("Item Price", {"item_code": CODE, "price_list": PRICE_LIST}), 1)

	def test_precio_nuevo_preserva_historico(self):
		upsert_buying_item_price(CODE, 120.0, STOCK_UOM, "2026-08-01", None)
		upsert_buying_item_price(CODE, 132.0, STOCK_UOM, "2026-09-01", None)
		rows = frappe.get_all(
			"Item Price",
			filters={"item_code": CODE, "price_list": PRICE_LIST},
			fields=["price_list_rate", "valid_from", "valid_upto"],
			order_by="valid_from asc",
		)
		self.assertEqual(len(rows), 2)  # histórico preservado
		self.assertEqual(rows[0].price_list_rate, 120.0)
		self.assertEqual(getdate(rows[0].valid_upto), getdate("2026-08-31"))  # cerrado día previo
		self.assertEqual(rows[1].price_list_rate, 132.0)
		self.assertIsNone(rows[1].valid_upto)

	def test_close_open_item_prices(self):
		upsert_buying_item_price(CODE, 10.0, STOCK_UOM, "2025-01-01", None)
		close_open_item_prices(CODE, "2026-09-30")
		row = frappe.get_all(
			"Item Price", filters={"item_code": CODE, "price_list": PRICE_LIST}, fields=["valid_upto"]
		)[0]
		self.assertEqual(getdate(row.valid_upto), getdate("2026-09-30"))

	def test_item_default(self):
		company = frappe.db.get_value("Company", {}, "name")
		if not company:
			self.skipTest(
				"Site sin Company (bare CI); Item Default se valida en site con ERPNext configurado."
			)
		set_item_default_price_list(CODE, company)
		set_item_default_price_list(CODE, company)  # idempotente
		it = frappe.get_doc("Item", CODE)
		rows = [d for d in it.item_defaults if d.company == company]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].default_price_list, PRICE_LIST)
