# CONTINUITY.md — acti_customs

> Solo para recuperación de contexto de sesión. No es plan, backlog ni documentación.

## Estado actual

- **Bloque 1 — Catálogo Microsoft (Excel → Microsoft Offer → Items):** implementado y validado.
  - DocType `Microsoft Offer` (identidad `offer_key`), DocType Single `Microsoft Catalog Sync`
    (Dry Run / Aplicar), Custom Fields `ms_*` en Item (incl. `ms_offer_label`).
  - Materializador `materialize_item` (idempotente por `offer_key`) y sincronizador
    `sync_microsoft_catalog` (dry-run/apply, inactivación sin borrado, preflight fiscal fail-closed).
  - Naming `SkuTitle | compromiso | facturación | segmento`; Trials `Prueba 1 mes`.
  - Sin modificación de core/schema estándar. Tests en verde.
- **Versión:** 0.1.0.

## En curso / siguiente

- Rama `feat/microsoft-offer-catalog` en revisión hacia PR contra `version-16`.

## Fuera de alcance (etapas posteriores)

- Recurrencia / suscripción de licencias.
- Selector/cotizador Microsoft dentro de Quotation (Bloque 2).
