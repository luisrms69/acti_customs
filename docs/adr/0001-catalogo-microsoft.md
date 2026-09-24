# ADR-0001: Catálogo Microsoft — Microsoft Offer + materialización de Items

**Fecha:** 2026-09-24
**Status:** Aceptado

## Contexto

Se requiere disponer del catálogo de licencias Microsoft (precio vigente NCE) como Items
nativos de ERPNext, cargados desde el Excel oficial, para poder cotizarlos. El catálogo tiene
~3,900 ofertas y cambia con cada versión (precios, vigencias, altas/bajas). Cada oferta se
distingue por seis atributos comerciales: ProductTitle, ProductId, SkuTitle, TermDuration,
BillingPlan, Segment (más SkuId como metadata).

## Decisión

1. **Catálogo interno `Microsoft Offer`** (DocType propio de `acti_customs`) como representación
   de una oferta: conserva precio (`unit_price`), moneda, market, vigencia
   (`effective_start_date`/`effective_end_date`), `tags`, `change_indicator`, `is_active` y el
   vínculo 1:1 al Item materializado.
2. **Identidad técnica `offer_key`** = `ProductId|SkuId|TermDuration|BillingPlan|Segment`
   (es el `name` del DocType, único). NO usa títulos, que pueden cambiar entre versiones del
   catálogo. Es la clave de idempotencia.
3. **`item_code`** determinístico = `MS-<ProductId>-<SkuId>-<TermDuration>-<BillingPlan>-<Segment>`.
4. **Materializador** `materialize_item(offer)`: crea o reutiliza el Item ERPNext idempotentemente
   por `offer_key` (nunca por ProductId, nombre ni similitud); fail-closed ante inconsistencias;
   preserva Items legacy (sin `ms_offer_key`).
5. **Sincronizador** `sync_microsoft_catalog(file, dry_run)`: Dry Run (valida y reporta sin
   escribir) / Apply (UPSERT de ofertas, actualización de metadata mutable sin recrear Items,
   inactivación de ofertas ausentes sin borrarlas, materialización de Items faltantes).
6. **`item_name`** (campo estándar, ≤140): `<SkuTitle> | <compromiso> | <facturación> | <segmento>`,
   abreviando solo el SkuTitle (truncado en medio) cuando excede 140; la representación completa
   vive en `ms_offer_label` (Custom Field propio) y en los campos `ms_*`. Caso especial
   `P1M + BillingPlan None + Trial` → `Prueba 1 mes`.

## Restricciones asumidas

- **No se modifica core/metadata/schema estándar** de Frappe/ERPNext. En particular NO se amplía
  `Item.item_name` (sigue `varchar(140)`); la información completa se conserva en Custom Fields
  propios (`ms_*`).
- **`acti_customs` consume** catálogos fiscales (UOM, SAT, Item Group), **no los administra**;
  esa configuración pertenece a `facturacion_mexico`. El sincronizador hace preflight fail-closed
  si falta una dependencia.

## Fuera de alcance

- Recurrencia / suscripción de licencias (renovaciones, ciclos de facturación como documentos vivos).
- Selector/cotizador dentro de Quotation.

## Consecuencias

- Reejecutar el mismo Excel es idempotente (0 duplicados).
- Nuevas versiones del catálogo agregan ofertas/Items nuevos y actualizan precio/vigencia sin
  recrear Items existentes.
