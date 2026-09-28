# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Tests de funciones puras del catálogo Microsoft (sin BD)."""

import unittest

from acti_customs.acti_customizations.microsoft.keys import (
	build_display_name,
	build_item_code,
	is_trial_offer,
	microsoft_cost,
)


class TestKeys(unittest.TestCase):
	# --- regla de costo (/12) aplicada en sync, no en runtime ---
	def test_cost_p1y_monthly_divided_by_12(self):
		self.assertEqual(microsoft_cost(120, "P1Y", "Monthly"), 10.0)

	def test_cost_p1y_annual_sin_division(self):
		self.assertEqual(microsoft_cost(120, "P1Y", "Annual"), 120.0)

	def test_cost_p1m_sin_division(self):
		self.assertEqual(microsoft_cost(20, "P1M", "Monthly"), 20.0)

	def test_cost_trial_cero(self):
		self.assertEqual(microsoft_cost(0, "P1M", "None"), 0.0)

	# --- trial = P1M + None (sin depender de tags) ---
	def test_trial_p1m_none(self):
		self.assertTrue(is_trial_offer("P1M", "None"))

	def test_no_trial_p1m_monthly(self):
		self.assertFalse(is_trial_offer("P1M", "Monthly"))

	def test_no_trial_p1y_annual(self):
		self.assertFalse(is_trial_offer("P1Y", "Annual"))

	# --- item_code determinista (identidad) ---
	def test_item_code_deterministico(self):
		self.assertEqual(
			build_item_code("CFQ7X1", "S1", "P1Y", "Annual", "Commercial"),
			"MS-CFQ7X1-S1-P1Y-Annual-Commercial",
		)

	# --- display trial: "Prueba 1 mes" sin "None" ---
	def test_display_trial(self):
		d = build_display_name("Azure VD", "P1M", "None", "Commercial")
		self.assertIn("Prueba 1 mes", d)
		self.assertNotIn("None", d)

	def test_display_normal(self):
		d = build_display_name("Office 365 E3", "P1Y", "Annual", "Commercial")
		self.assertEqual(d, "Office 365 E3 | 1 año | anual | Commercial")
