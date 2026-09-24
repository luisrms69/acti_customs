# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Claves determinísticas del catálogo Microsoft.

Dos identidades distintas para una oferta:

- **offer_key** (clave técnica/idempotencia): `ProductId|SkuId|TermDuration|BillingPlan|Segment`.
  NO usa títulos (pueden cambiar entre versiones del catálogo). En el catálogo actual estas
  5 componentes dan 3,932 valores únicos para las 3,932 ofertas.
- **item_code** (código legible del Item ERPNext):
  `MS-<ProductId>-<SkuId>-<TermDuration>-<BillingPlan>-<Segment>`.

Ambas se derivan de las MISMAS 5 componentes, de forma determinística. Funciones puras
(sin frappe) para poder testearlas y reutilizarlas desde la futura rutina de sincronizacion.
"""

# Componentes que forman la identidad tecnica, en orden.
KEY_COMPONENTS = ("product_id", "sku_id", "term_duration", "billing_plan", "segment")

OFFER_KEY_SEP = "|"
ITEM_CODE_SEP = "-"
ITEM_CODE_PREFIX = "MS"

# Longitud maxima de Item.item_code (== columna name, varchar(140)) en este ERPNext.
ITEM_CODE_MAXLEN = 140


class OfferKeyError(ValueError):
	"""Una componente de la identidad falta o contiene un separador reservado."""


def _norm(value):
	return "" if value is None else str(value).strip()


def _components(product_id, sku_id, term_duration, billing_plan, segment):
	return [_norm(product_id), _norm(sku_id), _norm(term_duration), _norm(billing_plan), _norm(segment)]


def validate_components(product_id, sku_id, term_duration, billing_plan, segment):
	"""Valida que las 5 componentes sean utilizables en una clave determinística.

	Lanza OfferKeyError si alguna esta vacia o contiene un separador reservado
	(`|` o `-`), lo que romperia la unicidad/parseo de la clave.
	"""
	comps = _components(product_id, sku_id, term_duration, billing_plan, segment)
	for name, val in zip(KEY_COMPONENTS, comps, strict=True):
		if not val:
			raise OfferKeyError(f"Componente de identidad vacia: {name}")
		if OFFER_KEY_SEP in val or ITEM_CODE_SEP in val:
			raise OfferKeyError(
				f"Componente {name}={val!r} contiene un separador reservado ('{OFFER_KEY_SEP}' o '{ITEM_CODE_SEP}')"
			)
	return comps


def build_offer_key(product_id, sku_id, term_duration, billing_plan, segment):
	comps = validate_components(product_id, sku_id, term_duration, billing_plan, segment)
	return OFFER_KEY_SEP.join(comps)


def build_item_code(product_id, sku_id, term_duration, billing_plan, segment):
	comps = validate_components(product_id, sku_id, term_duration, billing_plan, segment)
	code = ITEM_CODE_PREFIX + ITEM_CODE_SEP + ITEM_CODE_SEP.join(comps)
	if len(code) > ITEM_CODE_MAXLEN:
		raise OfferKeyError(f"item_code excede {ITEM_CODE_MAXLEN} caracteres: {len(code)}")
	return code


# ---------------------------------------------------------------------------
# item_name: display comercial con los SEIS atributos.
# ProductTitle/SkuTitle NO son identidad tecnica (Microsoft puede cambiarlos) pero
# deben mostrarse. Item.item_name es varchar(140); ~31% de las ofertas exceden 140
# con los seis atributos completos. El nombre capado abrevia SOLO los dos titulos
# (nunca las 4 dimensiones cortas), y los titulos completos se conservan en
# ms_product_title / ms_sku_title y en Microsoft Offer.
# ---------------------------------------------------------------------------

NAME_SEP = " | "
ITEM_NAME_MAXLEN = 140
_ELLIPSIS = "…"  # '...'


def build_item_name(product_title, product_id, sku_title, term_duration, billing_plan, segment):
	"""Display completo (sin capar) con los seis atributos, en orden."""
	parts = [
		_norm(product_title),
		_norm(product_id),
		_norm(sku_title),
		_norm(term_duration),
		_norm(billing_plan),
		_norm(segment),
	]
	for name, val in zip(
		("product_title", "product_id", "sku_title", "term_duration", "billing_plan", "segment"),
		parts,
		strict=True,
	):
		if not val:
			raise OfferKeyError(f"Componente de item_name vacia: {name}")
	return NAME_SEP.join(parts)


def _shrink(text, budget):
	if budget <= 0:
		return ""
	if len(text) <= budget:
		return text
	if budget <= 1:
		return text[:budget]
	return text[: budget - 1] + _ELLIPSIS


def build_item_name_capped(
	product_title, product_id, sku_title, term_duration, billing_plan, segment, maxlen=ITEM_NAME_MAXLEN
):
	"""item_name garantizado <= maxlen conservando los seis atributos.

	Solo se abrevian los dos titulos (ProductTitle/SkuTitle) y de forma equilibrada;
	ProductId/TermDuration/BillingPlan/Segment quedan siempre intactos. Los titulos
	completos se conservan aparte (ms_product_title/ms_sku_title, Microsoft Offer).
	"""
	full = build_item_name(product_title, product_id, sku_title, term_duration, billing_plan, segment)
	if len(full) <= maxlen:
		return full
	pt, sk = _norm(product_title), _norm(sku_title)
	# Longitud fija: las 4 dimensiones cortas + los 5 separadores.
	fixed = (
		len(_norm(product_id)) + len(_norm(term_duration)) + len(_norm(billing_plan)) + len(_norm(segment))
	)
	fixed += 5 * len(NAME_SEP)
	budget = maxlen - fixed  # espacio total para los dos titulos
	half = budget // 2
	pt_c = _shrink(pt, half)
	sk_c = _shrink(sk, budget - len(pt_c))
	return NAME_SEP.join(
		[pt_c, _norm(product_id), sk_c, _norm(term_duration), _norm(billing_plan), _norm(segment)]
	)
