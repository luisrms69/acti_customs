# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from acti_customs.acti_customizations.microsoft.keys import (
	ITEM_NAME_MAXLEN,
	OfferKeyError,
	build_display_name,
	build_display_name_capped,
	build_item_code,
	build_item_name,
	build_item_name_capped,
	build_offer_key,
)

# El test runner no debe generar registros de prueba para Item (su grafo de links
# alcanza doctypes de apps no instaladas en el test site, p.ej. Payment Gateway).
# Los tests de Microsoft Offer no requieren registros de Item.
test_ignore = ["Item"]

# Oferta de referencia (ejemplo del diseno).
REF = dict(
	product_id="CFQ7TTC0LH2Z",
	sku_id="003J",
	term_duration="P3Y",
	billing_plan="Triennial",
	segment="Commercial",
)


class TestKeys(FrappeTestCase):
	def test_offer_key_deterministic(self):
		self.assertEqual(build_offer_key(**REF), "CFQ7TTC0LH2Z|003J|P3Y|Triennial|Commercial")

	def test_item_code_deterministic(self):
		self.assertEqual(build_item_code(**REF), "MS-CFQ7TTC0LH2Z-003J-P3Y-Triennial-Commercial")

	def test_component_empty_raises(self):
		bad = dict(REF, sku_id="")
		with self.assertRaises(OfferKeyError):
			build_offer_key(**bad)

	def test_component_with_separator_raises(self):
		with self.assertRaises(OfferKeyError):
			build_offer_key(**dict(REF, product_id="CFQ7-TTC0"))
		with self.assertRaises(OfferKeyError):
			build_offer_key(**dict(REF, segment="Comm|ercial"))

	def test_item_name_full_short(self):
		name = build_item_name(
			"Office 365 E3", "CFQ7TTC0LF8R", "Office 365 E3", "P1Y", "Annual", "Commercial"
		)
		self.assertIn("Office 365 E3", name)
		self.assertTrue(name.endswith("Commercial"))
		self.assertLessEqual(len(name), ITEM_NAME_MAXLEN)

	def test_item_name_capped_preserves_six(self):
		long_title = "Dynamics 365 Operations - Sandbox Tier 4:Standard Performance Testing (Education Faculty Pricing)"
		capped = build_item_name_capped(long_title, "CFQ7TTC0LHXZ", long_title, "P1M", "Monthly", "Education")
		self.assertLessEqual(len(capped), ITEM_NAME_MAXLEN)
		# Las 4 dimensiones cortas quedan intactas.
		for token in ("CFQ7TTC0LHXZ", "P1M", "Monthly", "Education"):
			self.assertIn(token, capped)
		# Se muestra (abreviado) el titulo.
		self.assertIn("Dynamics 365", capped)
		self.assertIn("…", capped)
		# Estructura de 6 componentes.
		self.assertEqual(len(capped.split(" | ")), 6)

	# --- item_name definitivo (display) ---
	def test_display_name_friendly(self):
		self.assertEqual(
			build_display_name("Power BI Pro", "P1Y", "Annual", "Commercial"),
			"Power BI Pro | 1 año | anual | Commercial",
		)
		self.assertEqual(
			build_display_name("Office 365 A3", "P1M", "Monthly", "Education"),
			"Office 365 A3 | 1 mes | mensual | Education",
		)
		self.assertEqual(
			build_display_name("X", "P3Y", "Triennial", "Charity"), "X | 3 años | cada 3 años | Charity"
		)

	def test_display_name_unmapped_value_kept_raw(self):
		# billing_plan 'None' (valor real del catalogo) no se inventa: se conserva crudo.
		self.assertEqual(
			build_display_name("Foo", "P1M", "None", "Commercial"), "Foo | 1 mes | None | Commercial"
		)

	def test_display_name_trial_combined(self):
		# P1M + None + Trial (validado por Tags) -> 'Prueba 1 mes', sin componente 'None'.
		name = build_display_name(
			"Agent 365 (Education Faculty Pricing)", "P1M", "None", "Education", tags="License;Trial"
		)
		self.assertEqual(name, "Agent 365 (Education Faculty Pricing) | Prueba 1 mes | Education")
		self.assertNotIn("None", name)
		self.assertEqual(len(name.split(" | ")), 3)

	def test_display_name_none_without_trial_tag_kept(self):
		# P1M + None SIN tag Trial -> se conserva 'None' (no se asume Trial).
		self.assertEqual(
			build_display_name("Foo", "P1M", "None", "Commercial", tags="License"),
			"Foo | 1 mes | None | Commercial",
		)

	def test_display_name_capped_middle_truncates_only_sku(self):
		long_sku = "Dynamics 365 Operations - Sandbox Tier 4:Standard Performance Testing (Education Faculty Pricing)"
		# maxlen reducido para forzar el truncado del SkuTitle de forma determinista.
		capped = build_display_name_capped(long_sku, "P1M", "Monthly", "Education", maxlen=60)
		self.assertLessEqual(len(capped), 60)
		parts = capped.split(" | ")
		self.assertEqual(len(parts), 4)
		# compromiso/facturacion/segmento intactos:
		self.assertEqual(parts[1], "1 mes")
		self.assertEqual(parts[2], "mensual")
		self.assertEqual(parts[3], "Education")
		# truncado en MEDIO del SkuTitle: conserva inicio y fin.
		self.assertIn("…", parts[0])
		self.assertTrue(parts[0].startswith("Dynamics 365"))
		self.assertTrue(parts[0].endswith(")"))


class TestMicrosoftOffer(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_create_names_by_offer_key(self):
		doc = frappe.get_doc(
			{
				"doctype": "Microsoft Offer",
				"product_title": "Office 365 E3",
				"sku_title": "Office 365 E3",
				"unit_price": 100,
				**REF,
			}
		).insert(ignore_permissions=True)
		self.assertEqual(doc.name, "CFQ7TTC0LH2Z|003J|P3Y|Triennial|Commercial")
		self.assertEqual(doc.offer_key, doc.name)
		self.assertEqual(doc.expected_item_code(), "MS-CFQ7TTC0LH2Z-003J-P3Y-Triennial-Commercial")

	def test_duplicate_offer_key_raises(self):
		base = {
			"doctype": "Microsoft Offer",
			"product_title": "X",
			"sku_title": "X",
			**REF,
		}
		frappe.get_doc(dict(base)).insert(ignore_permissions=True)
		with self.assertRaises(frappe.exceptions.DuplicateEntryError):
			frappe.get_doc(dict(base)).insert(ignore_permissions=True)

	def test_bad_segment_raises(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Microsoft Offer",
					"product_title": "X",
					"sku_title": "X",
					**dict(REF, segment="Gov"),
				}
			).insert(ignore_permissions=True)

	def test_end_before_start_raises(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Microsoft Offer",
					"product_title": "X",
					"sku_title": "X",
					"effective_start_date": "2026-01-10",
					"effective_end_date": "2026-01-01",
					**REF,
				}
			).insert(ignore_permissions=True)

	def test_is_vigente(self):
		doc = frappe.get_doc(
			{
				"doctype": "Microsoft Offer",
				"product_title": "X",
				"sku_title": "X",
				"effective_start_date": "2026-01-01",
				"effective_end_date": "2026-12-31",
				**REF,
			}
		).insert(ignore_permissions=True)
		self.assertTrue(doc.is_vigente("2026-06-15"))
		self.assertFalse(doc.is_vigente("2025-12-31"))
		self.assertFalse(doc.is_vigente("2027-01-01"))
		doc.is_active = 0
		self.assertFalse(doc.is_vigente("2026-06-15"))

	def test_item_custom_fields_exist(self):
		meta = frappe.get_meta("Item")
		for fn in ("ms_offer", "ms_offer_key", "ms_product_id", "ms_sku_id", "ms_segment"):
			self.assertTrue(meta.has_field(fn), f"falta custom field Item.{fn}")
