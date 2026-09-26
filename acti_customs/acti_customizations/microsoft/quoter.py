# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Selector/cotizador Microsoft dentro de Quotation (ADR-0003).

Selecciona entre los `Item` del catálogo Microsoft (item_group "Licenciamiento Microsoft") y agrega
el Item existente a una Quotation Draft. NO consulta `Microsoft Offer` (eliminado). NO crea Items.

Costo: NO se recalcula en runtime (la regla /12 se aplicó en el sync y vive en Item Price). El costo
para la venta se obtiene de la infraestructura de costo de ERPNext a través del resolver genérico de
`erpnext_proposals` (Item Price + FX por fecha/moneda). Aquí solo queda la regla comercial de margen
bruto: `precio = ROUNDUP(costo / (1 - margen), 2)`.
"""

import math

import frappe
from frappe.utils import flt

from acti_customs.acti_customizations.microsoft.keys import (
	build_display_name,
	friendly_billing,
	friendly_term,
	is_trial_offer,
)
from acti_customs.acti_customizations.microsoft.materializer import ITEM_GROUP, STOCK_UOM

# Orden de resolución (dimensiones). product_id/sku_id colapsan solos salvo ambigüedad real.
SELECT_ORDER = (
	"product_title",
	"product_id",
	"sku_title",
	"sku_id",
	"term_duration",
	"billing_plan",
	"segment",
)
VISIBLE_FIELDS = ("product_title", "sku_title", "term_duration", "billing_plan", "segment")
REQUIRED_ITEMS_FIELD = "required_items"

# Código de source del resolver de erpnext_proposals para "Item comprable sin fuente de costo".
SRC_SIN_COSTO = "sin_costo"

# Dimensión del selector -> campo real en Item.
_ITEM_FIELD = {
	"product_title": "ms_product_title",
	"product_id": "ms_product_id",
	"sku_title": "ms_sku_title",
	"sku_id": "ms_sku_id",
	"term_duration": "ms_term_duration",
	"billing_plan": "ms_billing_plan",
	"segment": "ms_segment",
}

_LABELS = {
	"product_title": "Producto",
	"product_id": "Product Id",
	"sku_title": "SKU",
	"sku_id": "Sku Id",
	"term_duration": "Compromiso",
	"billing_plan": "Facturacion",
	"segment": "Segmento",
}


class QuoterError(frappe.ValidationError):
	pass


def _value_label(field, value):
	if field == "term_duration":
		return friendly_term(value)
	if field == "billing_plan":
		return friendly_billing(value)
	return value


def _display_labels(term_duration, billing_plan, segment, tags=None):
	if is_trial_offer(term_duration, billing_plan, tags):
		return "Prueba 1 mes", ""
	return friendly_term(term_duration), friendly_billing(billing_plan)


def _candidates(selected):
	"""Items Microsoft NCE activos que cumplen la selección parcial (identidad por item_code).

	Mismo criterio NCE que el sync (`_plan`): solo Items con `ms_product_id` set. Items legacy/manuales
	del mismo Item Group pero SIN `ms_product_id` NO son ofertas Microsoft NCE y quedan fuera del selector.
	"""
	filters = {"item_group": ITEM_GROUP, "disabled": 0, "ms_product_id": ["is", "set"]}
	for k, v in (selected or {}).items():
		if k in _ITEM_FIELD and v not in (None, ""):
			filters[_ITEM_FIELD[k]] = v
	return frappe.get_all(
		"Item",
		filters=filters,
		fields=[
			"name",
			"item_name",
			"ms_product_title",
			"ms_product_id",
			"ms_sku_title",
			"ms_sku_id",
			"ms_term_duration",
			"ms_billing_plan",
			"ms_segment",
		],
	)


def _dim(item, field):
	"""Valor de una dimensión del selector para un Item."""
	return item.get(_ITEM_FIELD[field]) or ""


def _item_summary(item):
	compromiso, facturacion = _display_labels(
		item["ms_term_duration"], item["ms_billing_plan"], item["ms_segment"]
	)
	return {
		"offer_key": item["name"],  # identidad = item_code
		"item": item["name"],
		"item_code": item["name"],
		"product_title": item["ms_product_title"],
		"sku_title": item["ms_sku_title"],
		"term_duration": item["ms_term_duration"],
		"billing_plan": item["ms_billing_plan"],
		"segment": item["ms_segment"],
		"compromiso": compromiso,
		"facturacion": facturacion,
		"is_trial": is_trial_offer(item["ms_term_duration"], item["ms_billing_plan"]),
		"display": item["item_name"]
		or build_display_name(
			item["ms_sku_title"], item["ms_term_duration"], item["ms_billing_plan"], item["ms_segment"]
		),
	}


def next_step(selected):
	"""Resolución progresiva (lógica pura sobre Item)."""
	selected = dict(selected or {})
	cands = _candidates(selected)
	if not cands:
		return {"error": "No hay licencias que coincidan con la seleccion."}
	for field in SELECT_ORDER:
		if selected.get(field) not in (None, ""):
			continue
		values = sorted({_dim(c, field) for c in cands})
		if len(values) == 1:
			selected[field] = values[0]
			cands = [c for c in cands if _dim(c, field) == values[0]]
			continue
		return {
			"field": field,
			"label": _LABELS.get(field, field),
			"options": [{"value": v, "label": _value_label(field, v)} for v in values],
			"selected": selected,
		}
	if len(cands) != 1:
		return {"error": f"Seleccion ambigua: {len(cands)} licencias resuelven la misma identidad."}
	return {"resolved": _item_summary(cands[0]), "selected": selected}


def resolve_path(selected):
	"""Resolución progresiva CON selecciones editables (ver detalle en la versión previa)."""
	sel = dict(selected or {})
	running = {}
	steps = []
	for field in SELECT_ORDER:
		cands = _candidates(running)
		if not cands:
			return {
				"steps": steps,
				"selected": running,
				"error": "No hay licencias que coincidan con la seleccion.",
			}
		values = sorted({_dim(c, field) for c in cands})
		chosen = sel.get(field)
		if chosen not in values:
			chosen = values[0] if len(values) == 1 else None
		if field in VISIBLE_FIELDS or len(values) > 1:
			steps.append(
				{
					"field": field,
					"label": _LABELS.get(field, field),
					"options": [{"value": v, "label": _value_label(field, v)} for v in values],
					"value": chosen,
					"ambiguous": chosen is None,
				}
			)
		if chosen is None:
			return {"steps": steps, "selected": running}
		running[field] = chosen
	cands = _candidates(running)
	if len(cands) != 1:
		return {"steps": steps, "selected": running, "error": f"Seleccion ambigua: {len(cands)} licencias."}
	return {"steps": steps, "selected": running, "resolved": _item_summary(cands[0])}


# --- Pricing (margen bruto custom; el costo llega ya resuelto) -----------------


def roundup2(value):
	"""ROUNDUP a 2 decimales (siempre hacia arriba)."""
	return math.ceil(round(flt(value) * 100.0, 6)) / 100.0


def compute_unit_price(cost, margin_fraction):
	cost = flt(cost)
	if cost <= 0:
		return 0.0
	return roundup2(cost / (1.0 - margin_fraction))


def price_summary(summary, cost, qty, margin_pct):
	"""Resumen de precio a partir de un COSTO ya resuelto (en la moneda de la Quotation).

	`summary` es el dict de `_item_summary`. `cost` viene del resolver de costo (Item Price + FX),
	NO se recalcula aquí. `margin_pct` es porcentaje (20 = 20%). Regla: ROUNDUP(costo/(1-margen),2).
	"""
	qty = flt(qty)
	margin_pct = flt(margin_pct)
	if qty <= 0:
		raise QuoterError("La cantidad debe ser mayor a 0.")
	if margin_pct < 0 or margin_pct >= 100:
		raise QuoterError("El margen debe ser >= 0 y < 100%.")
	cost = flt(cost)
	price = compute_unit_price(cost, margin_pct / 100.0)
	return {
		"item": summary["item"],
		"display": summary["display"],
		"sku_title": summary["sku_title"],
		"compromiso": summary["compromiso"],
		"facturacion": summary["facturacion"],
		"is_trial": summary["is_trial"],
		"segment": summary["segment"],
		"qty": qty,
		"cost_unit": round(cost, 4),
		"margin_pct": margin_pct,
		"price_unit": price,
		"amount": round(price * qty, 2),
	}


def _load_valid_item(item_code):
	"""Carga y valida que el item_code sea un Item Microsoft activo (fail-closed)."""
	if not frappe.db.exists("Item", item_code):
		raise QuoterError(f"Item inexistente: {item_code!r}")
	vals = frappe.db.get_value("Item", item_code, ["item_group", "disabled"], as_dict=True)
	if vals.item_group != ITEM_GROUP:
		raise QuoterError(f"El Item {item_code!r} no pertenece al catalogo Microsoft.")
	if vals.disabled:
		raise QuoterError(f"El Item {item_code!r} esta deshabilitado.")
	return item_code


def _summary_for(item_code):
	item = frappe.db.get_value(
		"Item",
		item_code,
		[
			"name",
			"item_name",
			"ms_product_title",
			"ms_product_id",
			"ms_sku_title",
			"ms_sku_id",
			"ms_term_duration",
			"ms_billing_plan",
			"ms_segment",
		],
		as_dict=True,
	)
	return _item_summary(item)


def _get_resolver():
	"""Devuelve el resolver de costo genérico de erpnext_proposals (indirección testeable)."""
	from erpnext_proposals.erpnext_proposals.utils.item_cost import resolve_external_cost

	return resolve_external_cost


def resolve_cost(item_code, transaction_date, currency, company):
	"""FRONTERA con el resolver genérico de erpnext_proposals (Item Price + FX por fecha).

	acti_customs NO reimplementa selección de Price List, FX ni consulta Currency Exchange: delega en
	`resolve_external_cost(item, uom, transaction_date, company, target_currency)` y usa `ec.amount`
	(el costo externo expresado en la moneda de la Quotation). Fail-closed sin degradar a 0 cuando el
	costo es irresoluble (`amount is None`: `sin_tipo_cambio` / `ambiguo_price_list`). `sin_costo` /
	`no_purchase` devuelven 0 legítimo (p. ej. Trial). Devuelve el costo por unidad en `currency`.
	"""
	try:
		resolver = _get_resolver()
	except ImportError as exc:
		raise QuoterError(
			"Resolucion de costo pendiente: erpnext_proposals no esta instalado en este site."
		) from exc
	ec = resolver(
		item_code,
		uom=STOCK_UOM,
		transaction_date=transaction_date,
		company=company,
		target_currency=currency,
	)
	if ec.amount is None:
		# sin_tipo_cambio / ambiguo_price_list: irresoluble → fail-closed, NO se degrada a 0.
		raise QuoterError(
			f"Costo externo irresoluble ({ec.source}) para {item_code!r} en {currency}: "
			f"revise tipo de cambio / Price List de compra. No se degrada a 0."
		)
	if ec.source == SRC_SIN_COSTO:
		# El resolver ya distingue precio-0 (buying_item_price, costo 0 válido, p. ej. Trial) de
		# SIN precio (sin_costo). 'sin_costo' = Item comprable sin fuente de costo → fail-closed:
		# nunca cotizar aplicando margen sobre 0 (posible licencia mal sincronizada).
		raise QuoterError(
			f"Item comprable {item_code!r} sin fuente de costo (sin_costo): fail-closed. "
			f"No se cotiza sobre costo 0 (revise el Buying Item Price / sincronizacion del catalogo)."
		)
	# buying_item_price (incluye 0 legítimo, p. ej. Trial), no_purchase, last_purchase_rate, valuation_rate.
	return flt(ec.amount)


# --- API whitelisted (para el diálogo en Quotation) ---------------------------


@frappe.whitelist()
def get_next_options(selected=None):
	if isinstance(selected, str):
		selected = frappe.parse_json(selected) if selected else {}
	return next_step(selected or {})


@frappe.whitelist()
def get_selection_path(selected=None):
	if isinstance(selected, str):
		selected = frappe.parse_json(selected) if selected else {}
	return resolve_path(selected or {})


@frappe.whitelist()
def get_price_preview(offer_key: str, qty: float, margin_pct: float, quotation: str | None = None):
	"""Preview de precio. Requiere contexto de Quotation (moneda/fecha) para resolver el costo (FX)."""
	item_code = _load_valid_item(offer_key)
	if not quotation:
		raise QuoterError("Falta el contexto de Quotation para resolver el costo (moneda/fecha).")
	q = frappe.db.get_value("Quotation", quotation, ["currency", "transaction_date", "company"], as_dict=True)
	cost = resolve_cost(item_code, q.transaction_date, q.currency, q.company)
	return price_summary(_summary_for(item_code), cost, qty, margin_pct)


@frappe.whitelist()
def add_license_to_quotation(quotation: str, offer_key: str, qty: float, margin_pct: float):
	"""Destino VENTA: agrega el Item Microsoft como línea Quotation Item con rate calculado."""
	q = frappe.get_doc("Quotation", quotation)
	q.check_permission("write")
	if q.docstatus != 0:
		raise QuoterError("La Quotation no esta en Draft.")
	item_code = _load_valid_item(offer_key)
	cost = resolve_cost(item_code, q.transaction_date, q.currency, q.company)
	summary = price_summary(_summary_for(item_code), cost, qty, margin_pct)
	q.append("items", {"item_code": item_code, "qty": summary["qty"], "rate": summary["price_unit"]})
	q.save()
	summary["quotation"] = q.name
	summary["destination"] = "sale"
	return summary


def build_required_row(item_code, qty):
	"""Fila para required_items: SOLO item/qty/uom (fieldnames reales de Proposal Required Item)."""
	uom = frappe.db.get_value("Item", item_code, "stock_uom")
	return {"item": item_code, "qty": flt(qty), "uom": uom}


@frappe.whitelist()
def add_license_as_cost(quotation: str, offer_key: str, qty: float):
	"""Destino COSTO: agrega el Item Microsoft a required_items (item/qty/uom). Sin costo/precio/margen.

	El costo y el análisis económico los resuelve erpnext_proposals (fuente única: Item Price + FX).
	"""
	qty = flt(qty)
	if qty <= 0:
		raise QuoterError("La cantidad debe ser mayor a 0.")
	q = frappe.get_doc("Quotation", quotation)
	q.check_permission("write")
	if q.docstatus != 0:
		raise QuoterError("La Quotation no esta en Draft.")
	if not q.meta.has_field(REQUIRED_ITEMS_FIELD):
		raise QuoterError(
			"Esta Quotation no tiene la tabla de Items requeridos (requiere erpnext_proposals)."
		)
	item_code = _load_valid_item(offer_key)
	q.append(REQUIRED_ITEMS_FIELD, build_required_row(item_code, qty))
	q.save()
	return {"item": item_code, "qty": qty, "destination": "cost", "quotation": q.name}
