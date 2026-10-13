# ADR-0004: Retiro comercial vía `ms_catalog_active` y moneda predeterminada del cotizador

**Fecha:** 2026-10-13
**Status:** Aceptado
**Actualiza:** ADR-0003 (ciclo de vida del catálogo Microsoft NCE)

## Contexto

El sincronizador del catálogo Microsoft (ADR-0003) retiraba las ofertas ausentes del Excel marcando
`Item.disabled = 1`. Un Item deshabilitado **bloquea operaciones nativas sobre documentos existentes**:
`get_item_details` → `validate_end_of_life` lanza *"Item is disabled"* al convertir Quotation → Sales
Order → Sales Invoice o al facturar un compromiso vigente. Es decir, retirar un producto del catálogo
impedía **facturar ventas ya ganadas** de ese producto.

Además, en staging se observó que las cotizaciones Microsoft nuevas tomaban `Standard Selling` (MXN),
cuando el ~98.7 % del licenciamiento NCE (evidencia: 1 041 CFDI) se factura en **USD**.

## Decisión

### 1. Retiro comercial con `ms_catalog_active`, no con `disabled`
- Custom Field `ms_catalog_active` en `Item` (Check, **default 1**, por fixtures).
- Presente en catálogo → `ms_catalog_active = 1`, `disabled = 0`. Ausente → `ms_catalog_active = 0`,
  **`disabled = 0`** (el Item permanece operable). Reaparición → `1`.
- El selector del cotizador y el guard de alta (`_load_valid_item`) exigen `ms_catalog_active = 1`, de
  modo que una oferta retirada **no puede añadirse** a una cotización (ni por UI ni por llamada directa),
  pero los flujos nativos de conversión/facturación —que no pasan por el cotizador— siguen funcionando.
- Se conserva el cierre de vigencias del precio de compra y el histórico (ADR-0003).
- Los Items legacy (sin `ms_product_id`) quedan fuera del control del sincronizador.

### 2. Transición sin patches de datos
La normalización de los Items que el sincronizador anterior dejó en `disabled = 1` la realiza el **propio
Apply** del sincronizador (presentes → `disabled=0, ms_catalog_active=1`; ausentes → `disabled=0,
ms_catalog_active=0`), y el **Dry Run la reporta** (`items_needing_transition`) sin escribir. **Queda
prohibido** usar patches de datos en `acti_customs` y ejecutar cambios automáticos de datos durante
`bench migrate`/install.

### 3. Moneda predeterminada del cotizador
- Campo `default_quote_currency` (Link→Currency, **default USD**) en el Single *Microsoft Catalog Sync*;
  helper `get_default_quote_currency()` con *fallback* USD.
- El cotizador aplica esa moneda con `frm.set_value("currency", …)` **solo** en una cotización nueva y
  **sin líneas**, reutilizando el recálculo FX nativo. No altera cotizaciones existentes ni líneas ya
  capturadas; el usuario puede cambiarla con el campo nativo.

### 4. Reporte de sincronización nativo
Dry Run y Apply presentan el resultado con `frappe.msgprint` (tarjetas + tablas acotadas); el JSON
técnico se conserva en `last_result` para auditoría.

## Consecuencias

- Retirar un producto del catálogo **ya no bloquea** la facturación de compromisos existentes.
- No hay patches de datos ni mutaciones automáticas en migrate; la transición es idempotente y explícita.
- El cotizador refleja la realidad USD del negocio sin imponer la moneda a documentos existentes.
- Pendiente (fuera de alcance): la guía `docs/usuario/catalogo-microsoft.md` aún menciona `Microsoft
  Offer`/`MS Offer Label` (deuda documental previa a ADR-0003), a limpiar por separado.

## Alternativas descartadas

- **Mantener `disabled=1` para retirar:** rechazada — rompe la facturación de ventas ganadas.
- **Patch de datos para normalizar los `disabled` heredados:** rechazada por decisión del proyecto
  (sin patches de datos); se integra en el Apply del sincronizador.
- **Lista de precios de venta paralela / moneda por línea:** fuera de alcance; la moneda es a nivel
  documento (nativo) y el precio negociado se preserva en la conversión (comportamiento nativo verificado).
