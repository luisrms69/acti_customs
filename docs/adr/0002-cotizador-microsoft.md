# ADR-0002: Cotizador Microsoft en Quotation — dos destinos, costo por fuente única

**Fecha:** 2026-09-25
**Status:** Aceptado

## Contexto

Sobre el catálogo ya materializado ([[ADR-0001]]: `Microsoft Offer` → Items), se requiere
seleccionar una licencia Microsoft desde una Quotation en borrador y agregarla, resolviendo la
oferta exacta por sus atributos comerciales. Existen dos usos distintos de una misma licencia:

1. **Se vende/factura directamente** al cliente.
2. **Es un insumo (costo)** para prestar un servicio, y no debe aparecer como línea comercial.

## Decisión

1. **Selector server-side** (`resolve_path`): resolución progresiva sobre
   `Producto → SKU → Compromiso → Facturación → Segmento`, autoseleccionando dimensiones con una
   sola opción y pidiendo solo las ambiguas, hasta resolver **una** `Microsoft Offer` activa,
   vigente y con Item. Permite cambiar decisiones anteriores (limpia y recalcula dependientes).
   La UI (`doctype_js` en Quotation) es solo presentación; la lógica vive en el servidor.

2. **Dos destinos MUTUAMENTE EXCLUYENTES por acción:**
   - **Agregar a cotización** (`add_license_to_quotation`): agrega el Item existente a
     `Quotation.items` con `qty` y `rate` de venta (`ROUNDUP(costo/(1-margen), 2)`; costo =
     `UnitPrice`, o `UnitPrice/12` si `P1Y+Monthly`; Trial = 0). No toca `required_items`.
   - **Agregar como costo** (`add_license_as_cost`): agrega el Item existente a
     `Quotation.required_items` con **solo** `item`/`qty`/`uom`. No crea `Quotation Item`.

   Cada acción del usuario escribe en **una sola** tabla. No hay caso que escriba en ambas.

3. **Costo por fuente única — responsabilidad de `erpnext_proposals`.** `acti_customs` **no**
   resuelve costo económico ni escribe `frozen_cost_rate`, `frozen_cost_source`,
   `economic_behavior`, `cost_locked` ni ninguna metadata económica. Tras el `save()` normal de
   Frappe, `erpnext_proposals` procesa el documento con sus propios hooks y materializa el costo
   desde su fuente genérica (`resolve_external_cost`). `acti_customs` solo agrega el Item a la lista.

4. **Caso mixto permitido.** La misma licencia puede existir en `items` y en `required_items` si el
   usuario ejecuta deliberadamente las dos acciones (propósitos/cantidades distintas). **No** se
   añade un guard global de unicidad entre tablas.

5. **Visibilidad:** el botón aparece solo en Quotation guardada con `docstatus == 0` (y
   `workflow_state == "Borrador"` cuando ese workflow existe; fallback a docstatus para sites sin él).

## Restricciones asumidas

- **No se modifica `erpnext_proposals`** (ni su schema, hooks, clase override o análisis económico),
  **ni core Frappe/ERPNext**, ni el catálogo/Items de [[ADR-0001]]. Sin Property Setter, sin Item Price.
- Integración **aditiva**: `doctype_js` convive con el de `erpnext_proposals`; sin override de
  Quotation, sin `doc_events`, sin monkeypatches.
- **Fail-closed sin `erpnext_proposals`:** si la Quotation no tiene la tabla `required_items`,
  "Agregar como costo" aborta con error claro; no se modifica ERPNext para compensarlo.

## Fuera de alcance

- Resolver el costo cuando el Item Microsoft no tiene costo en la fuente genérica (hoy resuelve
  `sin_costo = 0`). Es responsabilidad de `erpnext_proposals` / del costeo del Item; **tema
  independiente**, fuera de este bloque.
- Recurrencia / suscripción de licencias.

## Consecuencias

- El análisis económico de `erpnext_proposals` reconoce las filas `required_items` agregadas y las
  costea con su propia lógica, sin acoplamiento desde `acti_customs`.
- La separación venta/costo es explícita y auditable por acción.
