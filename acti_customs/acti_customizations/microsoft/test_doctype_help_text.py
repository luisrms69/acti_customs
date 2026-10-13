# Copyright (c) 2025, Consultoria en Negocios y Aplicaciones and contributors
# For license information, please see license.txt

"""Regresión del render de textos de ayuda con el motor de plantillas de Frappe (`microtemplate.js`).

No prohíbe comillas simples de forma indiscriminada: **reproduce el problema real de renderizado**.
Porta el algoritmo de compilación de `microtemplate.js` (que convierte el texto en el cuerpo de una
función `_p.push('...')`) y verifica que el cuerpo generado **compila como JavaScript** (igual que el
`new Function(...)` del navegador). El bug de `microtemplate.js` es que su regex
`/((^|%})[^\\t]*)'/g` solo escapa la PRIMERA comilla simple tras `^`/`%}`: un *par* de comillas deja la
segunda sin escapar y rompe el literal → "Error in Template". Un apóstrofe **suelto** sí se escapa y es
válido, por eso no debe marcarse como error.
"""

import json
import os
import re
import shutil
import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

_APP = frappe.get_app_path("acti_customs")
DOCTYPE_JSON = os.path.join(
	_APP, "acti_customizations", "doctype", "microsoft_catalog_sync", "microsoft_catalog_sync.json"
)
CUSTOM_FIELDS_JSON = os.path.join(_APP, "fixtures", "custom_field.json")


def _microtemplate_fn_str(s: str) -> str:
	"""Port fiel de `frappe.template` (microtemplate.js) → cuerpo de la función compilada."""
	t = re.sub(r"[\r\t\n]", " ", s)
	t = t.replace("{%", "\t")
	t = re.sub(r"((^|%\})[^\t]*)'", lambda m: m.group(1) + "\r", t)  # escapa solo la 1ª comilla (bug real)
	t = re.sub(r"\t=(.*?)%\}", lambda m: "'," + m.group(1) + ",'", t)
	t = t.replace("\t", "');\n")
	t = t.replace("%}", "\n_p.push('")
	t = t.replace("\r", "\\'")
	return "with(obj){\n_p.push('" + t + "');}return _p.join('');"


def _compiles_as_js(fn_str: str):
	"""True/False si el cuerpo compila con `new Function` (como el navegador); None si no hay node."""
	node = shutil.which("node")
	if not node:
		return None
	r = subprocess.run(
		[node, "-e", "new Function('obj', require('fs').readFileSync(0, 'utf8'));"],
		input=fn_str,
		capture_output=True,
		text=True,
	)
	return r.returncode == 0


def _renders_ok(text: str):
	return _compiles_as_js(_microtemplate_fn_str(text))


class TestDocTypeHelpTextRendersSafely(FrappeTestCase):
	def setUp(self):
		if _compiles_as_js("with(obj){\n_p.push('x');}return _p.join('');") is None:
			self.skipTest("node no disponible para validar el render de microtemplate")

	def _rendered_texts(self):
		"""(ubicación, texto) de los campos cuyo contenido Frappe pasa por el motor de plantillas."""
		texts = []
		meta = json.load(open(DOCTYPE_JSON, encoding="utf-8"))
		for f in meta.get("fields", []):
			for k in ("options", "description"):
				if isinstance(f.get(k), str) and f[k]:
					texts.append((f"Microsoft Catalog Sync:{f.get('fieldname')}.{k}", f[k]))
		for r in json.load(open(CUSTOM_FIELDS_JSON, encoding="utf-8")):
			if isinstance(r.get("description"), str) and r["description"]:
				texts.append((f"{r.get('name')}.description", r["description"]))
		return texts

	def test_todos_los_textos_compilan_en_microtemplate(self):
		fallos = [donde for donde, txt in self._rendered_texts() if not _renders_ok(txt)]
		self.assertEqual(fallos, [], f"Textos que rompen microtemplate.js (Error in Template): {fallos}")

	def test_el_checker_distingue_bug_de_apostrofe_suelto(self):
		# Control negativo: el patrón original (par de comillas que encierra un término) DEBE romper.
		self.assertFalse(
			_renders_ok("(Price List 'Microsoft NCE - Compra', USD)"),
			"El checker debe detectar el par de comillas como render roto (el bug real).",
		)
		# Control positivo: NO se prohíbe la comilla simple en general — un apóstrofe suelto es válido.
		self.assertTrue(
			_renders_ok("Texto con un apostrofe suelto: d'accord, sin romper el render."),
			"Un apóstrofe suelto se escapa bien y no debe marcarse como error.",
		)
		# Y el texto ya corregido (comillas dobles) debe renderizar.
		self.assertTrue(
			_renders_ok('(Price List "Microsoft NCE - Compra", USD)'),
			"El texto corregido con comillas dobles debe renderizar sin error.",
		)
