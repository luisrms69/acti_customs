# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Sincronizacion del catalogo Microsoft: Excel -> Microsoft Offer -> Items.

Flujo idempotente:
  - lee/valida el Excel (fail-closed si esta mal formado);
  - UPSERT de Microsoft Offer por offer_key (crea nuevas, actualiza metadata mutable);
  - marca is_active=0 las ofertas que ya no vienen en el archivo (sin borrarlas);
  - materializa el Item faltante de cada oferta valida (materialize_item, idempotente);
  - nunca duplica Items; preserva intactos los 15 Items legacy.

acti_customs CONSUME catalogos fiscales (UOM/SAT/Item Group); no los crea ni administra.
Preflight fail-closed antes de aplicar si falta una dependencia.
"""

import frappe
from frappe.utils import cint, flt

from acti_customs.acti_customizations.microsoft.catalog import SHEET, CatalogError, read_catalog
from acti_customs.acti_customizations.microsoft.keys import (
	OfferKeyError,
	build_display_name,
	build_display_name_capped,
	build_offer_key,
)
from acti_customs.acti_customizations.microsoft.materializer import (
	ITEM_GROUP,
	STOCK_UOM,
	MaterializeError,
	materialize_item,
)

VALID_SEGMENTS = ("Commercial", "Education", "Charity")

# Campos de catalogo mutables (metadata NO identitaria) que se actualizan sin recrear Item.
_MUTABLE_STR = ("product_title", "sku_title", "currency", "market", "tags", "change_indicator")


def _norm(v):
	return "" if v is None else str(v).strip()


def _norm_date(v):
	return str(v)[:10] if v else None


def _differs(existing, row):
	"""True si la metadata mutable del archivo difiere de la oferta existente."""
	for f in _MUTABLE_STR:
		if _norm(existing.get(f)) != _norm(row.get(f)):
			return True
	if round(flt(existing.get("unit_price")), 2) != round(flt(row.get("unit_price")), 2):
		return True
	if _norm_date(existing.get("effective_start_date")) != (row.get("effective_start_date") or None):
		return True
	if _norm_date(existing.get("effective_end_date")) != (row.get("effective_end_date") or None):
		return True
	return False


def _assert_preflight():
	"""Dependencias fiscales/maestras que acti_customs consume (no crea)."""
	missing = []
	if not frappe.db.exists("UOM", STOCK_UOM):
		missing.append(f"UOM {STOCK_UOM!r} (la administra facturacion_mexico)")
	if not frappe.db.exists("Item Group", ITEM_GROUP):
		missing.append(f"Item Group {ITEM_GROUP!r}")
	if missing:
		raise CatalogError("Faltan dependencias requeridas en el site: " + "; ".join(missing))


def _plan(rows):
	"""Calcula el plan de sincronizacion en memoria (solo lectura)."""
	existing = {
		o.name: o
		for o in frappe.get_all(
			"Microsoft Offer",
			fields=[
				"name",
				"product_title",
				"sku_title",
				"unit_price",
				"currency",
				"market",
				"effective_start_date",
				"effective_end_date",
				"tags",
				"change_indicator",
				"is_active",
				"item",
			],
		)
	}
	item_keys = set(frappe.get_all("Item", filters={"ms_offer_key": ["is", "set"]}, pluck="ms_offer_key"))

	errors, valid, new, update, unchanged = [], [], [], [], []
	file_keys = set()
	for r in rows:
		try:
			key = build_offer_key(
				r["product_id"], r["sku_id"], r["term_duration"], r["billing_plan"], r["segment"]
			)
		except OfferKeyError as exc:
			errors.append({"row": r["_row"], "error": str(exc)})
			continue
		if r["segment"] not in VALID_SEGMENTS:
			errors.append(
				{"row": r["_row"], "offer_key": key, "error": f"Segment invalido: {r['segment']!r}"}
			)
			continue
		if key in file_keys:
			errors.append({"row": r["_row"], "offer_key": key, "error": "offer_key duplicado en el archivo"})
			continue
		file_keys.add(key)
		valid.append((key, r))
		ex = existing.get(key)
		if ex is None:
			new.append(key)
		elif _differs(ex, r):
			update.append(key)
		else:
			unchanged.append(key)

	to_inactivate = [k for k, o in existing.items() if o.is_active and k not in file_keys]
	items_to_create = [k for k, _ in valid if k not in item_keys]
	items_existing = [k for k, _ in valid if k in item_keys]
	return {
		"existing": existing,
		"valid": valid,
		"errors": errors,
		"new": new,
		"update": set(update),
		"unchanged": unchanged,
		"to_inactivate": to_inactivate,
		"items_to_create": items_to_create,
		"items_existing": items_existing,
	}


def _new_offer_doc(row):
	doc = frappe.new_doc("Microsoft Offer")
	for f in (
		"product_title",
		"product_id",
		"sku_title",
		"sku_id",
		"term_duration",
		"billing_plan",
		"segment",
		"market",
		"currency",
		"unit_price",
		"effective_start_date",
		"effective_end_date",
		"tags",
		"change_indicator",
	):
		doc.set(f, row.get(f))
	doc.is_active = 1
	return doc


def _apply_mutable(doc, row):
	for f in (
		"product_title",
		"sku_title",
		"currency",
		"market",
		"unit_price",
		"effective_start_date",
		"effective_end_date",
		"tags",
		"change_indicator",
	):
		doc.set(f, row.get(f))
	doc.is_active = 1


def _apply(plan):
	created = updated = items_created = inactivated = 0
	mat_errors = []
	n = 0
	for key, row in plan["valid"]:
		ex = plan["existing"].get(key)
		if ex is None:
			_new_offer_doc(row).insert(ignore_permissions=True)
			created += 1
		elif key in plan["update"]:
			doc = frappe.get_doc("Microsoft Offer", key)
			_apply_mutable(doc, row)
			doc.save(ignore_permissions=True)
			updated += 1
		elif not ex.is_active:
			# Reaparecio en el catalogo: reactivar.
			frappe.db.set_value("Microsoft Offer", key, "is_active", 1)
		was_missing_item = key in set(plan["items_to_create"])
		try:
			materialize_item(key)
			if was_missing_item:
				items_created += 1
		except MaterializeError as exc:
			mat_errors.append({"offer_key": key, "error": str(exc)})
		n += 1
		if n % 200 == 0:
			frappe.db.commit()

	for key in plan["to_inactivate"]:
		frappe.db.set_value("Microsoft Offer", key, "is_active", 0)
		inactivated += 1
	frappe.db.commit()
	return {
		"offers_created": created,
		"offers_updated": updated,
		"items_created": items_created,
		"offers_inactivated": inactivated,
		"materialize_errors": mat_errors,
	}


def sync_microsoft_catalog(file_path, dry_run=True):
	"""Sincroniza el catalogo Microsoft desde un .xlsx.

	dry_run=True: analiza y devuelve el resumen SIN modificar datos.
	dry_run=False: aplica (crea/actualiza catalogo, materializa Items, inactiva ausentes).

	Fail-closed ante archivo mal formado (CatalogError) o dependencias faltantes en apply.
	"""
	dry_run = bool(cint(dry_run)) if not isinstance(dry_run, bool) else dry_run
	rows, _header = read_catalog(file_path)  # CatalogError si estructura invalida
	preflight_ok = frappe.db.exists("UOM", STOCK_UOM) and frappe.db.exists("Item Group", ITEM_GROUP)
	if not dry_run:
		_assert_preflight()  # fail-closed antes de escribir

	plan = _plan(rows)
	report = {
		"dry_run": dry_run,
		"sheet": SHEET,
		"preflight_ok": bool(preflight_ok),
		"rows_read": len(rows),
		"rows_valid": len(plan["valid"]),
		"offers_new": len(plan["new"]),
		"offers_to_update": len(plan["update"]),
		"offers_unchanged": len(plan["unchanged"]),
		"offers_to_inactivate": len(plan["to_inactivate"]),
		"items_to_create": len(plan["items_to_create"]),
		"items_existing": len(plan["items_existing"]),
		"errors": plan["errors"],
	}
	if not dry_run:
		report["applied"] = _apply(plan)
	return report


def refresh_microsoft_item_names(dry_run=True):
	"""Re-aplica item_name (nuevo naming) a los Items Microsoft ya creados.

	Solo actualiza `item_name` de Items con ms_offer_key (excluye legacy). NO toca
	item_code, ms_*, offer_key, links ni metadata estandar. Devuelve estadisticas de
	longitud del nombre completo (sin capar) y conteos de actualizacion.
	"""
	dry_run = bool(cint(dry_run)) if not isinstance(dry_run, bool) else dry_run
	# Tags viven en Microsoft Offer (no en el Item); mapa offer_key -> tags para la regla Trial.
	offer_tags = dict(frappe.get_all("Microsoft Offer", fields=["name", "tags"], as_list=True))
	items = frappe.get_all(
		"Item",
		filters={"ms_offer_key": ["is", "set"]},
		fields=[
			"name",
			"item_name",
			"ms_offer_key",
			"ms_sku_title",
			"ms_term_duration",
			"ms_billing_plan",
			"ms_segment",
		],
	)
	lengths = []
	over_140 = 0
	updated = unchanged = 0
	n = 0
	for it in items:
		tags = offer_tags.get(it.ms_offer_key)
		full = build_display_name(
			it.ms_sku_title, it.ms_term_duration, it.ms_billing_plan, it.ms_segment, tags
		)
		lengths.append(len(full))
		if len(full) > 140:
			over_140 += 1
		capped = build_display_name_capped(
			it.ms_sku_title, it.ms_term_duration, it.ms_billing_plan, it.ms_segment, tags
		)
		if capped != (it.item_name or ""):
			if not dry_run:
				frappe.db.set_value("Item", it.name, "item_name", capped, update_modified=False)
			updated += 1
		else:
			unchanged += 1
		n += 1
		if not dry_run and n % 500 == 0:
			frappe.db.commit()
	if not dry_run:
		frappe.db.commit()
	lengths.sort()
	stats = {}
	if lengths:
		stats = {
			"min": lengths[0],
			"avg": round(sum(lengths) / len(lengths), 1),
			"p95": lengths[min(len(lengths) - 1, int(len(lengths) * 0.95))],
			"max": lengths[-1],
			"full_over_140": over_140,
		}
	return {
		"dry_run": dry_run,
		"items_microsoft": len(items),
		"item_name_updated": updated,
		"item_name_unchanged": unchanged,
		"full_name_length": stats,
	}


# --- Mecanismo de carga nativo (UI): wrapper whitelisted para el DocType Single ---


@frappe.whitelist()
def run_sync_from_single(dry_run=1):
	"""Ejecuta la sincronizacion usando el archivo adjunto en 'Microsoft Catalog Sync'.

	Llamado por los botones Dry Run / Aplicar del DocType Single. Solo System Manager.
	"""
	frappe.only_for("System Manager")
	dry_run = bool(cint(dry_run))
	file_url = frappe.db.get_single_value("Microsoft Catalog Sync", "catalog_file")
	if not file_url:
		frappe.throw("Adjunte el archivo .xlsx del catalogo Microsoft primero.")
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	report = sync_microsoft_catalog(file_doc.get_full_path(), dry_run=dry_run)
	single = frappe.get_single("Microsoft Catalog Sync")
	single.last_run_dry_run = 1 if dry_run else 0
	single.last_run_at = frappe.utils.now()
	single.last_result = frappe.as_json(report, indent=1)
	single.save(ignore_permissions=True)
	return report
