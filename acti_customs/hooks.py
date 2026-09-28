app_name = "acti_customs"
app_title = "ACTI Customizations"
app_publisher = "Consultoria en Negocios y Aplicaciones"
app_description = "ACTI-specific business customizations"
app_email = "it@buzola.mx"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext"]

# Client scripts (aditivos; NO modifican core/erpnext_proposals)
# ------------------
doctype_js = {"Quotation": "public/js/quotation_microsoft.js"}

# Fixtures
# ------------------
# Custom Fields MÍNIMOS de acti_customs (catalogo Microsoft) sobre Item: solo las dimensiones de
# licenciamiento sin equivalente nativo (ADR-0003). Precio/moneda/vigencia viven en Item Price nativo.
# NOTA: acti_customs NO modifica campos/schema estandar (sin Property Setter sobre Item).
fixtures = [
	{
		"doctype": "Custom Field",
		"filters": [
			["dt", "=", "Item"],
			[
				"fieldname",
				"in",
				[
					"ms_microsoft_section",
					"ms_product_id",
					"ms_sku_id",
					"ms_term_duration",
					"ms_billing_plan",
					"ms_segment",
					"ms_col_break",
					"ms_product_title",
					"ms_sku_title",
				],
			],
		],
	},
]

# Includes in <head>
# ------------------
# (sin includes globales)

# Testing
# -------
# before_tests = "acti_customs.install.before_tests"
