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
	fields.push({ fieldtype: "Float", fieldname: "qty", label: __("Cantidad"), default: 1 });
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

	// Muestra u oculta el bloque de detalle (cantidad/margen/resumen/acciones). Antes de resolver una
	// oferta exacta, todo esto permanece oculto.
	const show_detail = (on) => {
		DETAIL_FIELDS.forEach((fn) => d.set_df_property(fn, "hidden", on ? 0 : 1));
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
		frappe
			.call({
				method: "acti_customs.acti_customizations.microsoft.quoter.get_price_preview",
				args: {
					offer_key: resolved.offer_key,
					qty: d.get_value("qty"),
					margin_pct: d.get_value("margin_pct"),
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
		const qty = d.get_value("qty");
		const common = { quotation: frm.doc.name, offer_key: resolved.offer_key, qty: qty };
		let method, args, msg_ok;
		if (destino === "cost") {
			method = "acti_customs.acti_customizations.microsoft.quoter.add_license_as_cost";
			args = common;
			msg_ok = __("Agregado como costo: {0}", [resolved.display]);
		} else {
			method = "acti_customs.acti_customizations.microsoft.quoter.add_license_to_quotation";
			args = Object.assign({ margin_pct: d.get_value("margin_pct") }, common);
			msg_ok = __("Agregado a cotización: {0}", [resolved.display]);
		}
		frappe
			.call({ method, args, freeze: true, freeze_message: __("Agregando...") })
			.then((r) => {
				if (r.message) {
					d.hide();
					frappe.show_alert({ message: msg_ok, indicator: "green" });
					frm.reload_doc();
				}
			});
	}

	d.show();

	// Wire de cambios POR DELEGACIÓN sobre $wrapper (existe siempre, tolerante a re-render del control).
	VISIBLE.forEach((f) => {
		d.fields_dict["sel_" + f].$wrapper.on("change", "select", () => on_change(f));
	});
	d.fields_dict.qty.$wrapper.on("change", "input", render_preview);
	d.fields_dict.margin_pct.$wrapper.on("change", "input", render_preview);

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
		const is_draft = frm.doc.docstatus === 0 && !frm.is_new();
		const ws = frm.doc.workflow_state;
		const in_borrador = !ws || ws === DRAFT_WORKFLOW_STATE;
		if (is_draft && in_borrador) {
			frm.add_custom_button(__("Cotizador Microsoft"), () =>
				acti_customs.ms.open_dialog(frm)
			);
		}
	},
});
