# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Costo Microsoft como Item Price NATIVO (ADR-0003).

Fuente única de costo: `Item Price` (buying) de la Price List propia de acti_customs
`Microsoft NCE - Compra` (USD). Aquí vive todo lo referente a:
  - asegurar la Price List (idempotente; fail-closed si existe con config incompatible);
  - persistir/actualizar el Buying Item Price (USD) con vigencias, preservando histórico;
  - fijar `Item Default.default_price_list` por Item+Company (selector nativo de costo).

NO se convierte a MXN aquí (la conversión FX la hace el resolver genérico de erpnext_proposals con
`get_exchange_rate` por fecha). El `UnitPrice` crudo NO se persiste; solo el costo ya calculado.
"""

import frappe
from frappe.utils import add_days, flt, getdate, today

from acti_customs.acti_customizations.microsoft.materializer import STOCK_UOM

PRICE_LIST = "Microsoft NCE - Compra"
PRICE_LIST_CURRENCY = "USD"


class PricingError(frappe.ValidationError):
	"""Configuración de pricing inconsistente (fail-closed)."""


def ensure_price_list():
	"""Asegura la Buying Price List Microsoft (idempotente).

	Si no existe la crea (buying=1, selling=0, USD, enabled=1). Si existe, valida su configuración;
	si es incompatible, fail-closed (no se corrige silenciosamente). NO toca Buying Settings ni la
	vuelve global.
	"""
	if frappe.db.exists("Price List", PRICE_LIST):
		d = frappe.db.get_value(
			"Price List", PRICE_LIST, ["buying", "selling", "currency", "enabled"], as_dict=True
		)
		problems = []
		if not d.buying:
			problems.append("buying debe ser 1")
		if d.selling:
			problems.append("selling debe ser 0")
		if d.currency != PRICE_LIST_CURRENCY:
			problems.append(f"currency debe ser {PRICE_LIST_CURRENCY} (es {d.currency!r})")
		if not d.enabled:
			problems.append("enabled debe ser 1")
		if problems:
			raise PricingError(
				f"Price List {PRICE_LIST!r} existe con configuracion incompatible: {'; '.join(problems)}. "
				f"No se corrige silenciosamente."
			)
		return PRICE_LIST
	frappe.get_doc(
		{
			"doctype": "Price List",
			"price_list_name": PRICE_LIST,
			"buying": 1,
			"selling": 0,
			"currency": PRICE_LIST_CURRENCY,
			"enabled": 1,
		}
	).insert(ignore_permissions=True)
	return PRICE_LIST


def _rows(item_code):
	return frappe.get_all(
		"Item Price",
		filters={"item_code": item_code, "price_list": PRICE_LIST},
		fields=["name", "price_list_rate", "valid_from", "valid_upto"],
		order_by="valid_from asc",
	)


def upsert_buying_item_price(item_code, cost, uom=None, valid_from=None, valid_upto=None):
	"""Persiste el costo (USD) del Item en Item Price. Idempotente y preserva histórico.

	- Existe una fila con el MISMO `valid_from` → se corrige en sitio solo si rate/valid_upto difieren.
	- `valid_from` nuevo (cambio de precio/periodo) → se cierran las filas abiertas/solapadas anteriores
	  (`valid_upto` = día previo al nuevo `valid_from`) y se crea la nueva. No se borra histórico.
	"""
	ensure_price_list()
	cost = flt(cost)
	uom = uom or STOCK_UOM
	vf = getdate(valid_from) if valid_from else None
	vu = getdate(valid_upto) if valid_upto else None
	rows = _rows(item_code)

	for r in rows:
		rvf = getdate(r.valid_from) if r.valid_from else None
		if rvf == vf:
			changes = {}
			if flt(r.price_list_rate) != cost:
				changes["price_list_rate"] = cost
			rvu = getdate(r.valid_upto) if r.valid_upto else None
			if rvu != vu:
				changes["valid_upto"] = vu
			if changes:
				doc = frappe.get_doc("Item Price", r.name)
				for k, v in changes.items():
					doc.set(k, v)
				doc.save(ignore_permissions=True)
			return r.name

	# Nuevo periodo: cerrar filas abiertas o que se solapen con el nuevo valid_from.
	if vf:
		for r in rows:
			rvu = getdate(r.valid_upto) if r.valid_upto else None
			if rvu is None or rvu >= vf:
				frappe.db.set_value("Item Price", r.name, "valid_upto", add_days(vf, -1))

	doc = frappe.get_doc(
		{
			"doctype": "Item Price",
			"item_code": item_code,
			"price_list": PRICE_LIST,
			"uom": uom,
			"price_list_rate": cost,
			"valid_from": vf,
			"valid_upto": vu,
		}
	).insert(ignore_permissions=True)
	return doc.name


def close_open_item_prices(item_code, valid_upto=None):
	"""Cierra los Item Price abiertos del Item (oferta desaparecida). No borra histórico."""
	vu = getdate(valid_upto) if valid_upto else getdate(today())
	names = frappe.get_all(
		"Item Price",
		filters={"item_code": item_code, "price_list": PRICE_LIST, "valid_upto": ["is", "not set"]},
		pluck="name",
	)
	for name in names:
		frappe.db.set_value("Item Price", name, "valid_upto", vu)
	return len(names)


def set_item_default_price_list(item_code, company):
	"""Fija item_defaults[company].default_price_list = Microsoft NCE - Compra (idempotente).

	No toca defaults de otras Company ni otros campos del default de esta Company.
	"""
	ensure_price_list()  # el default_price_list debe apuntar a una Price List existente (link válido)
	doc = frappe.get_doc("Item", item_code)
	for row in doc.item_defaults or []:
		if row.company == company:
			if row.default_price_list != PRICE_LIST:
				row.default_price_list = PRICE_LIST
				doc.save(ignore_permissions=True)
			return
	doc.append("item_defaults", {"company": company, "default_price_list": PRICE_LIST})
	doc.save(ignore_permissions=True)
