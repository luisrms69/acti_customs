// Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
// For license information, please see license.txt

frappe.ui.form.on("Microsoft Catalog Sync", {
	refresh(frm) {
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
					if (r.message) {
						frappe.msgprint({
							title: dry_run ? __("Dry Run - resumen") : __("Catalogo aplicado"),
							indicator: "blue",
							message:
								"<pre>" +
								frappe.utils.escape_html(JSON.stringify(r.message, null, 1)) +
								"</pre>",
						});
						frm.reload_doc();
					}
				})
				.catch(() => frappe.dom.unfreeze());
		};

		frm.add_custom_button(__("Dry Run"), () => run(true));
		frm.add_custom_button(__("Aplicar catalogo"), () => {
			frappe.confirm(__("Esto creara/actualizara Microsoft Offer e Items. Continuar?"), () =>
				run(false)
			);
		});
	},
});
