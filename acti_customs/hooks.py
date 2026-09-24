app_name = "acti_customs"
app_title = "ACTI Customizations"
app_publisher = "Consultoria en Negocios y Aplicaciones"
app_description = "ACTI-specific business customizations"
app_email = "it@buzola.mx"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext"]

# Fixtures
# ------------------
# Custom Fields de acti_customs (catalogo Microsoft) sobre Item. Se exportan/importan
# filtrados por fieldname para no arrastrar custom fields de otras apps.
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
					"ms_offer",
					"ms_offer_key",
					"ms_product_id",
					"ms_sku_id",
					"ms_term_duration",
					"ms_billing_plan",
					"ms_segment",
					"ms_col_break",
					"ms_product_title",
					"ms_sku_title",
					"ms_market",
					"ms_currency",
					"ms_offer_label",
				],
			],
		],
	},
]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "acti_customs",
# 		"logo": "/assets/acti_customs/logo.png",
# 		"title": "ACTI Customizations",
# 		"route": "/acti_customs",
# 		"has_permission": "acti_customs.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/acti_customs/css/acti_customs.css"
# app_include_js = "/assets/acti_customs/js/acti_customs.js"

# include js, css files in header of web template
# web_include_css = "/assets/acti_customs/css/acti_customs.css"
# web_include_js = "/assets/acti_customs/js/acti_customs.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "acti_customs/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "acti_customs/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "acti_customs.utils.jinja_methods",
# 	"filters": "acti_customs.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "acti_customs.install.before_install"
# after_install = "acti_customs.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "acti_customs.uninstall.before_uninstall"
# after_uninstall = "acti_customs.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "acti_customs.utils.before_app_install"
# after_app_install = "acti_customs.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "acti_customs.utils.before_app_uninstall"
# after_app_uninstall = "acti_customs.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "acti_customs.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "acti_customs.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["acti_customs.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"acti_customs.tasks.all"
# 	],
# 	"daily": [
# 		"acti_customs.tasks.daily"
# 	],
# 	"hourly": [
# 		"acti_customs.tasks.hourly"
# 	],
# 	"weekly": [
# 		"acti_customs.tasks.weekly"
# 	],
# 	"monthly": [
# 		"acti_customs.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "acti_customs.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "acti_customs.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "acti_customs.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "acti_customs.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["acti_customs.utils.before_request"]
# after_request = ["acti_customs.utils.after_request"]

# Job Events
# ----------
# before_job = ["acti_customs.utils.before_job"]
# after_job = ["acti_customs.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"acti_customs.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
