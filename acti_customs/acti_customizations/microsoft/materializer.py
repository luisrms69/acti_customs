# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Materializacion server-side de una `Microsoft Offer` en un `Item` ERPNext.

Dada una oferta valida, crea (o reutiliza) su Item de forma idempotente. La identidad
y la idempotencia se controlan por `offer_key` y por el vinculo Offer<->Item, NUNCA por
ProductId, item_name, similitud de texto ni prefijo `MS-*` (por eso los 15 Items legacy
coarse jamas se reutilizan para una oferta exacta nueva).

El sincronizador futuro del catalogo llamara `materialize_item(offer)` por cada oferta.
No hay endpoint publico, boton ni UI.
"""

import frappe

from acti_customs.acti_customizations.microsoft.keys import build_display_name_capped, build_item_name

# Baseline aprobada para NUEVOS Items del catalogo Microsoft.
ITEM_GROUP = "Licenciamiento Microsoft"
STOCK_UOM = "E48 - Servicio"  # UOM real existente en el site (SAT E48). No crear otra.
SAT_PRODUCTO_SERVICIO = "81112501"
SAT_FIELD = "fm_producto_servicio_sat"  # custom field de facturacion_mexico (opcional)

# Campos estructurados Microsoft en Item <- Microsoft Offer.
_MS_FIELD_MAP = {
	"ms_offer": "name",
	"ms_offer_key": "offer_key",
	"ms_product_id": "product_id",
	"ms_sku_id": "sku_id",
	"ms_term_duration": "term_duration",
	"ms_billing_plan": "billing_plan",
	"ms_segment": "segment",
	"ms_product_title": "product_title",
	"ms_sku_title": "sku_title",
	"ms_market": "market",
	"ms_currency": "currency",
}


class MaterializeError(frappe.ValidationError):
	"""Inconsistencia que impide materializar de forma segura (fail-closed)."""


def _load_offer(offer):
	if isinstance(offer, str):
		return frappe.get_doc("Microsoft Offer", offer)
	return offer


def _offer_args(offer):
	return (
		offer.product_title,
		offer.product_id,
		offer.sku_title,
		offer.term_duration,
		offer.billing_plan,
		offer.segment,
	)


def _assert_fiscal_prereqs():
	"""acti_customs CONSUME catalogos fiscales (UOM/SAT); no los crea ni administra."""
	if not frappe.db.exists("UOM", STOCK_UOM):
		raise MaterializeError(
			f"Falta configuracion fiscal requerida: la UOM {STOCK_UOM!r} no existe en el site "
			f"(la administra facturacion_mexico). acti_customs no la crea."
		)
	if not frappe.db.exists("Item Group", ITEM_GROUP):
		raise MaterializeError(f"Falta el Item Group {ITEM_GROUP!r} en el site.")


def _assert_structured_consistent(item_name, offer, expected_code):
	"""Verifica que un Item existente corresponde estructuralmente a la oferta."""
	vals = frappe.db.get_value(
		"Item", item_name, ["item_code", "ms_offer_key", "ms_product_id", "ms_sku_id"], as_dict=True
	)
	if vals.item_code != expected_code:
		raise MaterializeError(
			f"Item {item_name}: item_code={vals.item_code!r} != esperado {expected_code!r} (fail-closed)"
		)
	if vals.ms_offer_key != offer.offer_key:
		raise MaterializeError(
			f"Item {item_name}: ms_offer_key={vals.ms_offer_key!r} != {offer.offer_key!r} (fail-closed)"
		)
	if vals.ms_product_id != offer.product_id or vals.ms_sku_id != offer.sku_id:
		raise MaterializeError(
			f"Item {item_name}: campos estructurados no coinciden con la oferta (fail-closed)"
		)


def _build_item(offer, item_code):
	item = frappe.new_doc("Item")
	item.item_code = item_code
	# item_name estandar (<=140): SkuTitle | compromiso | facturacion | segmento
	# (abrevia solo el SkuTitle). NO es la fuente de identidad; la completa vive en
	# ms_offer_label + ms_*.
	item.item_name = build_display_name_capped(
		offer.sku_title, offer.term_duration, offer.billing_plan, offer.segment
	)
	item.item_group = ITEM_GROUP
	item.stock_uom = STOCK_UOM
	item.is_stock_item = 0
	item.is_sales_item = 1
	item.is_purchase_item = 1
	item.disabled = 0
	# sales_uom solo si el campo existe realmente en este ERPNext.
	if item.meta.has_field("sales_uom"):
		item.sales_uom = STOCK_UOM
	# Campos Microsoft estructurados.
	for item_field, offer_field in _MS_FIELD_MAP.items():
		item.set(item_field, offer.get(offer_field))
	# Etiqueta comercial completa (sin truncar) en campo propio de acti_customs.
	item.ms_offer_label = build_item_name(*_offer_args(offer))
	# SAT: poblar solo si el custom field de facturacion_mexico existe (no dependemos de el).
	if item.meta.has_field(SAT_FIELD):
		item.set(SAT_FIELD, SAT_PRODUCTO_SERVICIO)
	return item


def materialize_item(offer):
	"""Crea o reutiliza el Item de una Microsoft Offer. Idempotente por offer_key.

	Devuelve el name (== item_code) del Item. Lanza MaterializeError ante cualquier
	inconsistencia (fail-closed), sin elegir arbitrariamente.
	"""
	offer = _load_offer(offer)
	offer_key = offer.offer_key
	if not offer_key:
		raise MaterializeError("La Microsoft Offer no tiene offer_key (guardela primero).")
	expected_code = offer.expected_item_code()

	# Items existentes con este offer_key (identidad nueva; nunca por ProductId/nombre).
	by_key = frappe.get_all("Item", filters={"ms_offer_key": offer_key}, pluck="name")
	if len(by_key) > 1:
		raise MaterializeError(
			f"Caso D: {len(by_key)} Items comparten ms_offer_key={offer_key}: {by_key}. Fail-closed."
		)
	existing = by_key[0] if by_key else None

	# Caso B / D: la oferta ya tiene vinculo.
	if offer.item:
		if not frappe.db.exists("Item", offer.item):
			raise MaterializeError(
				f"Caso D: Microsoft Offer.item={offer.item!r} apunta a un Item inexistente."
			)
		if existing and existing != offer.item:
			raise MaterializeError(
				f"Caso D: la oferta apunta a {offer.item!r} pero otro Item ({existing!r}) tiene el mismo offer_key."
			)
		_assert_structured_consistent(offer.item, offer, expected_code)
		return offer.item  # Caso B: ya materializado y consistente.

	# Caso C: existe Item por offer_key pero la oferta no tiene link -> reparar vinculo.
	if existing:
		_assert_structured_consistent(existing, offer, expected_code)
		offer.db_set("item", existing)
		return existing

	# Caso A: no existe -> crear.
	if frappe.db.exists("Item", expected_code):
		# Colision de item_code sin offer_key (p.ej. un legacy con ese nombre): fail-closed.
		raise MaterializeError(
			f"Caso D: ya existe un Item con item_code={expected_code!r} sin ms_offer_key. Fail-closed."
		)
	_assert_fiscal_prereqs()
	item = _build_item(offer, expected_code)
	item.insert(ignore_permissions=True)
	offer.db_set("item", item.name)
	return item.name
