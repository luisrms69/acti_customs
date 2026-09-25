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


# ---------------------------------------------------------------------------
# item_name definitivo (display): <SkuTitle> | <compromiso> | <facturacion> | <segmento>
# NO usa ProductTitle/ProductId. La representacion completa de 6 atributos queda en
# ms_offer_label (build_item_name). Los valores no mapeados se conservan crudos
# (deterministico), no se inventan.
# ---------------------------------------------------------------------------

FRIENDLY_TERM = {"P1M": "1 mes", "P1Y": "1 año", "P3Y": "3 años"}
FRIENDLY_BILLING = {"Monthly": "mensual", "Annual": "anual", "Triennial": "cada 3 años"}
DISPLAY_SEP = " | "


def friendly_term(value):
	v = _norm(value)
	return FRIENDLY_TERM.get(v, v)


def friendly_billing(value):
	v = _norm(value)
	return FRIENDLY_BILLING.get(v, v)


def _is_trial(tags):
	return "trial" in _norm(tags).lower()


def is_trial_offer(term_duration, billing_plan, tags):
	"""True para el caso especial trial: P1M + BillingPlan 'None' + tag Trial."""
	return _norm(term_duration) == "P1M" and _norm(billing_plan) == "None" and _is_trial(tags)


def _tail_parts(term_duration, billing_plan, segment, tags):
	"""Componentes despues del SkuTitle. Caso especial P1M + None + Trial: etiqueta
	combinada 'Prueba 1 mes' (sin componente de facturacion 'None')."""
	if _norm(term_duration) == "P1M" and _norm(billing_plan) == "None" and _is_trial(tags):
		return ["Prueba 1 mes", _norm(segment)]
	return [friendly_term(term_duration), friendly_billing(billing_plan), _norm(segment)]


def build_display_name(sku_title, term_duration, billing_plan, segment, tags=None):
	"""Display completo (sin capar): SkuTitle | compromiso | facturacion | segmento.

	Excepcion (validada por Tags): P1M + BillingPlan 'None' + Trial ->
	'SkuTitle | Prueba 1 mes | segmento' (no se muestra 'None').
	"""
	return DISPLAY_SEP.join([_norm(sku_title), *_tail_parts(term_duration, billing_plan, segment, tags)])


def _middle_trunc(text, budget):
	"""Trunca en el MEDIO conservando inicio y fin (mas informativo)."""
	if budget <= 0:
		return ""
	if len(text) <= budget:
		return text
	if budget <= len(_ELLIPSIS):
		return text[:budget]
	keep = budget - len(_ELLIPSIS)
	head = (keep + 1) // 2
	tail = keep - head
	return text[:head] + _ELLIPSIS + (text[-tail:] if tail else "")


def build_display_name_capped(
	sku_title, term_duration, billing_plan, segment, tags=None, maxlen=ITEM_NAME_MAXLEN
):
	"""item_name <= maxlen; abrevia SOLO el SkuTitle (truncado en medio).

	Los componentes que siguen al SkuTitle quedan siempre completos. El SkuTitle completo
	permanece en ms_sku_title y en ms_offer_label.
	"""
	full = build_display_name(sku_title, term_duration, billing_plan, segment, tags)
	if len(full) <= maxlen:
		return full
	tail = _tail_parts(term_duration, billing_plan, segment, tags)
	fixed = sum(len(t) for t in tail) + len(tail) * len(DISPLAY_SEP)
	sku = _middle_trunc(_norm(sku_title), maxlen - fixed)
	return DISPLAY_SEP.join([sku, *tail])
