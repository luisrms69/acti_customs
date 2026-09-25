# Cotizador Microsoft — agregar licencias a una Quotation

Esta guía describe cómo agregar licencias del catálogo Microsoft a una cotización usando el
**Cotizador Microsoft**. Las licencias deben estar previamente cargadas (ver
[Catálogo Microsoft](catalogo-microsoft.md)); el cotizador solo selecciona ofertas existentes,
no crea Items ni modifica el catálogo.

## Dónde aparece

En una **Quotation guardada y en estado Borrador**, aparece el botón **Cotizador Microsoft**.
No aparece en cotizaciones nuevas sin guardar ni en cotizaciones ya enviadas/aprobadas.

## Seleccionar la licencia

Al abrir el cotizador se resuelve la oferta paso a paso:

`Producto → SKU → Compromiso → Facturación → Segmento`

- Cuando una dimensión tiene una sola opción posible, se **autoselecciona**.
- Solo se piden las decisiones **ambiguas** (con varias opciones).
- Puede **cambiarse una decisión anterior**; las posteriores se recalculan automáticamente.
- Las licencias de prueba se muestran como **"Prueba 1 mes"** (sin fila de facturación).

Cuando queda **una sola oferta**, se habilitan la cantidad, el margen y el resumen
(Costo / Precio / Importe en formato moneda).

## Dos destinos (excluyentes por acción)

### Agregar a cotización
La licencia se **vende** al cliente: se agrega como línea normal de la cotización
(`Quotation Item`) con la cantidad indicada y el precio de venta (calculado con el margen).

### Agregar como costo
La licencia es un **insumo** para prestar el servicio y **no** debe aparecer como línea comercial:
se agrega a la tabla de **Items requeridos** de la propuesta (Item + cantidad). El costo y su
efecto en el análisis económico los calcula la propia propuesta.

> Cada botón agrega la licencia a **un solo** destino. Si una misma licencia se necesita como
> venta y como costo, se ejecutan las dos acciones por separado.

## Notas

- El cotizador **no** crea Items nuevos ni modifica precios/costos del catálogo.
- "Agregar como costo" requiere que la cotización sea una propuesta con tabla de Items requeridos;
  si no lo es, la acción se detiene con un mensaje claro.
