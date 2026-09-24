# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from acti_customs.acti_customizations.microsoft.keys import (
	build_display_name_capped,
	build_item_code,
	build_offer_key,
)

VALID_SEGMENTS = ("Commercial", "Education", "Charity")


class MicrosoftOffer(Document):
	"""Una oferta del catalogo Microsoft (una fila del precio vigente).

	Un Microsoft Offer se materializa 1:1 en un Item ERPNext (no lazy). La identidad
	tecnica es `offer_key` (ProductId|SkuId|TermDuration|BillingPlan|Segment), que es
	tambien el name del documento. El precio/vigencia viven aqui (catalogo), no en la
	identidad historica del Item.
	"""

	def before_naming(self):
		# offer_key es el name (autoname field:offer_key); debe calcularse ANTES del naming.
		self.offer_key = build_offer_key(
			self.product_id, self.sku_id, self.term_duration, self.billing_plan, self.segment
		)

	def validate(self):
		# Recalcular la clave de forma defensiva (mantiene consistencia ante edicion manual).
		self.offer_key = build_offer_key(
			self.product_id, self.sku_id, self.term_duration, self.billing_plan, self.segment
		)
		if self.segment not in VALID_SEGMENTS:
			frappe.throw(
				_("Segment invalido: {0}. Debe ser uno de {1}.").format(self.segment, VALID_SEGMENTS)
			)
		if self.effective_start_date and self.effective_end_date:
			if getdate(self.effective_end_date) < getdate(self.effective_start_date):
				frappe.throw(_("Effective End Date no puede ser anterior a Effective Start Date."))

	def expected_item_code(self):
		"""item_code determinista que le corresponde a esta oferta (no crea el Item)."""
		return build_item_code(
			self.product_id, self.sku_id, self.term_duration, self.billing_plan, self.segment
		)

	def expected_item_name(self):
		"""item_name (<=140): SkuTitle | compromiso | facturacion | segmento (abrevia solo SkuTitle)."""
		return build_display_name_capped(
			self.sku_title, self.term_duration, self.billing_plan, self.segment, self.tags
		)

	def is_vigente(self, on_date=None):
		"""True si la oferta es comercialmente vigente en `on_date` (default hoy).

		Vigencia = activa en el catalogo (is_active) Y dentro del rango de fechas.
		Se deriva de los datos; no se almacena un estado redundante.
		"""
		if not self.is_active:
			return False
		ref = getdate(on_date or today())
		if self.effective_start_date and ref < getdate(self.effective_start_date):
			return False
		if self.effective_end_date and ref > getdate(self.effective_end_date):
			return False
		return True
