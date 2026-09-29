# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Sincronización del catálogo Microsoft: Excel → Item + Item Price + Item Default (ADR-0003).

Flujo idempotente, nativo, sin `Microsoft Offer`:
  - lee/valida el Excel (fail-closed si está mal formado);
  - por cada oferta: UPSERT del Item (identidad = item_code determinista) con metadata Microsoft mínima;
  - persiste el COSTO (regla /12) como Buying Item Price USD en `Microsoft NCE - Compra`, con vigencias;
  - fija `Item Default.default_price_list` del Item para la Company;
  - ofertas ausentes: deshabilita el Item y cierra su Item Price vigente (sin borrar histórico);
  - reaparición: reactiva y reabre precio en el siguiente sync.

acti_customs CONSUME catálogos fiscales (UOM/Item Group); no los crea. El `UnitPrice` crudo es input:
NO se persiste como segunda verdad; solo el costo calculado vive en Item Price.
"""

import io

import frappe
from frappe import _
from frappe.utils import cint

from acti_customs.acti_customizations.microsoft.catalog import SHEET, CatalogError, read_catalog
from acti_customs.acti_customizations.microsoft.keys import OfferKeyError, microsoft_cost
from acti_customs.acti_customizations.microsoft.materializer import (
	ITEM_GROUP,
	STOCK_UOM,
	item_code_for,
	upsert_item,
)
from acti_customs.acti_customizations.microsoft.pricing import (
	PRICE_LIST,
	close_open_item_prices,
	ensure_price_list,
	set_item_default_price_list,
	upsert_buying_item_price,
)

VALID_SEGMENTS = ("Commercial", "Education", "Charity")


def resolve_company(explicit, companies):
	"""Company objetivo del Item Default (pura, determinista; sin selección silenciosa).

	- explícita → debe existir en el site.
	- sin explícita: 1 Company → esa; 0 → fail-closed; >1 → fail-closed (hay que especificarla).
	El default global de Frappe puede servir como valor INICIAL del campo en Microsoft Catalog Sync,
	pero NO como mecanismo para desambiguar múltiples Companies aquí.
	"""
	if explicit:
		if explicit not in companies:
			raise CatalogError(f"Company {explicit!r} no existe en el site (fail-closed).")
		return explicit
	if len(companies) == 1:
		return companies[0]
	if not companies:
		raise CatalogError("No hay Company en el site (fail-closed).")
	raise CatalogError(
		"Hay multiples Companies: especifique la Company objetivo en 'Microsoft Catalog Sync' (fail-closed)."
	)


def _resolve_company(explicit=None):
	return resolve_company(explicit, frappe.get_all("Company", pluck="name"))


def _assert_preflight():
	if not frappe.db.exists("UOM", STOCK_UOM):
		raise CatalogError(f"Falta la UOM {STOCK_UOM!r} (la administra facturacion_mexico).")
	if not frappe.db.exists("Item Group", ITEM_GROUP):
		raise CatalogError(f"Falta el Item Group {ITEM_GROUP!r}.")
	ensure_price_list()  # crea o valida (fail-closed si incompatible)


def _plan(rows):
	"""Plan de sincronización (solo lectura).

	"Gestionados por el sync" = Items del catálogo NCE, marcados por `ms_product_id` set. Los Items
	legacy/manuales que compartan el Item Group pero NO tengan `ms_product_id` quedan FUERA (no se
	cuentan ni se desactivan): el sync solo administra las ofertas Microsoft NCE.
	"""
	existing = set(
		frappe.get_all(
			"Item",
			filters={"item_group": ITEM_GROUP, "ms_product_id": ["is", "set"]},
			pluck="name",
		)
	)
	errors, valid, file_codes = [], [], set()
	for r in rows:
		if r["segment"] not in VALID_SEGMENTS:
			errors.append({"row": r["_row"], "error": f"Segment invalido: {r['segment']!r}"})
			continue
		try:
			code = item_code_for(r)
		except OfferKeyError as exc:
			errors.append({"row": r["_row"], "error": str(exc)})
			continue
		if code in file_codes:
			errors.append({"row": r["_row"], "item_code": code, "error": "item_code duplicado en el archivo"})
			continue
		file_codes.add(code)
		valid.append((code, r))

	to_disable = sorted(existing - file_codes)
	items_new = [c for c, _r in valid if c not in existing]
	items_existing = [c for c, _r in valid if c in existing]
	return {
		"valid": valid,
		"errors": errors,
		"items_new": items_new,
		"items_existing": items_existing,
		"to_disable": to_disable,
	}


def _apply(plan, company):
	created = updated = prices = defaults = disabled = 0
	errors = []
	existing_new = set(plan["items_new"])
	n = 0
	for code, r in plan["valid"]:
		try:
			was_new = code in existing_new
			upsert_item(r)
			created += 1 if was_new else 0
			updated += 0 if was_new else 1
			cost = microsoft_cost(r.get("unit_price"), r["term_duration"], r["billing_plan"])
			upsert_buying_item_price(
				code, cost, STOCK_UOM, r.get("effective_start_date"), r.get("effective_end_date")
			)
			prices += 1
			set_item_default_price_list(code, company)
			defaults += 1
		except Exception as exc:
			errors.append({"item_code": code, "error": str(exc)})
		n += 1
		if n % 200 == 0:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit -- carga masiva por lotes; commit controlado

	for code in plan["to_disable"]:
		frappe.db.set_value("Item", code, "disabled", 1)
		close_open_item_prices(code)
		disabled += 1

	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- commit final controlado del apply
	return {
		"items_created": created,
		"items_updated": updated,
		"prices_upserted": prices,
		"item_defaults_set": defaults,
		"items_disabled": disabled,
		"row_errors": errors,
	}


def sync_microsoft_catalog(file, dry_run=True, company=None):
	"""Sincroniza el catálogo Microsoft desde un .xlsx.

	`file`: ruta local (str/os.PathLike), contenido binario del .xlsx (bytes/bytearray) u
	objeto file-like. El binario se envuelve en BytesIO para openpyxl (compat. con archivos
	gestionados por Frappe/`File.get_content()`, sin depender de una ruta local).

	dry_run=True: analiza y devuelve el resumen SIN modificar datos.
	dry_run=False: aplica (Items + Item Price + Item Default; deshabilita ausentes).
	`company`: Company objetivo del Item Default (obligatoria si hay varias; ver resolve_company).
	"""
	dry_run = bool(cint(dry_run)) if not isinstance(dry_run, bool) else dry_run
	source = io.BytesIO(file) if isinstance(file, (bytes, bytearray)) else file
	rows, _header = read_catalog(source)  # CatalogError si estructura invalida
	preflight_ok = frappe.db.exists("UOM", STOCK_UOM) and frappe.db.exists("Item Group", ITEM_GROUP)
	target_company = None
	if not dry_run:
		_assert_preflight()
		target_company = _resolve_company(company)  # fail-closed si ambigua/ausente

	plan = _plan(rows)
	report = {
		"dry_run": dry_run,
		"sheet": SHEET,
		"price_list": PRICE_LIST,
		"preflight_ok": bool(preflight_ok),
		"target_company": target_company,
		"rows_read": len(rows),
		"rows_valid": len(plan["valid"]),
		"items_new": len(plan["items_new"]),
		"items_existing": len(plan["items_existing"]),
		"items_to_disable": len(plan["to_disable"]),
		"errors": plan["errors"],
	}
	if not dry_run:
		report["applied"] = _apply(plan, target_company)
	return report


@frappe.whitelist()
def run_sync_from_single(dry_run: int = 1):
	"""Ejecuta la sincronización usando el archivo y la Company de 'Microsoft Catalog Sync'. Solo System Manager."""
	frappe.only_for("System Manager")
	dry_run = bool(cint(dry_run))
	single = frappe.get_single("Microsoft Catalog Sync")
	file_url = single.catalog_file
	if not file_url:
		frappe.throw(_("Adjunte el archivo .xlsx del catalogo Microsoft primero."))
	file_doc = frappe.get_doc("File", {"file_url": file_url})
	# get_content() es la abstracción nativa de Frappe: funciona con archivos locales y con
	# almacenamiento externo (p. ej. dfp_external_storage/B2), sin exigir una ruta local.
	content = file_doc.get_content()
	report = sync_microsoft_catalog(content, dry_run=dry_run, company=single.get("target_company"))
	single.reload()
	single.last_run_dry_run = 1 if dry_run else 0
	single.last_run_at = frappe.utils.now()
	single.last_result = frappe.as_json(report, indent=1)
	single.save(ignore_permissions=True)
	return report
