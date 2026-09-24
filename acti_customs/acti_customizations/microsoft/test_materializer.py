# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Tests del materializador Microsoft Offer -> Item.

Este es un test de MODULO (no vive bajo doctype/<x>/) a proposito: asi el runner de
Frappe no genera automaticamente test-records de Item (cuyo grafo de links alcanza
doctypes de apps no instaladas, p.ej. Payment Gateway). Los Items reales que crea el
materializador SI se prueban aqui; no se oculta ningun error propio con test_ignore.

Prerrequisitos reales creados en setUp (existen en los sites reales): la UOM
`E48 - Servicio` y el Item Group hoja `Licenciamiento Microsoft`.
"""

from unittest.mock import patch

import frappe
import frappe.model.meta
from frappe.tests.utils import FrappeTestCase

from acti_customs.acti_customizations.microsoft.materializer import (
	ITEM_GROUP,
	SAT_FIELD,
	SAT_PRODUCTO_SERVICIO,
	STOCK_UOM,
	MaterializeError,
	_build_item,
	materialize_item,
)

REF = dict(
	product_id="CFQ7TTC0LH2Z",
	sku_id="003J",
	term_duration="P3Y",
	billing_plan="Triennial",
	segment="Commercial",
)
EXPECTED_CODE = "MS-CFQ7TTC0LH2Z-003J-P3Y-Triennial-Commercial"


def _ensure_prereqs():
	if not frappe.db.exists("UOM", STOCK_UOM):
		frappe.get_doc({"doctype": "UOM", "uom_name": STOCK_UOM}).insert(ignore_permissions=True)
	if not frappe.db.exists("Item Group", ITEM_GROUP):
		# El site de CI (erpnext sin setup wizard) puede no tener la raíz "All Item Groups".
		parent = frappe.db.get_value("Item Group", {"is_group": 1}, "name")
		if not parent:
			root = frappe.get_doc({"doctype": "Item Group", "item_group_name": "All Item Groups", "is_group": 1})
			root.insert(ignore_permissions=True)
			parent = root.name
		frappe.get_doc(
			{"doctype": "Item Group", "item_group_name": ITEM_GROUP, "parent_item_group": parent, "is_group": 0}
		).insert(ignore_permissions=True)


class TestMaterializer(FrappeTestCase):
	def setUp(self):
		_ensure_prereqs()

	def tearDown(self):
		frappe.db.rollback()

	def _offer(self, **over):
		data = dict(
			{
				"doctype": "Microsoft Offer",
				"product_title": "Office 365 E3",
				"sku_title": "Office 365 E3 Sku",
				"market": "MX",
				"currency": "USD",
				"unit_price": 100,
			},
			**REF,
		)
		data.update(over)
		return frappe.get_doc(data).insert(ignore_permissions=True)

	# --- Caso A: creacion ---
	def test_creates_item_with_expected_code(self):
		offer = self._offer()
		code = materialize_item(offer)
		self.assertEqual(code, EXPECTED_CODE)
		self.assertTrue(frappe.db.exists("Item", EXPECTED_CODE))

	def test_erpnext_fields(self):
		offer = self._offer()
		item = frappe.get_doc("Item", materialize_item(offer))
		self.assertEqual(item.item_group, ITEM_GROUP)
		self.assertEqual(item.stock_uom, STOCK_UOM)
		self.assertEqual(item.is_stock_item, 0)
		self.assertEqual(item.is_sales_item, 1)
		self.assertEqual(item.is_purchase_item, 1)
		self.assertEqual(item.disabled, 0)
		if item.meta.has_field("sales_uom"):
			self.assertEqual(item.sales_uom, STOCK_UOM)

	def test_microsoft_fields(self):
		offer = self._offer()
		item = frappe.get_doc("Item", materialize_item(offer))
		self.assertEqual(item.ms_offer, offer.name)
		self.assertEqual(item.ms_offer_key, offer.offer_key)
		self.assertEqual(item.ms_product_id, REF["product_id"])
		self.assertEqual(item.ms_sku_id, REF["sku_id"])
		self.assertEqual(item.ms_term_duration, REF["term_duration"])
		self.assertEqual(item.ms_billing_plan, REF["billing_plan"])
		self.assertEqual(item.ms_segment, REF["segment"])
		self.assertEqual(item.ms_product_title, "Office 365 E3")
		self.assertEqual(item.ms_sku_title, "Office 365 E3 Sku")
		self.assertEqual(item.ms_market, "MX")
		self.assertEqual(item.ms_currency, "USD")

	def test_item_name_display_and_offer_label(self):
		offer = self._offer()
		item = frappe.get_doc("Item", materialize_item(offer))
		# item_name: SkuTitle | compromiso | facturacion | segmento (P3Y->3 años, Triennial->cada 3 años)
		self.assertEqual(item.item_name, "Office 365 E3 Sku | 3 años | cada 3 años | Commercial")
		self.assertLessEqual(len(item.item_name), 140)
		# ms_offer_label conserva la representacion COMPLETA de 6 atributos, sin truncar.
		self.assertEqual(
			item.ms_offer_label,
			"Office 365 E3 | CFQ7TTC0LH2Z | Office 365 E3 Sku | P3Y | Triennial | Commercial",
		)

	def test_fail_closed_when_uom_missing(self):
		# acti_customs NO crea la UOM fiscal: si falta, fail-closed claro.
		frappe.delete_doc("UOM", STOCK_UOM, force=True, ignore_permissions=True)
		offer = self._offer()
		with self.assertRaises(MaterializeError):
			materialize_item(offer)

	def test_link_offer_to_item(self):
		offer = self._offer()
		code = materialize_item(offer)
		offer.reload()
		self.assertEqual(offer.item, code)
		self.assertEqual(frappe.db.get_value("Item", code, "ms_offer"), offer.name)

	# --- Caso B: segunda ejecucion no duplica ---
	def test_idempotent_second_run(self):
		offer = self._offer()
		c1 = materialize_item(offer)
		c2 = materialize_item(offer)
		self.assertEqual(c1, c2)
		self.assertEqual(frappe.db.count("Item", {"ms_offer_key": offer.offer_key}), 1)

	# --- Caso C: existe Item por offer_key sin link -> reutiliza y repara ---
	def test_reuse_by_offer_key_repairs_link(self):
		offer = self._offer()
		# Crear el Item "a mano" con el offer_key pero sin vincular la oferta.
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": EXPECTED_CODE,
				"item_name": "cualquiera",
				"item_group": ITEM_GROUP,
				"stock_uom": STOCK_UOM,
				"is_stock_item": 0,
				"ms_offer_key": offer.offer_key,
				"ms_product_id": REF["product_id"],
				"ms_sku_id": REF["sku_id"],
			}
		).insert(ignore_permissions=True)
		code = materialize_item(offer)
		self.assertEqual(code, item.name)
		offer.reload()
		self.assertEqual(offer.item, item.name)
		self.assertEqual(frappe.db.count("Item", {"ms_offer_key": offer.offer_key}), 1)

	# --- Caso D: inconsistencias fail-closed ---
	def test_duplicate_offer_key_fails(self):
		offer = self._offer()
		for suffix in ("A", "B"):
			frappe.get_doc(
				{
					"doctype": "Item",
					"item_code": f"{EXPECTED_CODE}-{suffix}",
					"item_name": f"dup-{suffix}",
					"item_group": ITEM_GROUP,
					"stock_uom": STOCK_UOM,
					"is_stock_item": 0,
					"ms_offer_key": offer.offer_key,
				}
			).insert(ignore_permissions=True)
		with self.assertRaises(MaterializeError):
			materialize_item(offer)

	def test_item_code_collision_without_key_fails(self):
		offer = self._offer()
		# Un Item con el mismo item_code pero SIN ms_offer_key (p.ej. legacy homonimo).
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": EXPECTED_CODE,
				"item_name": "sin key",
				"item_group": ITEM_GROUP,
				"stock_uom": STOCK_UOM,
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
		with self.assertRaises(MaterializeError):
			materialize_item(offer)

	# --- Item legacy coarse NO se reutiliza ---
	def test_legacy_item_not_reused(self):
		# Legacy estilo MS-<ProductId>-1, sin ms_offer_key, mismo ProductId.
		legacy = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": "MS-CFQ7TTC0LH2Z-1",
				"item_name": "Legacy coarse",
				"item_group": ITEM_GROUP,
				"stock_uom": "H87 - Pieza" if frappe.db.exists("UOM", "H87 - Pieza") else STOCK_UOM,
				"is_stock_item": 0,
			}
		).insert(ignore_permissions=True)
		offer = self._offer()
		code = materialize_item(offer)
		self.assertEqual(code, EXPECTED_CODE)
		self.assertNotEqual(code, legacy.name)
		# El legacy sigue intacto y sin vinculo.
		self.assertFalse(frappe.db.get_value("Item", legacy.name, "ms_offer_key"))

	# --- SAT: seguro si el custom field NO existe (test site sin facturacion_mexico) ---
	def test_sat_safe_when_field_absent(self):
		self.assertFalse(frappe.get_meta("Item").has_field(SAT_FIELD))
		offer = self._offer()
		code = materialize_item(offer)  # no debe fallar
		self.assertTrue(frappe.db.exists("Item", code))

	# --- SAT: poblado cuando el custom field existe (sin DDL: se simula el campo) ---
	def test_sat_populated_when_field_exists(self):
		offer = self._offer()
		orig_has_field = frappe.model.meta.Meta.has_field

		def fake_has_field(meta_self, fieldname):
			if fieldname == SAT_FIELD:
				return True
			return orig_has_field(meta_self, fieldname)

		with patch.object(frappe.model.meta.Meta, "has_field", fake_has_field):
			item = _build_item(offer, EXPECTED_CODE)
		self.assertEqual(item.get(SAT_FIELD), SAT_PRODUCTO_SERVICIO)
