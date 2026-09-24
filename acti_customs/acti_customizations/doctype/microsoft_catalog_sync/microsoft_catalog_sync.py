# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class MicrosoftCatalogSync(Document):
	"""Single DocType operativo para cargar el catalogo Microsoft (Dry Run / Aplicar).

	La logica vive en acti_customs.acti_customizations.microsoft.sync; este DocType solo
	guarda el archivo adjunto y el resumen de la ultima ejecucion.
	"""

	pass
