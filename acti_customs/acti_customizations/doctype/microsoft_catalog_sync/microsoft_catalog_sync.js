// Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
// For license information, please see license.txt
//
// Presentación nativa (frappe.msgprint con HTML) del resultado de la sincronización. El backend
// sigue devolviendo el MISMO JSON (y lo guarda en `last_result` para auditoría/pruebas); aquí solo
// se transforma ese JSON en un resumen legible: cabecera Dry Run/Apply, tarjetas de conteos, tablas
// acotadas de novedades (con "+N más") y errores. Sin DocTypes, páginas ni dependencias nuevas.
//
// El helper de presentación se expone bajo `acti_customs.ms_catalog_sync` (mismo patrón que
// `quotation_microsoft.js` con `acti_customs.ms`). Una función top-level "suelta" NO es confiablemente
// alcanzable desde el closure del controlador en el bundle del desk; además, el `.catch` del handler
// debe SURFACEAR el error (no tragarlo), para que el usuario siempre vea un resultado comprensible.

/* global acti_customs */

frappe.provide("acti_customs.ms_catalog_sync");

frappe.ui.form.on("Microsoft Catalog Sync", {
	refresh(frm) {
		// Valor inicial de la Company objetivo: default global (el usuario puede cambiarlo).
		if (!frm.doc.target_company && frappe.defaults.get_default("company")) {
			frm.set_value("target_company", frappe.defaults.get_default("company"));
		}
		const run = (dry_run) => {
			if (!frm.doc.catalog_file) {
				frappe.msgprint(__("Adjunte primero el archivo .xlsx del catalogo."));
				return;
			}
			const label = dry_run ? __("Dry Run") : __("Aplicando catalogo");
			frappe.dom.freeze(label + "...");
			frappe
				.call({
					method: "acti_customs.acti_customizations.microsoft.sync.run_sync_from_single",
					args: { dry_run: dry_run ? 1 : 0 },
				})
				.then((r) => {
					frappe.dom.unfreeze();
					const data = r && r.message;
					if (!data) {
						// El servidor respondió sin resultados: avisar explícitamente (nunca silencio).
						frappe.msgprint({
							title: __("Sincronización catálogo Microsoft"),
							indicator: "orange",
							message: __("El servidor no devolvió resultados para mostrar."),
						});
						return;
					}
					// Mostrar SIEMPRE el reporte. reload_doc (refresca last_run_*) es secundario y no debe
					// impedir el diálogo: se dispara después y cualquier fallo suyo se ignora, no tapa el mensaje.
					frappe.msgprint(acti_customs.ms_catalog_sync.render_report(data));
					try {
						const p = frm.reload_doc();
						if (p && typeof p.catch === "function") p.catch(() => {});
					} catch (e) {
						// no-op: el reporte ya se mostró
					}
				})
				.catch((e) => {
					// NUNCA tragar el error en silencio: mostrar un mensaje comprensible (requisito del reporte).
					frappe.dom.unfreeze();
					const detail =
						e && (e.message || e._server_messages)
							? "<br><pre style='white-space:pre-wrap'>" +
							  frappe.utils.escape_html(String(e.message || e._server_messages)) +
							  "</pre>"
							: "";
					frappe.msgprint({
						title: __("Sincronización catálogo Microsoft — error"),
						indicator: "red",
						message: __("No se pudo completar la operación.") + detail,
					});
				});
		};

		frm.add_custom_button(__("Dry Run"), () => run(true));
		frm.add_custom_button(__("Aplicar catalogo"), () => {
			frappe.confirm(
				__("Esto creara/actualizara Items y sus precios (Buying Item Price). Continuar?"),
				() => run(false)
			);
		});
	},
});

// Construye el objeto {title, indicator, message} para frappe.msgprint a partir del JSON del backend.
// Expuesto en el namespace del app (alcanzable desde el controlador en el bundle del desk) y
// defensivo: nunca lanza (msg ausente/parcial → se degrada), para garantizar que SIEMPRE haya mensaje.
acti_customs.ms_catalog_sync.render_report = function (msg) {
	const esc = frappe.utils.escape_html;
	// Entero seguro (null/undefined/""/no numérico → 0). NO usar `frappe.utils.cint`: no existe en el
	// cliente (cint es un global del desk); en staging lanzaba "frappe.utils.cint is not a function".
	const toInt = (v) => {
		const n = parseInt(v, 10);
		return Number.isNaN(n) ? 0 : n;
	};
	msg = msg || {}; // null/undefined → objeto vacío (defensivo; el handler ya filtra, doble resguardo)
	const a = msg.applied; // presente solo en Apply
	const is_apply = !!a;
	const errors = is_apply ? a.row_errors || [] : msg.errors || [];
	const has_err = errors.length > 0;

	const title = is_apply
		? __("Catálogo Microsoft — Aplicado")
		: __("Catálogo Microsoft — Dry Run (análisis, sin cambios)");
	const indicator = has_err ? "red" : is_apply ? "green" : "blue";

	// --- Tarjetas de conteos (solo métricas realmente provistas por el backend) ---
	const metrics = is_apply
		? [
				[__("Válidos"), msg.rows_valid, ""],
				[__("Creados"), a.items_created, "green"],
				[__("Actualizados"), a.items_updated, ""],
				[__("Reactivados"), a.items_reactivated, "blue"],
				[__("Retirados"), a.items_retired, "orange"],
				[__("Precios"), a.prices_upserted, ""],
				[__("Item Defaults"), a.item_defaults_set, ""],
				[__("Errores"), errors.length, has_err ? "red" : ""],
		  ]
		: [
				[__("Leídos"), msg.rows_read, ""],
				[__("Válidos"), msg.rows_valid, ""],
				[__("Nuevos"), msg.items_new, "green"],
				[__("Existentes"), msg.items_existing, ""],
				[__("Reactivados"), msg.items_reactivated, "blue"],
				[__("Retiros"), msg.items_to_retire, "orange"],
				[__("Requieren transición"), msg.items_needing_transition, "orange"],
				[__("Errores"), errors.length, has_err ? "red" : ""],
		  ];

	const card = ([label, value, color]) =>
		`<div style="flex:1 1 90px;min-width:90px;border:1px solid var(--border-color);
			border-left:3px solid var(--${color ? color : "border"}-500,var(--border-color));
			border-radius:6px;padding:6px 10px;margin:4px;text-align:center">
			<div style="font-size:1.4em;font-weight:600">${toInt(value)}</div>
			<div class="text-muted small">${esc(label)}</div>
		</div>`;
	const cards =
		`<div style="display:flex;flex-wrap:wrap;margin:-4px 0 8px">` +
		metrics.map(card).join("") +
		`</div>`;

	// --- Banner de estado ---
	let banner;
	if (is_apply) {
		banner = has_err
			? `<div class="text-danger" style="margin-bottom:8px"><b>${__(
					"Aplicado con errores"
			  )}</b> — ${__("revise el detalle de errores abajo.")}</div>`
			: `<div class="text-success" style="margin-bottom:8px"><b>${__(
					"Aplicado correctamente"
			  )}</b></div>`;
	} else {
		banner = `<div class="text-muted" style="margin-bottom:8px">${__(
			"Análisis sin modificar datos. Use 'Aplicar catálogo' para ejecutar los cambios."
		)}</div>`;
	}

	// --- Tablas acotadas de novedades (códigos) ---
	const details = msg.details || {};
	const code_table = (label, codes, total) => {
		if (!total) return "";
		const shown = codes || [];
		const rows = shown.map((c) => `<tr><td><code>${esc(c)}</code></td></tr>`).join("");
		const more =
			total > shown.length
				? `<div class="text-muted small" style="margin-bottom:8px">+${
						total - shown.length
				  } ${__("más")}</div>`
				: "";
		return (
			`<h5 style="margin-top:10px">${esc(label)} (${toInt(total)})</h5>` +
			`<table class="table table-bordered table-condensed" style="margin-bottom:2px">${rows}</table>` +
			more
		);
	};
	const novedades =
		code_table(__("Nuevos"), details.new, msg.items_new) +
		code_table(__("Reactivados"), details.reactivated, msg.items_reactivated) +
		code_table(__("Retiros"), details.to_retire, msg.items_to_retire) +
		code_table(
			__("Requieren transición (se normalizan al aplicar)"),
			details.needs_transition,
			msg.items_needing_transition
		);

	// --- Tabla de errores (acotada) ---
	let errs_html = "";
	if (has_err) {
		const LIMIT = 50;
		const shown = errors.slice(0, LIMIT);
		const rows = shown
			.map(
				(e) =>
					`<tr><td><code>${esc(e.item_code || e.row || "")}</code></td><td>${esc(
						e.error || ""
					)}</td></tr>`
			)
			.join("");
		const more =
			errors.length > LIMIT
				? `<div class="text-muted small">+${errors.length - LIMIT} ${__("más")}</div>`
				: "";
		errs_html =
			`<h5 class="text-danger" style="margin-top:10px">${__("Errores")} (${
				errors.length
			})</h5>` +
			`<table class="table table-bordered table-condensed"><thead><tr>` +
			`<th>${__("Código / Fila")}</th><th>${__("Error")}</th></tr></thead>${rows}</table>` +
			more;
	}

	const footer = `<div class="text-muted small" style="margin-top:10px">${__("Hoja")}: ${esc(
		msg.sheet || ""
	)} · ${__("Lista de precios")}: ${esc(msg.price_list || "")}${
		msg.target_company ? " · " + __("Company") + ": " + esc(msg.target_company) : ""
	}</div>`;

	return {
		title: title,
		indicator: indicator,
		message: banner + cards + novedades + errs_html + footer,
	};
};
