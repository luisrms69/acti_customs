# CONTINUITY.md — acti_customs

> Solo para recuperación de contexto de sesión. No es plan, backlog ni documentación.

## Estado actual

- **Bloque 1 — Catálogo Microsoft (Excel → Microsoft Offer → Items):** implementado, liberado
  como `v0.1.0` (mergeado a `version-16`).
  - DocType `Microsoft Offer` (identidad `offer_key`), DocType Single `Microsoft Catalog Sync`
    (Dry Run / Aplicar), Custom Fields `ms_*` en Item (incl. `ms_offer_label`).
  - Materializador `materialize_item` (idempotente por `offer_key`) y sincronizador
    `sync_microsoft_catalog` (dry-run/apply, inactivación sin borrado, preflight fiscal fail-closed).
  - Naming `SkuTitle | compromiso | facturación | segmento`; Trials `Prueba 1 mes`.
- **Bloque 2 — Cotizador Microsoft en Quotation:** implementado y validado (visual en un site con
  `erpnext_proposals`). Selector progresivo (`resolve_path`) con selecciones editables; botón visible
  solo en Borrador. Dos destinos excluyentes por acción:
  - **Agregar a cotización** → `Quotation.items` (rate de venta con margen).
  - **Agregar como costo** → `required_items` (solo item/qty/uom). El costo/economía los resuelve
    `erpnext_proposals` (fuente única); `acti_customs` no escribe metadata económica. Ver ADR-0002.
  - Integración aditiva (`doctype_js`), sin override de Quotation ni cambios en core/`erpnext_proposals`.
    Fail-closed sin `erpnext_proposals`.
- **Versión:** 0.2.0.

## En curso / siguiente

- Rama `feat/microsoft-quotation-selector` en revisión hacia PR contra `version-16`.

## Fuera de alcance (etapas posteriores)

- Resolver `sin_costo = 0` de Items Microsoft en la fuente genérica de costo (responsabilidad de
  `erpnext_proposals` / costeo del Item) — tema independiente.
- Recurrencia / suscripción de licencias.
