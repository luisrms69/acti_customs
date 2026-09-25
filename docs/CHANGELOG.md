# Changelog — acti_customs

## [0.2.0] — 2026-09-25

### Added
- **Cotizador Microsoft** en Quotation (Borrador): selector progresivo de licencias
  (`Producto → SKU → Compromiso → Facturación → Segmento`) con autoselección, edición de
  decisiones anteriores y resumen Costo/Precio/Importe en formato moneda.
- Dos destinos mutuamente excluyentes por acción:
  - **Agregar a cotización** → línea `Quotation Item` con `rate` de venta (margen).
  - **Agregar como costo** → fila en `required_items` de la propuesta (solo item/qty/uom); el
    costo y el análisis económico los resuelve `erpnext_proposals` (fuente única).
- Ver ADR-0002 y la guía de usuario `docs/usuario/cotizador-microsoft.md`.

### Notes
- Integración aditiva (`doctype_js`), sin override de Quotation ni cambios en `erpnext_proposals`,
  core o schema. Fail-closed cuando `erpnext_proposals` no está instalado.

## [0.1.0] — 2026-09-24

### Added
- **Catálogo Microsoft**: DocType `Microsoft Offer` (identidad `offer_key`), Single
  `Microsoft Catalog Sync` (Dry Run / Aplicar), materializador idempotente `offer → Item`,
  sincronizador Excel → Offers → Items y Custom Fields `ms_*` en Item. Ver ADR-0001.

## [0.0.1] — 2026-09-22

### Added
- Scaffold inicial del app
