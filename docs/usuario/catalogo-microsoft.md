# Catálogo Microsoft — carga y consulta

Esta guía describe cómo cargar el catálogo de licencias Microsoft y qué queda disponible en ERPNext.

## Cargar / actualizar el catálogo

1. Abrir **Microsoft Catalog Sync** (DocType Single de configuración).
2. Adjuntar el Excel del catálogo Microsoft (hoja `Jan_NCE_LicenseBasedPL_GA_MX`).
3. **Dry Run** — analiza el archivo **sin modificar datos** y muestra un resumen:
   filas leídas/válidas, ofertas nuevas/a actualizar/sin cambios/a inactivar, Items a crear y errores.
4. Si el Dry Run está limpio, **Aplicar catálogo** — crea/actualiza el catálogo y materializa los
   Items faltantes.

Requisitos previos (configuración fiscal, administrada por otra app): debe existir la unidad
`E48 - Servicio` y el Item Group `Licenciamiento Microsoft`. Si falta alguno, la carga se detiene
con un mensaje claro.

## Qué queda cargado

- **Microsoft Offer**: una por oferta del catálogo, con precio vigente, moneda, vigencia y vínculo
  al Item. Es una representación interna del catálogo; no se administra manualmente.
- **Item** (Item Group `Licenciamiento Microsoft`): un Item por oferta, con:
  - `item_code` = `MS-<ProductId>-<SkuId>-<TermDuration>-<BillingPlan>-<Segment>`;
  - nombre visible `SkuTitle | compromiso | facturación | segmento`
    (p. ej. `Microsoft 365 Business Premium | 1 año | mensual | Commercial`;
    para pruebas: `Visio Plan 2 | Prueba 1 mes | Commercial`);
  - campos estructurados `MS *` (Product/Sku, plazo, facturación, segmento, etc.) y la etiqueta
    comercial completa en **MS Offer Label**.

## Idempotencia

Volver a cargar el mismo Excel no crea Items nuevos ni duplicados. Un cambio de precio/vigencia
actualiza el catálogo sin recrear el Item; una oferta que desaparece del archivo se marca inactiva
sin borrar su Item.
