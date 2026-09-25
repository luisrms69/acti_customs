# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Selector/cotizador Microsoft dentro de Quotation.

Selecciona entre ofertas YA cargadas (Microsoft Offer) y agrega el Item YA vinculado a
una Quotation Draft. NO crea Items, NO importa Excel, NO modifica el catalogo.

- Resolucion progresiva: en cada dimension, 0 opciones -> error; 1 -> autoselecciona;
  >1 -> pide seleccion. Solo ofrece ofertas is_active=1, vigentes por fecha y con Item.
- Pricing: costo = UnitPrice/12 si (P1Y + Monthly), si no UnitPrice;
  precio = ROUNDUP(costo / (1 - margen), 2). Trial (UnitPrice 0) -> costo 0, precio 0.

Todo server-side (la UI no es la fuente de verdad).
"""

import math

import frappe
from frappe.utils import flt, getdate, today

from acti_customs.acti_customizations.microsoft.keys import (
	build_display_name,
	friendly_billing,
	friendly_term,
	is_trial_offer,
)

# Orden de resolucion. product_id/sku_id normalmente colapsan solos (no se muestran al
# vendedor salvo ambiguedad real).
SELECT_ORDER = (
	"product_title",
	"product_id",
	"sku_title",
	"sku_id",
	"term_duration",
	"billing_plan",
	"segment",
)

# Dimensiones visibles en el dialogo (product_id/sku_id son internas; se muestran solo si son ambiguas).
VISIBLE_FIELDS = ("product_title", "sku_title", "term_duration", "billing_plan", "segment")

# Tabla de "Items requeridos" de erpnext_proposals (destino "Agregar como costo"). acti_customs solo
# hace append de item/qty/uom; toda resolucion de costo y economia es responsabilidad de esa app.
REQUIRED_ITEMS_FIELD = "required_items"

_LABELS = {
	"product_title": "Producto",
	"product_id": "Product Id",
	"sku_title": "SKU",
	"sku_id": "Sku Id",
	"term_duration": "Compromiso",
	"billing_plan": "Facturacion",
	"segment": "Segmento",
}

_FIELDS = (
	"name",
	"product_title",
	"product_id",
	"sku_title",
	"sku_id",
	"term_duration",
	"billing_plan",
	"segment",
	"item",
	"unit_price",
	"tags",
	"effective_start_date",
	"effective_end_date",
)


class QuoterError(frappe.ValidationError):
	pass


def _value_label(field, value):
	if field == "term_duration":
		return friendly_term(value)
	if field == "billing_plan":
		return friendly_billing(value)
	return value


def _display_labels(term_duration, billing_plan, segment, tags):
	"""(compromiso, facturacion) para el resumen. Trial (P1M+None+Trial): 'Prueba 1 mes' y
	facturacion vacia (el dialogo omite la fila 'Facturacion: None')."""
	if is_trial_offer(term_duration, billing_plan, tags):
		return "Prueba 1 mes", ""
	return friendly_term(term_duration), friendly_billing(billing_plan)


def _is_vigente(offer, on=None):
	ref = getdate(on or today())
	if offer.get("effective_start_date") and ref < getdate(offer["effective_start_date"]):
		return False
	if offer.get("effective_end_date") and ref > getdate(offer["effective_end_date"]):
		return False
	return True


def _candidates(selected):
	"""Ofertas activas, vigentes, con Item, que cumplen la seleccion parcial."""
	filters = {"is_active": 1, "item": ["is", "set"]}
	for k, v in (selected or {}).items():
		if k in SELECT_ORDER and v not in (None, ""):
			filters[k] = v
	rows = frappe.get_all("Microsoft Offer", filters=filters, fields=list(_FIELDS))
	return [r for r in rows if _is_vigente(r)]


def _offer_summary(offer):
	compromiso, facturacion = _display_labels(
		offer["term_duration"], offer["billing_plan"], offer["segment"], offer.get("tags")
	)
	return {
		"offer_key": offer["name"],
		"item": offer["item"],
		"product_title": offer["product_title"],
		"sku_title": offer["sku_title"],
		"term_duration": offer["term_duration"],
		"billing_plan": offer["billing_plan"],
		"segment": offer["segment"],
		"unit_price": flt(offer["unit_price"]),
		"compromiso": compromiso,
		"facturacion": facturacion,
		"is_trial": is_trial_offer(offer["term_duration"], offer["billing_plan"], offer.get("tags")),
		"display": build_display_name(
			offer["sku_title"],
			offer["term_duration"],
			offer["billing_plan"],
			offer["segment"],
			offer.get("tags"),
		),
	}


def next_step(selected):
	"""Devuelve el siguiente paso de resolucion progresiva (logica pura sobre BD).

	Retorna una de:
	  {"field","label","options":[{value,label}], "selected": {...auto...}}  -> pedir eleccion
	  {"resolved": {...oferta...}, "selected": {...}}                         -> oferta unica
	  {"error": "..."}                                                        -> 0 candidatos
	"""
	selected = dict(selected or {})
	cands = _candidates(selected)
	if not cands:
		return {"error": "No hay ofertas vigentes que coincidan con la seleccion."}
	for field in SELECT_ORDER:
		if selected.get(field) not in (None, ""):
			continue
		values = sorted({(c.get(field) or "") for c in cands})
		if len(values) == 1:
			selected[field] = values[0]
			cands = [c for c in cands if (c.get(field) or "") == values[0]]
			continue
		return {
			"field": field,
			"label": _LABELS.get(field, field),
			"options": [{"value": v, "label": _value_label(field, v)} for v in values],
			"selected": selected,
		}
	if len(cands) != 1:
		# No deberia ocurrir (offer_key es unico); fail-closed.
		return {"error": f"Seleccion ambigua: {len(cands)} ofertas resuelven la misma identidad."}
	return {"resolved": _offer_summary(cands[0]), "selected": selected}


def resolve_path(selected):
	"""Resolucion progresiva CON selecciones editables (logica pura sobre BD).

	Camina SELECT_ORDER acumulando una seleccion valida. Devuelve la lista de pasos visibles ya
	decididos/pendientes (cada uno con sus opciones validas y el valor elegido/autoseleccionado), de
	modo que el dialogo pueda mostrar y permitir CAMBIAR cualquier dimension anterior. Al cambiar una
	dimension, el llamador reenvia solo el prefijo hasta esa dimension; las posteriores incompatibles se
	descartan aqui automaticamente (solo se conserva un valor si sigue siendo una opcion valida).

	Retorna: {"steps":[{field,label,options,value,ambiguous}], "selected":{...}, y ademas
	          "resolved":{...} si queda una sola oferta, o "error":"..." si 0 candidatos}.
	"""
	sel = dict(selected or {})
	running = {}
	steps = []
	for field in SELECT_ORDER:
		cands = _candidates(running)
		if not cands:
			return {
				"steps": steps,
				"selected": running,
				"error": "No hay ofertas vigentes que coincidan con la seleccion.",
			}
		values = sorted({(c.get(field) or "") for c in cands})
		chosen = sel.get(field)
		if chosen not in values:
			# Valor ausente o invalidado por un cambio anterior: autoselecciona si es unico, si no pide.
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
		return {"steps": steps, "selected": running, "error": f"Seleccion ambigua: {len(cands)} ofertas."}
	return {"steps": steps, "selected": running, "resolved": _offer_summary(cands[0])}


# --- Pricing ---------------------------------------------------------------


def compute_cost(unit_price, term_duration, billing_plan):
	up = flt(unit_price)
	if (term_duration or "").strip() == "P1Y" and (billing_plan or "").strip() == "Monthly":
		return up / 12.0
	return up


def roundup2(value):
	"""ROUNDUP a 2 decimales (siempre hacia arriba)."""
	return math.ceil(round(flt(value) * 100.0, 6)) / 100.0


def compute_unit_price(cost, margin_fraction):
	cost = flt(cost)
	if cost <= 0:
		return 0.0
	return roundup2(cost / (1.0 - margin_fraction))


def price_summary(offer, qty, margin_pct):
	"""Resumen de precio. margin_pct es porcentaje (ej. 20 = 20%)."""
	qty = flt(qty)
	margin_pct = flt(margin_pct)
	if qty <= 0:
		raise QuoterError("La cantidad debe ser mayor a 0.")
	if margin_pct < 0 or margin_pct >= 100:
		raise QuoterError("El margen debe ser >= 0 y < 100%.")
	margin = margin_pct / 100.0
	cost = compute_cost(offer["unit_price"], offer["term_duration"], offer["billing_plan"])
	price = compute_unit_price(cost, margin)
	compromiso, facturacion = _display_labels(
		offer["term_duration"], offer["billing_plan"], offer["segment"], offer.get("tags")
	)
	return {
		"item": offer["item"],
		"display": offer.get("display")
		or build_display_name(
			offer["sku_title"],
			offer["term_duration"],
			offer["billing_plan"],
			offer["segment"],
			offer.get("tags"),
		),
		"sku_title": offer["sku_title"],
		"compromiso": compromiso,
		"facturacion": facturacion,
		"is_trial": is_trial_offer(offer["term_duration"], offer["billing_plan"], offer.get("tags")),
		"segment": offer["segment"],
		"qty": qty,
		"cost_unit": round(cost, 4),
		"margin_pct": margin_pct,
		"price_unit": price,
		"amount": round(price * qty, 2),
	}


def _load_valid_offer(offer_key):
	"""Carga la oferta y valida activa/vigente/con Item consistente (fail-closed)."""
	if not frappe.db.exists("Microsoft Offer", offer_key):
		raise QuoterError(f"Microsoft Offer inexistente: {offer_key!r}")
	off = frappe.get_doc("Microsoft Offer", offer_key)
	if not off.is_active or not off.is_vigente():
		raise QuoterError("La oferta no esta activa/vigente.")
	if not off.item or not frappe.db.exists("Item", off.item):
		raise QuoterError("La oferta no tiene Item vinculado valido (fail-closed).")
	if frappe.db.get_value("Item", off.item, "ms_offer_key") != off.offer_key:
		raise QuoterError("Vinculo Offer<->Item inconsistente (fail-closed).")
	return off


def _offer_dict(off):
	return {
		"item": off.item,
		"sku_title": off.sku_title,
		"term_duration": off.term_duration,
		"billing_plan": off.billing_plan,
		"segment": off.segment,
		"unit_price": off.unit_price,
		"tags": off.tags,
	}


# --- API whitelisted (para el dialogo en Quotation) ------------------------


@frappe.whitelist()
def get_next_options(selected: str | None = None):
	if isinstance(selected, str):
		selected = frappe.parse_json(selected) if selected else {}
	return next_step(selected or {})


@frappe.whitelist()
def get_selection_path(selected: str | None = None):
	"""Resolucion editable para el dialogo (ver resolve_path)."""
	if isinstance(selected, str):
		selected = frappe.parse_json(selected) if selected else {}
	return resolve_path(selected or {})


@frappe.whitelist()
def get_price_preview(offer_key: str, qty: float, margin_pct: float):
	off = _load_valid_offer(offer_key)
	return price_summary(_offer_dict(off), qty, margin_pct)


@frappe.whitelist()
def add_license_to_quotation(quotation: str, offer_key: str, qty: float, margin_pct: float):
	"""Destino VENTA: agrega el Item Microsoft como linea Quotation Item con rate calculado."""
	q = frappe.get_doc("Quotation", quotation)
	q.check_permission("write")
	if q.docstatus != 0:
		raise QuoterError("La Quotation no esta en Draft.")
	off = _load_valid_offer(offer_key)
	summary = price_summary(_offer_dict(off), qty, margin_pct)
	q.append("items", {"item_code": off.item, "qty": summary["qty"], "rate": summary["price_unit"]})
	q.save()
	summary["quotation"] = q.name
	summary["destination"] = "sale"
	return summary


def build_required_row(off, qty):
	"""Fila para required_items: SOLO item/qty/uom (fieldnames reales de Proposal Required Item).

	acti_customs no escribe costo/precio/margen ni metadata economica: la resolucion de costo y el
	analisis economico son responsabilidad exclusiva de erpnext_proposals (fuente unica de costos).
	"""
	uom = frappe.db.get_value("Item", off.item, "stock_uom")
	return {"item": off.item, "qty": flt(qty), "uom": uom}


@frappe.whitelist()
def add_license_as_cost(quotation: str, offer_key: str, qty: float):
	"""Destino COSTO: agrega el Item Microsoft a required_items de la propuesta (item/qty/uom).

	NO crea Quotation Item, NO escribe costo/precio/margen. El costo y su efecto economico los resuelve
	erpnext_proposals con su fuente unica; acti_customs solo agrega el Item a la lista.
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
	off = _load_valid_offer(offer_key)
	q.append(REQUIRED_ITEMS_FIELD, build_required_row(off, qty))
	q.save()
	return {
		"item": off.item,
		"qty": qty,
		"display": build_display_name(
			off.sku_title, off.term_duration, off.billing_plan, off.segment, off.tags
		),
		"destination": "cost",
		"quotation": q.name,
	}
