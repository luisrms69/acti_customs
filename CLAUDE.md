# CLAUDE.md — acti_customs

> **Reglas de operación Claude Code** (commits, PRs, base de datos, flujo de trabajo, prohibiciones git):
> Ver `/home/erpnext/Developer/frappe-infrastructure/.claude/CLAUDE.md`

---

## Estado del proyecto

- **App nueva:** creada en frappe-bench-v16
- **Bench activo:** `/home/erpnext/frappe-bench-v16`
- **Branch protegida:** `version-16` (nunca commitear directamente — estándar Frappe)
- **Versión:** 0.0.1 (desarrollo inicial)
- **En producción:** No

---

## Sites de desarrollo y prueba

| Site | Bench | Propósito | Notas |
|---|---|---|---|
| `<dev-site>` | frappe-bench-v16 | Desarrollo activo | Features, migrate, export-fixtures |
| `test-acti_customs.localhost` | frappe-bench-v16 | Tests unitarios | Solo para `bench run-tests` — nunca modificar manualmente |

> **`<dev-site>`** es un placeholder. El nombre real del site de desarrollo es infraestructura del
> cliente y **no se versiona**; vive únicamente en la configuración local del bench
> (`.claude/settings.local.json`, no publicado). Sustituir `<dev-site>` por ese nombre al operar.

**Reglas de uso:**
- `bench migrate` → siempre con `--site`. Nunca sin site en bench compartido.
- `bench run-tests` → siempre `test-acti_customs.localhost` — nunca en el site de desarrollo.
- `bench export-fixtures` → `<dev-site>`

**Apps en test-acti_customs.localhost:** frappe, erpnext, acti_customs

## Entorno
Ver contexto global en `frappe-infrastructure/.claude/CLAUDE.md`.

**Comandos frecuentes (bench v16):**
```bash
bench --site <dev-site> migrate
bench --site <dev-site> export-fixtures --app acti_customs
bench --site <dev-site> run-tests --app acti_customs
bench build --app acti_customs
```
**NUNCA:** `bench migrate` sin `--site` — afecta todos los sites del bench compartido

---

## Qué hace esta app

ACTI-specific business customizations

---

## DocTypes principales

*(pendiente de documentar al implementar)*

---

## Fixtures

*(pendiente — declarar en hooks.py al crear Custom Fields, Roles, Workspaces)*

---

## Dependencias

**Apps requeridas:** erpnext
**Apps en frappe-bench-v16:** frappe, erpnext, acti_customs
**Dependencias externas:** Ninguna

---

## Tests

```bash
bench --site test-acti_customs.localhost run-tests --app acti_customs
```

**Sin cobertura inicial.** Documentar tests aquí cuando se implementen.
**Site de tests dedicado:** `test-acti_customs.localhost` — nunca correr tests en el site de desarrollo.

---

## REGLAS GIT — ACTI_CUSTOMS

### Antes de cada commit

- Correr linters en archivos modificados:
  ```bash
  ruff format <archivos .py modificados>
  npx prettier@2.7.1 --write <archivos .js modificados>
  ```

### Antes de cada PR

- [ ] Linters pasados
- [ ] Fixtures exportados si hubo cambios de Custom Fields, Roles, Workspaces
- [ ] Patch creado si hay cambios de esquema — **requiere autorización explícita**
- [ ] `bench --site <dev-site> migrate` limpio
- [ ] Ver checklist global en `frappe-infrastructure/CONTRIBUTING.md`

### PROHIBICIÓN ABSOLUTA — NUNCA TRABAJAR EN version-16

**`version-16` es la rama protegida de acti_customs. Es el estándar Frappe upstream.**

Nota: otros repos Buzola usan `main` o `develop` por razones históricas.
Los apps nuevos del ecosistema usan `version-16` alineado con frappe/erpnext/hrms.

- **Nunca implementar cambios estando en `version-16`.**
- **Nunca crear commits estando en `version-16`.**
- **Nunca hacer push directo a `version-16`.** Todo cambio entra por PR.
- Todo cambio (incluso documental) debe iniciar en una **rama de trabajo** creada desde `version-16`
  limpio y sincronizado. Convención de prefijos: `feat/ fix/ docs/ chore/ refactor/ hotfix/`
  (ver `CONTRIBUTING.md`).
- `/ship commit` y `/ship push` deben **rechazar** si la rama es `version-16`.
- `/ship commit-push` está **deprecado y bloqueado** (ver `ship.md`): usar `/ship commit` y luego `/ship push`.
- `/ship pr` debe exigir rama distinta de `version-16` (PR hacia `version-16` como base).

**Única excepción de bootstrap:** el primer commit + primer push a `version-16` (Pasos 8–9) solo
para crear el repo remoto vacío. Esa excepción **termina en cuanto se crea y valida el ruleset**
(Paso 9b). Después de eso, ni un cambio documental va directo a `version-16`.

### Reglas específicas del proyecto

- PRs siempre a `version-16`
- Site de desarrollo: `<dev-site>`
- Site de tests: `test-acti_customs.localhost`
