# Changelog — acti_customs

## [0.4.2] — 2026-10-13

### Fixed
- **Microsoft Catalog Sync — el reporte de Dry Run/Apply no se mostraba** (ni mensaje ni error). El
  helper de presentación era una función top-level "suelta" y el `.catch` del handler tragaba en
  silencio cualquier excepción. Se expone el helper bajo el namespace `acti_customs.ms_catalog_sync`
  (alcanzable desde el controlador en el bundle del desk, como `quotation_microsoft.js` con
  `acti_customs.ms`) y el handler ahora **siempre** muestra un `frappe.msgprint`: el reporte en éxito,
  un aviso en respuesta vacía y un mensaje de error comprensible si el backend falla. `render_report`
  es defensivo (nunca lanza). **Solo presentación**: sin cambios en el sincronizador ni sus datos.
  Pruebas del **handler real** de Dry Run (éxito/vacío/error) además de `render_report` aislado.

## [0.4.1] — 2026-10-13

### Fixed
- **Microsoft Catalog Sync — "Error in Template" en el texto de ayuda.** El campo HTML `intro` del Single
  encerraba el nombre de la lista entre comillas simples (`'Microsoft NCE - Compra'`). El motor de
  plantillas de Frappe (`microtemplate.js`) solo escapa la primera comilla simple de cada segmento, así
  que el par rompía el literal generado y el render del formulario/Dry Run fallaba con *Error in Template*
  (`microtemplate.js:91`). Se cambió a comillas dobles. **Solo presentación**: sin cambios en el
  sincronizador, sus datos ni la lógica del catálogo. Incluye test de regresión que reproduce el render
  real (porta el algoritmo de `microtemplate.js` y compila el cuerpo con Node).

## [0.4.0] — 2026-10-13

### Added
- **Moneda predeterminada del cotizador Microsoft.** Nuevo campo `default_quote_currency` (por defecto
  **USD**) en el Single *Microsoft Catalog Sync*. Al abrir el cotizador en una cotización **nueva y sin
  líneas** se aplica esa moneda con el mecanismo nativo de ERPNext (recalcula FX e importes). Respeta
  cotizaciones existentes y líneas ya capturadas; el usuario puede cambiarla con el campo de moneda
  nativo. Ver ADR-0004 y `docs/usuario/cotizador-microsoft.md`.
- **Retiro comercial de ofertas vía `ms_catalog_active`** (Custom Field en `Item`, default 1). Una oferta
  que desaparece del Excel se marca `ms_catalog_active = 0`: desaparece del cotizador pero **su Item
  sigue habilitado** para completar operaciones en documentos existentes. Reaparición → vuelve a 1.
- **Reporte de sincronización nativo.** Dry Run y Apply muestran el resultado con `frappe.msgprint`
  (tarjetas de conteos + tablas acotadas de novedades y errores); el JSON técnico se conserva en
  `last_result`. El reporte incluye `items_reactivated`, `items_needing_transition` e `items_to_retire`.

### Changed
- **El sincronizador ya NO usa `Item.disabled` para retirar ofertas Microsoft.** El `disabled=1` previo
  bloqueaba conversiones/facturación de documentos existentes (vía `validate_end_of_life`). El retiro
  ahora es `ms_catalog_active=0` + `disabled=0`, cerrando la vigencia del precio de compra sin borrar
  histórico. El filtro del cotizador exige `ms_catalog_active=1` y el guard de alta rechaza ofertas
  retiradas, sin afectar la facturación de compromisos vigentes.

### Migration
- La transición de Items que el sincronizador anterior dejó en `disabled=1` la realiza el **propio
  Apply del sincronizador** (presentes → `disabled=0, ms_catalog_active=1`; ausentes → `disabled=0,
  ms_catalog_active=0`), reportada en Dry Run como `items_needing_transition`. **No se usan patches de
  datos** ni cambios automáticos durante `bench migrate`/install.

### Notes
- Sin cambios en core/schema de Frappe/ERPNext. Custom Field por fixtures; nada de Property Setters.
  Pruebas: `test_sync` 20/20, `test_quoter` 43/43 en el site de tests.

## [0.3.2] — 2026-09-29

### Fixed
- **Microsoft Catalog Sync** ahora lee el archivo adjunto mediante la abstracción nativa de Frappe
  `File.get_content()` en lugar de `File.get_full_path()`. Esto lo hace compatible con almacenamiento
  externo (p. ej. `dfp_external_storage`/B2), donde el `File` no tiene una ruta local y
  `get_full_path()` fallaba con `ValidationError: Cannot access file path`. `sync_microsoft_catalog()`
  acepta ahora ruta local **o** contenido binario del `.xlsx`; Dry Run/Apply y el modelo del catálogo
  no cambian. Sin dependencia hacia `dfp_external_storage`.

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
