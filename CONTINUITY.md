# CONTINUITY.md — acti_customs

> Solo para recuperación de contexto de sesión. No es plan, backlog ni documentación.

## Estado actual

- **Bloque 1 — Catálogo Microsoft (Excel → Items):** liberado como `v0.1.0` sobre el modelo antiguo
  (DocType `Microsoft Offer`). **Superado por el Bloque 3** (ver ADR-0003).
- **Bloque 2 — Cotizador Microsoft en Quotation:** liberado como `v0.2.0`. Selector progresivo y dos
  destinos excluyentes (venta / costo). **Base sobre la que se hizo el rework nativo.**
- **Bloque 3 — Catálogo Microsoft NATIVO (rework, ADR-0003):** implementado y validado en un site con
  `erpnext_proposals` y datos reales (3932 ofertas). Cambios estructurales:
  - **Elimina el DocType `Microsoft Offer`.** 1 oferta Microsoft = 1 `Item` ERPNext; identidad =
    `item_code` determinista `MS-<ProductId>-<SkuId>-<TermDuration>-<BillingPlan>-<Segment>`.
  - **Costo = fuente única en `Item Price` de compra** (Buying Price List `Microsoft NCE - Compra`, USD),
    con vigencias (`valid_from`/`valid_upto`). Regla `/12` aplicada en el sync (P1Y+Monthly). `ERP Price`
    del Excel se ignora. `Item Default.default_price_list` por Company (selección explícita, fail-closed).
  - **Sync idempotente** (`sync.py`): UPSERT de Item + Item Price + Item Default; ausentes → disable +
    cierre de precio (sin borrar histórico); reaparición → reactiva. Administra solo Items NCE
    (`ms_product_id` set); no toca legacy del mismo Item Group.
  - **Selector sobre `Item`** (`quoter.py`), sin `Microsoft Offer`. `product_id`/`sku_id` son
    disambiguadores internos que se difieren si son ambiguos (no congelan el GUI; las dimensiones
    visibles fijan la oferta). Margen bruto dinámico `ROUNDUP(costo/(1-margen),2)`.
  - **Costo vía frontera genérica** `erpnext_proposals.resolve_external_cost(item, uom, transaction_date,
    company, target_currency)` (Item Price + FX por fecha/moneda). `sin_costo` = fail-closed (no cotiza
    sobre 0); Trial 0 legítimo solo si el resolver devuelve `buying_item_price`. `acti_customs` NO
    reimplementa Price List/FX ni escribe economía.
  - **Cantidades enteras** en licencias: campo `Int` en el modal + bloqueo de captura/paste de fracciones
    (el input impide `.`/no-dígitos, "3.5" no llega a truncarse) + guard server-side `require_whole_qty()`.
    No se toca la UOM `E48 - Servicio` (compartida con servicios fraccionables).
  - **ADR-0003** documenta el rework y **supersede ADR-0001**; actualiza ADR-0002.
- **Versión:** 0.3.2. Tras el `v0.3.0`: `0.3.1` (fix: mostrar cotizador en cotizaciones nuevas) y
  `0.3.2` (fix: Microsoft Catalog Sync lee el archivo con `File.get_content()` en vez de
  `get_full_path()`, compatible con almacenamiento externo/B2; sin dependencia hacia `dfp_external_storage`).

- **Bloque 4 — Moneda default del cotizador + retiro vía `ms_catalog_active` (v0.4.0, ADR-0004):**
  implementado y validado en el site de tests (`test_sync` 20/20, `test_quoter` 43/43).
  - **Retiro comercial** con Custom Field `ms_catalog_active` (default 1), **no** con `Item.disabled`
    (que bloqueaba conversión/facturación de documentos existentes vía `validate_end_of_life`).
    Ausente → `ms_catalog_active=0, disabled=0` (operable) + cierre de vigencia; reaparición → 1.
    Selector y guard de alta exigen `ms_catalog_active=1`. Legacy intacto.
  - **Transición sin patches:** la normaliza el **Apply** del sync (Dry Run la reporta como
    `items_needing_transition`). **Prohibido** usar patches de datos en `acti_customs`.
  - **Moneda default** `default_quote_currency` (Single *Microsoft Catalog Sync*, default USD); el JS
    la aplica solo en Quotation nueva y sin líneas (nativo, respeta existentes).
  - **Reporte nativo** del sync vía `frappe.msgprint` (tarjetas + tablas); JSON en `last_result`.

## En curso / siguiente

- **`v0.4.0` liberado:** PR #7 merged (`5d95b72`), tag + GitHub Release `v0.4.0` publicados; rama feature
  eliminada; `/sync-check` limpio.
- **`v0.4.1` en `/ship pr`** (rama `fix/microsoft-catalog-sync-help-text` → `version-16`): fix del texto
  de ayuda `intro` del Single que rompía el render (`microtemplate.js` no escapa pares de comillas
  simples) → comillas dobles. Solo presentación; con test de regresión que reproduce el render real.
- Tras merge/release de v0.4.1: actualizar `acti_customs` en staging, `bench migrate` (previa
  verificación de la tabla huérfana `Microsoft Offer`), validar moneda/reporte, Dry Run y —con
  autorización— Apply para normalizar el catálogo.

## Fuera de alcance (etapas posteriores)

- Multi-moneda de venta más allá de lo que resuelve la frontera genérica de costo (FX nativo).
- Recurrencia / suscripción de licencias.
- Limpieza física de la tabla huérfana `tabMicrosoft Offer` (migrate eliminó la metadata del DocType;
  la tabla y sus filas quedaron huérfanas — requiere decisión/`DROP TABLE` explícito, no automático).
