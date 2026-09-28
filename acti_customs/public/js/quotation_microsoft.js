// Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
// For license information, please see license.txt
//
// "Cotizador Microsoft" en Quotation (Draft): dialogo que resuelve progresivamente una oferta del
// catalogo Microsoft (Microsoft Offer) permitiendo cambiar selecciones anteriores, y agrega el Item
// Microsoft YA existente a uno de dos destinos MUTUAMENTE EXCLUYENTES:
//   - "Agregar a cotización": linea Quotation Item con rate calculado (venta, con margen).
//   - "Agregar como costo":   fila en la tabla required_items de la propuesta (item/qty/uom).
// No crea Items ni toca el catalogo. El costo economico lo resuelve erpnext_proposals (fuente unica).
//
// Flujo: al abrir se ejecuta step() (resolve_path) -> se piden solo las decisiones ambiguas y se
// autoseleccionan las unicas hasta resolver UNA oferta -> recien entonces se muestran cantidad/margen,
// el resumen y las dos acciones finales. Antes de resolver, esos elementos permanecen ocultos.

/* global acti_customs */

frappe.provide("acti_customs.ms");

acti_customs.ms.open_dialog = function (frm) {
	const VISIBLE = ["product_title", "sku_title", "term_duration", "billing_plan", "segment"];
	const LABELS = {
		product_title: __("Producto"),
		sku_title: __("SKU"),
		term_duration: __("Compromiso"),
		billing_plan: __("Facturación"),
		segment: __("Segmento"),
	};
	const DETAIL_FIELDS = [
		"detalle_sb",
		"qty",
		"margin_pct",
		"acciones_sb",
		"btn_sale",
		"btn_cost",
	];
	const cur = frm.doc.currency;
	const is_new = frm.is_new(); // Quotation sin persistir: preview con contexto del form + alta nativa del 1er item
	let selected = {};
	let resolved = null;

	const fields = [];
	VISIBLE.forEach((f) => {
		fields.push({ fieldtype: "Select", fieldname: "sel_" + f, label: LABELS[f], options: [] });
	});
	fields.push({
		fieldtype: "Section Break",
		fieldname: "detalle_sb",
		label: __("Cantidad y margen"),
	});
	// Cantidad: Int (default visible 1). El problema real de Int es que Frappe deja teclear "3.5" y
	// luego lo TRUNCA a 3; la solución es impedir desde el input la captura de "." "," y no-dígitos
	// (ver wire de sanitización del input más abajo), NO cambiar de tipo. No se toca la UOM E48.
	fields.push({
		fieldtype: "Int",
		fieldname: "qty",
		label: __("Cantidad"),
		default: 1,
		description: __("Solo enteros positivos (sin fracciones)"),
	});
	fields.push({ fieldtype: "Column Break" });
	fields.push({
		fieldtype: "Float",
		fieldname: "margin_pct",
		label: __("Margen %"),
		default: 20,
		description: __("Solo aplica a 'Agregar a cotización'"),
	});
	fields.push({ fieldtype: "Section Break" });
	fields.push({ fieldtype: "HTML", fieldname: "preview" });
	fields.push({ fieldtype: "Section Break", fieldname: "acciones_sb" });
	fields.push({
		fieldtype: "Button",
		fieldname: "btn_sale",
		label: __("Agregar a cotización"),
		click: () => do_add("sale"),
	});
	fields.push({ fieldtype: "Column Break" });
	fields.push({
		fieldtype: "Button",
		fieldname: "btn_cost",
		label: __("Agregar como costo"),
		click: () => do_add("cost"),
	});

	const d = new frappe.ui.Dialog({ title: __("Cotizador Microsoft"), fields: fields });

	const fmt = (v) => format_currency(flt(v), cur);

	// Validación de cantidad: entero positivo. Devuelve un mensaje de error o "" si es válida.
	// NO coerciona el valor (no convierte 3.5 en 3): solo diagnostica para avisar/bloquear.
	const qty_error = () => {
		const q = flt(d.get_value("qty"));
		if (!(q > 0)) return __("La cantidad debe ser mayor a 0.");
		if (q % 1 !== 0)
			return __(
				"Las licencias Microsoft no admiten cantidades fraccionarias; use un número entero."
			);
		return "";
	};

	// Muestra u oculta el bloque de detalle (cantidad/margen/resumen/acciones). Antes de resolver una
	// oferta exacta, todo esto permanece oculto.
	const show_detail = (on) => {
		DETAIL_FIELDS.forEach((fn) => d.set_df_property(fn, "hidden", on ? 0 : 1));
		// "Agregar como costo" (required_items) queda FUERA DE ALCANCE en Quotation nueva por ahora:
		// se oculta. En Quotation existente se muestra igual que en v0.3.0.
		if (on && is_new) d.set_df_property("btn_cost", "hidden", 1);
		if (!on) d.fields_dict.preview.$wrapper.empty();
	};

	const render_selects = (steps) => {
		const byField = {};
		(steps || []).forEach((s) => (byField[s.field] = s));
		VISIBLE.forEach((f) => {
			const s = byField[f];
			if (!s) {
				d.set_df_property("sel_" + f, "hidden", 1);
				return;
			}
			const opts = [{ value: "", label: __("-- elegir --") }].concat(
				s.options.map((o) => ({ value: o.value, label: o.label }))
			);
			d.set_df_property("sel_" + f, "options", opts);
			d.set_df_property("sel_" + f, "hidden", 0);
			d.fields_dict["sel_" + f].set_value(s.value || "");
		});
	};

	const render_preview = () => {
		if (!resolved) return;
		const qerr = qty_error();
		if (qerr) {
			// Cantidad inválida: mostrar aviso en el resumen y NO calcular precio (no coerciona el valor).
			d.fields_dict.preview.$wrapper.html(
				`<div class='text-danger'>${frappe.utils.escape_html(qerr)}</div>`
			);
			return;
		}
		frappe
			.call({
				method: "acti_customs.acti_customizations.microsoft.quoter.get_price_preview",
				args: {
					offer_key: resolved.offer_key,
					qty: d.get_value("qty"),
					margin_pct: d.get_value("margin_pct"),
					// Persistida → el backend usa la BD; nueva/sin guardar → usa este contexto del formulario.
					quotation: frm.doc.name,
					company: frm.doc.company,
					currency: frm.doc.currency,
					transaction_date: frm.doc.transaction_date,
				},
			})
			.then((r) => {
				const s = r.message;
				if (!s) return;
				const row = (k, v) =>
					`<tr><td class='text-muted'>${k}</td><td style='text-align:right'><b>${v}</b></td></tr>`;
				const rows = [row(__("Nombre"), frappe.utils.escape_html(s.display))];
				if (s.compromiso)
					rows.push(row(__("Compromiso"), frappe.utils.escape_html(s.compromiso)));
				// Trial: facturacion vacia -> no se muestra la fila "Facturación: None".
				if (s.facturacion)
					rows.push(row(__("Facturación"), frappe.utils.escape_html(s.facturacion)));
				rows.push(row(__("Segmento"), frappe.utils.escape_html(s.segment)));
				rows.push(row(__("Cantidad"), flt(s.qty)));
				rows.push(row(__("Costo unitario"), fmt(s.cost_unit)));
				rows.push(row(__("Margen"), flt(s.margin_pct) + "%"));
				rows.push(row(__("Precio unitario"), fmt(s.price_unit)));
				rows.push(row(__("Importe"), fmt(s.amount)));
				d.fields_dict.preview.$wrapper.html(
					`<table class='table table-bordered' style='margin-top:8px'>${rows.join(
						""
					)}</table>
					 <div class='text-muted small'>${__(
							"'Agregar como costo' usa Item y cantidad; el costo lo resuelve la propuesta."
						)}</div>`
				);
			});
	};

	const step = () => {
		frappe
			.call({
				method: "acti_customs.acti_customizations.microsoft.quoter.get_selection_path",
				args: { selected: JSON.stringify(selected) },
			})
			.then((r) => {
				const msg = r.message || {};
				render_selects(msg.steps || []);
				selected = msg.selected || selected;
				if (msg.error) {
					resolved = null;
					show_detail(false);
					d.fields_dict.preview.$wrapper.html(
						`<div class='text-muted'>${frappe.utils.escape_html(msg.error)}</div>`
					);
					return;
				}
				if (msg.resolved) {
					resolved = msg.resolved;
					show_detail(true);
					render_preview();
				} else {
					resolved = null;
					show_detail(false);
				}
			});
	};

	const on_change = (changed) => {
		// Reconstruye la seleccion hasta la dimension cambiada (inclusive) y descarta las posteriores.
		const newsel = {};
		for (const f of VISIBLE) {
			const val = d.get_value("sel_" + f);
			if (val) newsel[f] = val;
			if (f === changed) break;
		}
		selected = newsel;
		step();
	};

	function do_add(destino) {
		if (!resolved) return;
		// Bloqueo de fracciones ANTES de llamar al backend: aviso y no se agrega (venta ni costo).
		const qerr = qty_error();
		if (qerr) {
			frappe.msgprint({ title: __("Cantidad inválida"), message: qerr, indicator: "red" });
			return;
		}
		const qty = d.get_value("qty");
		const offer_key = resolved.offer_key;
		const M = "acti_customs.acti_customizations.microsoft.quoter.";

		// "Agregar como costo": v0.3.0 en Quotation existente; FUERA DE ALCANCE (oculto) en Quotation nueva.
		if (destino === "cost") {
			if (is_new) return; // botón oculto en nueva; guard defensivo
			frappe
				.call({
					method: M + "add_license_as_cost",
					args: { quotation: frm.doc.name, offer_key, qty },
					freeze: true,
					freeze_message: __("Agregando..."),
				})
				.then((r) => {
					if (r.message) {
						d.hide();
						frappe.show_alert({
							message: __("Agregado como costo: {0}", [resolved.display]),
							indicator: "green",
						});
						frm.reload_doc();
					}
				});
			return;
		}

		// "Agregar a cotización" en Quotation EXISTENTE: v0.3.0 intacto (server-side, guarda y recarga).
		if (!is_new) {
			frappe
				.call({
					method: M + "add_license_to_quotation",
					args: {
						quotation: frm.doc.name,
						offer_key,
						qty,
						margin_pct: d.get_value("margin_pct"),
					},
					freeze: true,
					freeze_message: __("Agregando..."),
				})
				.then((r) => {
					if (r.message) {
						d.hide();
						frappe.show_alert({
							message: __("Agregado a cotización: {0}", [resolved.display]),
							indicator: "green",
						});
						frm.reload_doc();
					}
				});
			return;
		}

		// "Agregar a cotización" en Quotation NUEVA (sin persistir): alta NATIVA del primer item.
		// (a) rate lo calcula el MISMO preview con el contexto del formulario (no se duplica economía).
		frappe
			.call({
				method: M + "get_price_preview",
				args: {
					offer_key,
					qty,
					margin_pct: d.get_value("margin_pct"),
					company: frm.doc.company,
					currency: frm.doc.currency,
					transaction_date: frm.doc.transaction_date,
				},
			})
			.then((r) => {
				const s = r.message;
				if (!s) return;
				// (b) REUTILIZAR la fila vacía inicial que el grid auto-agrega en un doc nuevo, en vez de
				//     crear una segunda. Criterio ESTRICTO de "fila vacía inicial" (confirmado en runtime):
				//     __islocal && sin item_code && qty 0 && rate 0. NUNCA reutiliza una fila con item_code
				//     ni con qty/rate ya capturados. Si no hay ninguna que cumpla EXACTAMENTE, add_child.
				//     (c) trigger NATIVO item_code y ESPERAR: get_item_details completa item_name/description/
				//     UOM/conversion/cuentas/price list/impuestos. (e) DESPUÉS qty y rate (el rate manual
				//     sobrevive al price_list_rate). (f) recalc nativo vía set_value + refresh. (g) sin guardar.
				let row = (frm.doc.items || []).find(
					(it) => it.__islocal && !it.item_code && !flt(it.qty) && !flt(it.rate)
				);
				if (row) {
					row.item_code = s.item; // fila vacía inicial reutilizada
				} else {
					row = frm.add_child("items", { item_code: s.item });
				}
				frm.script_manager.trigger("item_code", row.doctype, row.name).then(() => {
					frappe.model.set_value(row.doctype, row.name, "qty", s.qty);
					frappe.model.set_value(row.doctype, row.name, "rate", s.price_unit);
					frm.refresh_field("items");
					d.hide();
					frappe.show_alert({
						message: __("Agregado a cotización: {0}", [resolved.display]),
						indicator: "green",
					});
				});
			});
	}

	d.show();

	// Wire de cambios POR DELEGACIÓN sobre $wrapper (existe siempre, tolerante a re-render del control).
	VISIBLE.forEach((f) => {
		d.fields_dict["sel_" + f].$wrapper.on("change", "select", () => on_change(f));
	});
	d.fields_dict.qty.$wrapper.on("change", "input", render_preview);
	d.fields_dict.margin_pct.$wrapper.on("change", "input", render_preview);

	// Cantidad: impedir DESDE EL INPUT capturar "." "," "e" "-" "+" o cualquier no-dígito, para que
	// "3.5" NUNCA llegue a Frappe a truncarse a 3. keypress bloquea el caracter; input sanea pegado.
	const $qty = d.fields_dict.qty.$input;
	$qty.on("keypress", (e) => {
		if (e.key && e.key.length === 1 && !/[0-9]/.test(e.key)) e.preventDefault();
	});
	$qty.on("input", () => {
		const raw = $qty.val() || "";
		const clean = raw.replace(/[^0-9]/g, "");
		if (clean !== raw) $qty.val(clean); // conserva solo dígitos; no permite fracciones
	});

	// Estado inicial: oculta detalle/acciones y ejecuta de inmediato el primer paso del selector.
	show_detail(false);
	step();
};

// Estado "Borrador" del workflow de propuestas (erpnext_proposals). En ese workflow es el ÚNICO
// estado con docstatus=0; los demás son docstatus=1. El chequeo de docstatus ya garantiza Borrador;
// se valida además el estado explícito como salvaguarda, con fallback para Quotations sin workflow.
const DRAFT_WORKFLOW_STATE = "Borrador";

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		const is_draft = frm.doc.docstatus === 0;
		const ws = frm.doc.workflow_state;
		const in_borrador = !ws || ws === DRAFT_WORKFLOW_STATE;
		if (is_draft && in_borrador) {
			frm.add_custom_button(__("Cotizador Microsoft"), () =>
				acti_customs.ms.open_dialog(frm)
			);
		}
	},
});
