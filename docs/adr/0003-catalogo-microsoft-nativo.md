# ADR-0003: Catálogo Microsoft nativo — Item + Buying Item Price (sin Microsoft Offer)

**Fecha:** 2026-09-25
**Status:** Aceptado
**Supersede:** ADR-0001
**Actualiza:** ADR-0002 (fuente única de costo)

## Contexto

El Excel Microsoft NCE es el **sistema anterior** (catálogo + cotizador en hoja de cálculo) que
reemplazamos, no una base de datos a copiar campo por campo. ADR-0001 introdujo un DocType propio
`Microsoft Offer` como catálogo paralelo con `unit_price`/`currency`/vigencias, y el costo se
recalculaba en runtime desde ese `unit_price` — un **costo paralelo** fuera de ERPNext. Auditorías
posteriores confirmaron que cada oferta Microsoft
(`ProductId+SkuId+TermDuration+BillingPlan+Segment`) corresponde **1:1 a un Item** y que todo lo
económico tiene hogar nativo (Item Price). La lógica funcional del cotizador (regla `/12`, margen
bruto) es correcta y fiel al Excel; el defecto era arquitectónico.

## Decisión

1. **1 oferta Microsoft = 1 `Item` ERPNext.** Identidad = `item_code` determinista
   `MS-<ProductId>-<SkuId>-<TermDuration>-<BillingPlan>-<Segment>`. **Se elimina `Microsoft Offer`**
   (catálogo paralelo redundante).
2. **Metadata Microsoft mínima en Item** (dimensiones sin equivalente nativo, para el selector):
   `ms_product_id, ms_sku_id, ms_term_duration, ms_billing_plan, ms_segment, ms_product_title`.
   `SkuTitle→item_name`, `SkuDescription→description`, UOM→`stock_uom`. Tags → Tags nativos de Frappe.
   Se retiran: link a Microsoft Offer, `ms_offer_key` (derivable del item_code), `ms_currency`,
   `ms_market`, `ms_sku_title`, `ms_offer_label`.
3. **Costo = única verdad persistida en ERPNext `Item Price`.** Buying Price List propia de acti_customs
   **`Microsoft NCE - Compra`** (`buying=1, selling=0, currency=USD, enabled=1`), **no global** (no se
   toca `Buying Settings`). Un `Item Price` (USD, uom `E48 - Servicio`, `valid_from`/`valid_upto` =
   `EffectiveStartDate`/`EffectiveEndDate`) por Item.
4. **Regla de costo durante el sync** (no en runtime): `IF(TermDuration=P1Y AND BillingPlan=Monthly,
   UnitPrice/12, UnitPrice)`; Trial (`UnitPrice=0`) → costo 0. El resultado se persiste como
   `Item Price.price_list_rate`. **`UnitPrice` es solo input del Excel**, no se persiste como segunda
   verdad; el cotizador **no** vuelve a ejecutar `/12` ni consulta UnitPrice.
5. **`Item Default.default_price_list` (por Item + Company) → `Microsoft NCE - Compra`.** Selector
   nativo, por-ítem, no usado por el flujo buying nativo → sin efectos colaterales; permite que un
   resolver de costo genérico elija la lista correcta.
6. **Selector Microsoft consulta `Item`** (por `item_group` + campos `ms_*`), no `Microsoft Offer`.
7. **Margen de venta bruto custom mínimo:** `precio = ROUNDUP(costo / (1 − margen), 2)`. El margen
   nativo de ERPNext es markup (`plr×(1+m/100)`), semántica distinta → se mantiene la fórmula bruta.
8. **`ERP Price` del Excel NO se migra** (resultado del sistema viejo; sirve a lo sumo como referencia).
9. **`erpnext_proposals` no conoce Microsoft.** El costo económico de `required_items` (solo
   `item/qty/uom`) lo resuelve su resolver genérico multimoneda (refactor paralelo en ese repo).
   `acti_customs` **no** duplica FX ni escribe metadata económica.

## Consecuencias

- Desaparece el costo paralelo; una sola verdad de costo (Item Price USD).
- `resolve_external_cost` genérico + Item Default + FX nativo resuelven el costo por fecha/moneda
  (dependencia externa en `erpnext_proposals`, en curso).
- La reconstrucción en sites de prueba se hace **desde el Excel** (no data patch Offer→Item Price).

## Fuera de alcance

- Refactor multimoneda de `erpnext_proposals` (repo/ADR propios).
- Recurrencia/suscripción de licencias.
