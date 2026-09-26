# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Materialización de una oferta Microsoft (fila del Excel) en un `Item` ERPNext (ADR-0003).

Cada oferta `ProductId+SkuId+TermDuration+BillingPlan+Segment` = 1 Item, con `item_code`
determinista como identidad. NO existe `Microsoft Offer`. Metadata Microsoft mínima en el Item
(dimensiones del selector). El costo NO vive aquí: vive en Item Price (ver `pricing.py`).

Idempotente por `item_code`: si el Item ya existe se reutiliza y solo se actualiza metadata mutable
(item_name/description/product_title); las dimensiones son parte del item_code y no cambian.
"""

import frappe

from acti_customs.acti_customizations.microsoft.keys import build_display_name_capped, build_item_code

# Baseline aprobada para los Items del catálogo Microsoft.
ITEM_GROUP = "Licenciamiento Microsoft"
STOCK_UOM = "E48 - Servicio"  # UOM real existente en el site (SAT E48). No crear otra.
SAT_PRODUCTO_SERVICIO = "81112501"
SAT_FIELD = "fm_producto_servicio_sat"  # custom field de facturacion_mexico (opcional)

# Campos Microsoft MÍNIMOS en Item (dimensiones sin equivalente nativo, para el selector).
_MS_FIELD_MAP = {
	"ms_product_id": "product_id",
	"ms_sku_id": "sku_id",
	"ms_term_duration": "term_duration",
	"ms_billing_plan": "billing_plan",
	"ms_segment": "segment",
	"ms_product_title": "product_title",
}


class MaterializeError(frappe.ValidationError):
	"""Inconsistencia que impide materializar de forma segura (fail-closed)."""


def _assert_fiscal_prereqs():
	"""acti_customs CONSUME catálogos fiscales (UOM/Item Group); no los crea ni administra."""
	if not frappe.db.exists("UOM", STOCK_UOM):
		raise MaterializeError(
			f"Falta configuracion fiscal requerida: la UOM {STOCK_UOM!r} no existe en el site "
			f"(la administra facturacion_mexico). acti_customs no la crea."
		)
	if not frappe.db.exists("Item Group", ITEM_GROUP):
		raise MaterializeError(f"Falta el Item Group {ITEM_GROUP!r} en el site.")


def item_code_for(row):
	"""item_code determinista de una fila del catálogo."""
	return build_item_code(
		row["product_id"], row["sku_id"], row["term_duration"], row["billing_plan"], row["segment"]
	)


def _display_name(row):
	return build_display_name_capped(
		row["sku_title"], row["term_duration"], row["billing_plan"], row["segment"], row.get("tags")
	)


def _apply_metadata(item, row):
	"""Aplica metadata mutable/estructurada de la fila al Item (sin tocar identidad)."""
	item.item_name = _display_name(row)
	if row.get("sku_description"):
		item.description = row["sku_description"]
	for item_field, row_field in _MS_FIELD_MAP.items():
		item.set(item_field, row.get(row_field))
	if item.meta.has_field(SAT_FIELD) and not item.get(SAT_FIELD):
		item.set(SAT_FIELD, SAT_PRODUCTO_SERVICIO)


def _build_item(row, item_code):
	item = frappe.new_doc("Item")
	item.item_code = item_code
	item.item_group = ITEM_GROUP
	item.stock_uom = STOCK_UOM
	item.is_stock_item = 0
	item.is_sales_item = 1
	item.is_purchase_item = 1
	item.disabled = 0
	if item.meta.has_field("sales_uom"):
		item.sales_uom = STOCK_UOM
	_apply_metadata(item, row)
	return item


def upsert_item(row):
	"""Crea o reutiliza el Item de una fila del catálogo. Idempotente por `item_code`.

	Devuelve el `item_code`. Si el Item ya existe (reutilización): reactiva si estaba disabled y
	actualiza metadata mutable (item_name/description/product_title) si cambió. Fail-closed ante
	prerequisitos fiscales ausentes al crear.
	"""
	code = item_code_for(row)
	if frappe.db.exists("Item", code):
		item = frappe.get_doc("Item", code)
		before = (item.item_name, item.get("description"), item.get("ms_product_title"), item.disabled)
		_apply_metadata(item, row)
		item.disabled = 0  # reactivar si reaparece
		after = (item.item_name, item.get("description"), item.get("ms_product_title"), item.disabled)
		if before != after:
			item.save(ignore_permissions=True)
		return code
	_assert_fiscal_prereqs()
	_build_item(row, code).insert(ignore_permissions=True)
	return code
