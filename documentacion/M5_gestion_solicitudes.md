# M5 — Gestión de Solicitudes

> Módulo del sistema CertiSENA que gestiona el ciclo de vida de una solicitud
> de certificación, desde que la empresa la redacta hasta que se radica,
> junto con los documentos que debe adjuntar.

| | |
|---|---|
| **Responsables** | Marlon y Vanessa — apoyo de Javier |
| **Implementado** | Bloques 1 a 4 (SOL-001 → 040) |
| **Pendiente** | Bloques 5, 6 y 7 |
| **Tamaño** | 43 endpoints · 40 permisos · 366 tests |

---

## 1. Qué resuelve el módulo

Una empresa que quiere certificarse tiene que hacer dos cosas:

1. **Presentar una solicitud** diciendo qué norma ISO quiere, con qué alcance,
   cuántos empleados y cuántas sedes tiene.
2. **Adjuntar los documentos** que respaldan esa solicitud, y esperar a que la
   administración los revise.

M5 cubre esas dos cosas: **el trámite y sus papeles**.

Lo que hace especial al módulo es que **cada acción está atada a un permiso
del Excel de la institución**. No hay reglas de acceso improvisadas: los 40
permisos implementados se transcriben a código, y un test verifica que sigan
coincidiendo.

---

## 2. La pieza central: la matriz de permisos

Esto es lo más importante que explicar, porque es lo que diferencia a M5 del
resto de módulos.

### El problema

El Excel define, para cada acción, qué puede hacer cada uno de los ocho roles.
Son 70 filas por 8 columnas. Si esas reglas se escriben a mano dentro de cada
endpoint, pasan tres cosas: se repiten, se contradicen entre sí, y cuando el
Excel cambia nadie se entera.

### La solución

La matriz vive en **un solo sitio**, `solicitud_permissions.py`, escrita igual
que en la hoja:

```python
PERMISOS_M5 = {
    #                                    SUPERADM ADM AUX EMP AUD COM APR PUB
    "SOL-001": ("Crear solicitud",             (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-005": ("Radicar solicitud",           (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-006": ("Consultar solicitud radicada",(V,  V,  V,  V,  V,  V,  V,  F)),
    ...
}
```

Y cada endpoint solo declara **qué permiso exige**:

```python
@router.post("/{id_solicitud}/radicar")
async def radicar_solicitud(
    id_solicitud: UUID,
    usuario: dict = Depends(requiere_permiso("SOL-005")),   # ← aquí
    db: AsyncSession = Depends(get_db),
):
```

Si el rol no tiene el permiso, la petición ni siquiera llega al código de
negocio: se corta con un `403` que dice exactamente qué permiso faltó.

### El test que lo mantiene honesto

`test_la_matriz_del_codigo_coincide_con_el_excel` **abre el archivo
`permisos.xlsx`** y compara celda por celda contra el código.

Si alguien cambia un permiso en la hoja y no lo refleja en el programa, la
suite falla y señala la celda exacta. La hoja de cálculo deja de ser un
documento que se desactualiza y pasa a ser la fuente de verdad.

### Ocho columnas, siete roles

El Excel tiene una columna `APR` (aprobador), pero **el aprobador es el
administrador**: no es un rol aparte.

Antes de unificarlos revisé las 70 filas: ADM y APR difieren en 29, y en las 29
ADM es el más permisivo. **No hay ninguna fila donde APR conceda algo que ADM
no conceda**, así que fusionarlos no le quita permisos a nadie.

Por eso el código separa dos conceptos:

| | |
|---|---|
| `COLUMNAS_MATRIZ` | Las 8 siglas del Excel, para poder comparar con la hoja |
| `ROLES_DEL_SISTEMA` | Los 7 roles reales de la tabla `rol` |
| `ROLES_A_COLUMNA` | Qué columna le toca a cada rol |

---

## 3. El ciclo de vida de una solicitud

```
                  SOL-001 / SOL-002  (crear / guardar borrador)
                         │
                         ▼
                    ┌──────────┐
      SOL-003 ─────►│ Borrador │◄───── SOL-008 (duplicar)
      (editar)      └────┬─────┘
      SOL-004 ─────►     │ SOL-005 (radicar)
      (eliminar)         ▼
                   ┌───────────┐
                   │ Radicada  │
                   └─────┬─────┘
          SOL-009        │              (Bloque 6)
       ┌─────────────────┴────────────────┐
       ▼                                  ▼
 ┌────────────┐                    ┌──────────────┐
 │ Cancelada  │                    │ En revision  │
 └────────────┘                    └──────────────┘
```

### Las reglas que impone el código

| Regla | Qué responde si se incumple |
|---|---|
| Solo se edita o elimina en `Borrador` | `409` |
| Radicar exige norma, alcance, empleados y sedes | `422` con la lista de lo que falta |
| Se cancela solo antes de la revisión | `409` |
| La cancelación exige un motivo | `422` |
| **Una empresa no ve ni toca solicitudes de otra** | `404` |

### Un detalle de seguridad que conviene explicar

Cuando una empresa pide una solicitud que no es suya, el sistema responde
**`404` (no existe)** y no `403` (prohibido).

La diferencia importa: un `403` le confirmaría que **esa solicitud sí existe**.
Probando radicados uno por uno podría deducir cuántas solicitudes hay o si un
competidor está tramitando una certificación. Con `404` no aprende nada.

### El número de radicado

Formato `SOL-2026-000042`. El consecutivo sale de una **secuencia de
PostgreSQL**, no de un `COUNT(*) + 1`. Si dos empresas radican en el mismo
instante, la base garantiza que cada una recibe un número distinto.

### El borrado que no borra

`SOL-004` nunca ejecuta un `DELETE`. Marca `deleted_at` y `deleted_by`, y todas
las consultas filtran por `deleted_at IS NULL`.

Es un expediente de certificación: aunque la empresa descarte un borrador, debe
poder auditarse quién lo creó y quién lo descartó.

---

## 4. Los documentos y su versionado

Cuando la empresa **reemplaza** un documento (SOL-032), la versión anterior no
se pierde: se copia a `historial_documento_solicitud` y la nueva sube de
versión.

```
  documento_solicitud            historial_documento_solicitud
  ┌────────────────────┐         ┌────────────────────┐
  │ camara v2  Pendiente│  ←──── │ camara v1  Rechazado│
  └────────────────────┘         └────────────────────┘
      (la vigente)                  (lo que se presentó antes)
```

Así queda registrado qué presentó la empresa en cada momento y por qué se le
pidió cambiarlo.

### Estados de un documento

`Pendiente` → la empresa lo subió · `Aprobado` (SOL-038) · `Rechazado`
(SOL-037) · `Correccion` (SOL-039, hay que volver a subirlo)

**Un documento aprobado ya no se puede reemplazar ni eliminar** (`409`).

### La validación automática (SOL-036)

Se comprueba al subir y al reemplazar, sin forma de saltársela:

- Extensiones permitidas: `.pdf .doc .docx .jpg .jpeg .png` → si no, `415`
- Máximo 10 MB → si no, `413`
- Archivo vacío → `400`

### Dónde se guardan los archivos

En `storage/solicitudes/<id_solicitud>/`, y en la base solo la ruta.

**El nombre que envía el usuario nunca se usa para construir la ruta real**: en
disco el fichero se llama como el id del documento. El nombre original se
sanea (se le quitan tildes, barras y caracteres raros) y solo sirve para
mostrarlo y para la descarga.

Si no se hiciera, alguien podría subir un archivo llamado `../../.env` y
escribir fuera de la carpeta. Hay un test que lo comprueba.

---

## 5. Información general y sedes (bloques 2 y 3)

### Registrar no es lo mismo que editar

En la hoja son permisos distintos (SOL-011 registrar norma / SOL-012 editarla),
así que el código los separa igual que subir y reemplazar un documento:

| Acción | Si el dato… | Respuesta |
|---|---|---|
| Registrar | ya existe | `409` indicando el permiso de edición |
| Editar | todavía no existe | `409` indicando el permiso de registro |

El número de sedes (SOL-019) solo tiene permiso de registro: si ya está, el
`409` remite a editar el borrador (SOL-003).

Los alcances y los procesos clave viven en `alcance_solicitud` y
`proceso_solicitud`. La hoja no da permiso para borrarlos, así que se pasan a
`Inactivo` con el permiso de edición. Dos procesos activos no pueden llamarse
igual.

`GET /solicitudes/{id}/informacion-general` (SOL-020) lo reúne todo: empresa,
norma, alcances, procesos, sedes incluidas y **qué campos faltan para radicar**.

### Las sedes son de la empresa, no de la solicitud

```
  empresa ──< sede_empresa >──< solicitud_sede >── solicitud
                (la sede física)      (el vínculo y su estado)
```

Una sede se registra una vez y se reutiliza en varias solicitudes. De ahí
salen las reglas:

| Regla | Qué responde |
|---|---|
| Agregar una sede existente de **otra** empresa | `404` |
| Agregar una sede `Inactiva` o ya incluida | `409` |
| Quitar una sede (SOL-023) no la borra: el vínculo pasa a `Excluida` y se reactiva si se vuelve a agregar | `200` |
| Inactivar una sede (SOL-023) la quita de la solicitud y la marca `Inactiva` en la empresa | `200` |
| Cambiar o inactivar una sede que ya está en **otra solicitud radicada** | `409`: se alteraría un expediente presentado |

### Registrar la sede y su ubicación

- **SOL-021** incluye una sede que la empresa ya tiene registrada. El portal la
  elige de `GET /solicitudes/{id}/sedes/disponibles` (sedes activas que aún no
  están en la solicitud).
- **SOL-024** tiene ruta propia, `POST /solicitudes/{id}/sedes/nueva`: registra
  la sede con su dirección y la incluye. Verifica además SOL-021, SOL-026
  (ciudad) y SOL-027 (departamento) con `exigir_permisos(...)`.
- **Ciudad, departamento y país solo se indican al registrar la sede.** No hay
  ninguna ruta para cambiarlos: si están mal, la sede se inactiva y se registra
  otra. Así una sede nunca "se muda" dentro de un expediente.
- **SOL-025** corrige la dirección y **SOL-022** el nombre y cuál es la
  principal.

### Validación de Administración (SOL-029)

Solo sobre solicitudes ya radicadas. Cada sede queda `Validada` o
`Con observaciones`, y se reportan las inconsistencias:

- sedes sin dirección, ciudad o departamento, o ya inactivas en la empresa;
- que no haya sedes, o que no coincidan con el número declarado (SOL-019);
- que no haya exactamente una sede principal.

### Exportación a Excel (SOL-030)

El `.xlsx` se genera con la librería estándar, igual que el PDF: **ninguna
dependencia nueva**. Todas las celdas son texto, así que un nombre de sede como
`=HYPERLINK(...)` se muestra tal cual y nunca se ejecuta como fórmula.

### Portal de empresa

`/empresa` usa los mismos componentes que el portal del Comité (encabezado,
menú lateral, paneles, tablas y estados de `styles.css`), para que todo el
proyecto se vea igual. El menú tiene cinco vistas: **Mis solicitudes**,
**Nueva solicitud**, **Información técnica** (bloque 2), **Sedes** (bloque 3) y
**Documentos** (bloque 4). Si la solicitud ya no está en borrador, las vistas
se muestran en solo lectura.

### Revisión de Administración

`/revision-solicitudes` (enlace *Revisión de solicitudes* en el panel del
administrador) usa el mismo diseño. Muestra la cola de solicitudes radicadas,
en revisión o todas; al revisar una se ven la empresa, la norma y sus sedes, y
se puede **validar las sedes** (SOL-029), exportarlas a Excel y descargar el
PDF. Solo entran Administrador, Auxiliar y Super Administrador.

### Estados antiguos de la base

La base tiene solicitudes con estados que M5 no usa (`APROBADO`, `EN_REVISION`,
`RADICADO`). Antes el listado respondía `500` al encontrarlas; ahora se
muestran tal cual y cualquier intento de modificarlas responde `409`.

---

## 6. Decisiones que tomé y por qué

Esto es lo que probablemente pregunten.

### No creé ninguna tabla

El esquema ya existía. El módulo se escribió contra `solicitud`,
`documento_solicitud`, `historial_documento_solicitud`, `historial_estado`,
`user_empresa`, `empresa`, `norma`, `alcance_solicitud`, `proceso_solicitud`,
`sede_empresa` y `solicitud_sede`. **Cero tablas nuevas, cero columnas
alteradas.**

Al arrancar solo se añade lo que faltaba: la secuencia del radicado, tres
índices y el rol `Publico`.

### La titularidad va por empresa, no por usuario

La solicitud no pertenece a *quien la creó* sino a **la empresa**, cruzando con
`user_empresa`.

Si el gerente crea la solicitud y luego se va de vacaciones, su compañero de la
misma empresa debe poder continuarla. Si la titularidad fuera del usuario,
quedaría bloqueada.

### El PDF no lleva identificadores internos

El PDF de la solicitud (SOL-007) sale de la aplicación y puede acabar en manos
de terceros, así que muestra **"Cafe del Eje S.A.S. (NIT 900123456-7)"** y no
`bec408ef-22a7-4a17-8736-e1b43a6eca05`.

Se generó con la librería estándar de Python, **sin añadir ninguna dependencia
al proyecto**.

### El arranque del módulo es independiente

`preparar_modulo_solicitudes()` abre **su propia sesión de base de datos**.

Si falla cualquier otra parte de la siembra inicial, M5 se prepara igual. Antes
iba dentro de la misma transacción y se habría perdido con el rollback.

---

## 7. Los tests

**366 tests propios del módulo**, y ninguno necesita base de datos: usan un
doble en memoria (`tests/fake_db.py`).

| Grupo | Tests | Qué comprueba |
|---|---|---|
| Conformidad con el Excel | 9 | Que la matriz coincida con la hoja, celda por celda |
| Autorización | 283 | Las 40 rutas × los 7 roles, el caso sin token y los permisos que verifica SOL-024 |
| Ciclo de vida | 22 | Estados, radicado consecutivo, borrado lógico, aislamiento entre empresas, PDF, estados antiguos |
| Información general | 19 | Registrar vs. editar, procesos sin nombres repetidos, estados antiguos, consulta general |
| Sedes | 26 | Ubicación fija al crear, inactivar, sedes disponibles, expedientes radicados, validación, Excel |
| Documentos | 7 | Reglas de formato y saneado del nombre de archivo |

```bash
pip install -r requirements.txt
pytest tests/ -q
```

---

## 8. Guion para la demostración

Entrar en `/login` con una cuenta de rol **Empresa**.

1. **Nueva solicitud** → elegir norma, llenar alcance, empleados y sedes →
   *Guardar borrador*
2. **Documentos** → subir un PDF → **recargar la página**: el archivo sigue ahí
3. Subir otro archivo del mismo tipo → aparece como **versión 2**, y la 1 queda
   en el historial
4. Intentar subir un `.exe` → **rechazado** por la validación de formato
5. **Radicar** → se asigna `SOL-2026-000001` y la solicitud deja de ser editable
6. **PDF** → se descarga con toda la información legible

Para enseñar los permisos: entrar con un **Auditor** y comprobar que ve la
solicitud pero **no puede crear ninguna** (`403`).

Bloques 2 y 3, sobre un borrador y desde el mismo portal:

7. **Información técnica** → registrar un proceso "Compras" y otro con el mismo
   nombre → el segundo se rechaza
8. **Sedes** → *Registrar sede nueva* → el portal advierte que ciudad y
   departamento no se podrán cambiar
9. *Editar* la sede → la ciudad aparece bloqueada; *Inactivar* y registrar otra
10. *Exportar a Excel* → descarga el `.xlsx`
11. Radicar y entrar con un **Administrador** → *Revisión de solicitudes* →
    *Revisar* → *Validar sedes*: cada sede queda `Validada` o
    `Con observaciones`, con la lista de lo que falta

---

## 9. Qué falta

| Bloque | Permisos | Tema |
|---|---|---|
| 5 | SOL-041 → 050 | Asignación de auditores (aparecen los primeros `REQ` y `SA`) |
| 6 | SOL-051 → 060 | Trazabilidad, bitácora inmutable y cierre |
| 7 | SOL-061 → 070 | Cálculo del tiempo de auditoría |

Los bloques 1 a 4 tienen API y pantallas: el portal de empresa (`/empresa`) y
la revisión de Administración (`/revision-solicitudes`).

**Una decisión pendiente:** de dónde sale qué documentos exige cada norma ISO.
Hoy la lista de tipos sugeridos está fija en el código; puede pasar a una tabla
para que la administración la edite sin tocar el programa.

**Un punto para el Bloque 6:** la tabla `historial_estado` no tiene columna de
usuario, así que ahora mismo la traza de *quién* hizo cada cambio va dentro del
texto de la observación. SOL-055 (bitácora inmutable) debería añadir
`usuario_id` y `permiso_codigo` como columnas propias.

---

## Anexo — Los 40 permisos implementados

### Bloque 1 — Ciclo de vida

| Código | Permiso | SUPERADM | ADM | AUX | EMP | AUD | COM | APR | PUB |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| SOL-001 | Crear solicitud | V | F | F | V | F | F | F | F |
| SOL-002 | Guardar borrador | V | F | F | V | F | F | F | F |
| SOL-003 | Editar borrador | V | F | F | V | F | F | F | F |
| SOL-004 | Eliminar borrador | V | F | F | V | F | F | F | F |
| SOL-005 | Radicar formalmente | V | F | F | V | F | F | F | F |
| SOL-006 | Consultar solicitud | V | V | V | V | V | V | V | F |
| SOL-007 | Descargar PDF | V | V | V | V | V | V | V | F |
| SOL-008 | Duplicar solicitud | V | F | F | V | F | F | F | F |
| SOL-009 | Cancelar antes de revisión | V | F | F | V | F | F | F | F |
| SOL-010 | Consultar estado | V | V | V | V | V | V | V | F |

### Bloque 2 — Información general

| Código | Permiso | SUPERADM | ADM | AUX | EMP | AUD | COM | APR | PUB |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| SOL-011 | Registrar norma ISO | V | F | F | V | F | F | F | F |
| SOL-012 | Editar norma ISO | V | F | F | V | F | F | F | F |
| SOL-013 | Registrar alcance técnico | V | F | F | V | F | F | F | F |
| SOL-014 | Editar alcance | V | F | F | V | F | F | F | F |
| SOL-015 | Registrar procesos clave | V | F | F | V | F | F | F | F |
| SOL-016 | Editar procesos | V | F | F | V | F | F | F | F |
| SOL-017 | Registrar número de empleados | V | F | F | V | F | F | F | F |
| SOL-018 | Editar número de empleados | V | F | F | V | F | F | F | F |
| SOL-019 | Registrar número de sedes | V | F | F | V | F | F | F | F |
| SOL-020 | Consultar información general | V | V | V | V | V | V | V | F |

### Bloque 3 — Sedes de la solicitud

| Código | Permiso | SUPERADM | ADM | AUX | EMP | AUD | COM | APR | PUB |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| SOL-021 | Agregar sede | V | F | F | V | F | F | F | F |
| SOL-022 | Editar sede | V | F | F | V | F | F | F | F |
| SOL-023 | Eliminar sede de la solicitud | V | F | F | V | F | F | F | F |
| SOL-024 | Registrar dirección | V | F | F | V | F | F | F | F |
| SOL-025 | Editar dirección | V | F | F | V | F | F | F | F |
| SOL-026 | Registrar ciudad | V | F | F | V | F | F | F | F |
| SOL-027 | Registrar departamento | V | F | F | V | F | F | F | F |
| SOL-028 | Consultar sedes añadidas | V | V | V | V | V | V | V | F |
| SOL-029 | Validar sedes | V | V | V | F | F | F | F | F |
| SOL-030 | Exportar sedes a Excel | V | V | V | V | F | F | F | F |

### Bloque 4 — Documentos adjuntos

| Código | Permiso | SUPERADM | ADM | AUX | EMP | AUD | COM | APR | PUB |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| SOL-031 | Subir documento | V | F | F | V | F | F | F | F |
| SOL-032 | Reemplazar documento | V | F | F | V | F | F | F | F |
| SOL-033 | Eliminar documento | V | F | F | V | F | F | F | F |
| SOL-034 | Descargar documento | V | V | V | V | V | V | V | F |
| SOL-035 | Ver en el visor | V | V | V | V | V | V | V | F |
| SOL-036 | Validar formato | V | V | V | V | V | V | V | F |
| SOL-037 | Rechazar documento | V | V | V | F | F | F | F | F |
| SOL-038 | Aprobar documento | V | V | V | F | F | F | F | F |
| SOL-039 | Solicitar corrección | V | V | V | F | F | F | F | F |
| SOL-040 | Historial documental | V | V | V | V | F | F | V | F |

**Códigos:** `V` concedido · `F` denegado · `REQ` requiere aprobación de un
superior · `SA` exclusivo del SuperAdministrador.

---

## Anexo — Endpoints

| Método | Ruta | Permiso |
|---|---|---|
| `POST` | `/solicitudes/` | SOL-001 |
| `POST` | `/solicitudes/borradores` | SOL-002 |
| `GET` | `/solicitudes/` | SOL-006 listado |
| `GET` | `/solicitudes/{id}` | SOL-006 detalle |
| `GET` | `/solicitudes/{id}/estado` | SOL-010 |
| `GET` | `/solicitudes/{id}/pdf` | SOL-007 |
| `PATCH` | `/solicitudes/{id}` | SOL-003 |
| `DELETE` | `/solicitudes/{id}` | SOL-004 |
| `POST` | `/solicitudes/{id}/radicar` | SOL-005 |
| `POST` | `/solicitudes/{id}/duplicar` | SOL-008 |
| `POST` | `/solicitudes/{id}/cancelar` | SOL-009 |
| `GET` | `/solicitudes/normas` | catálogo de normas |
| `GET` | `/solicitudes/documentos/formatos-permitidos` | SOL-036 |
| `POST` | `/solicitudes/{id}/documentos` | SOL-031 |
| `GET` | `/solicitudes/{id}/documentos` | SOL-035 |
| `PUT` | `/solicitudes/{id}/documentos/{doc}` | SOL-032 |
| `DELETE` | `/solicitudes/{id}/documentos/{doc}` | SOL-033 |
| `GET` | `/solicitudes/{id}/documentos/{doc}/descargar` | SOL-034 |
| `GET` | `/solicitudes/{id}/documentos/{doc}/ver` | SOL-035 |
| `POST` | `/solicitudes/{id}/documentos/{doc}/aprobar` | SOL-038 |
| `POST` | `/solicitudes/{id}/documentos/{doc}/rechazar` | SOL-037 |
| `POST` | `/solicitudes/{id}/documentos/{doc}/solicitar-correccion` | SOL-039 |
| `GET` | `/solicitudes/{id}/documentos/historial` | SOL-040 |
| `POST` | `/solicitudes/{id}/norma` | SOL-011 |
| `PATCH` | `/solicitudes/{id}/norma` | SOL-012 |
| `POST` | `/solicitudes/{id}/alcances` | SOL-013 |
| `PATCH` | `/solicitudes/{id}/alcances/{alcance}` | SOL-014 |
| `POST` | `/solicitudes/{id}/procesos` | SOL-015 |
| `PATCH` | `/solicitudes/{id}/procesos/{proceso}` | SOL-016 |
| `POST` | `/solicitudes/{id}/numero-empleados` | SOL-017 |
| `PATCH` | `/solicitudes/{id}/numero-empleados` | SOL-018 |
| `POST` | `/solicitudes/{id}/numero-sedes` | SOL-019 |
| `GET` | `/solicitudes/{id}/informacion-general` | SOL-020 |
| `GET` | `/solicitudes/{id}/sedes/disponibles` | SOL-021 |
| `POST` | `/solicitudes/{id}/sedes` | SOL-021 |
| `POST` | `/solicitudes/{id}/sedes/nueva` | SOL-024 (+ SOL-021, 026, 027) |
| `PATCH` | `/solicitudes/{id}/sedes/{sede}` | SOL-022 |
| `DELETE` | `/solicitudes/{id}/sedes/{sede}` | SOL-023 (quitar) |
| `POST` | `/solicitudes/{id}/sedes/{sede}/inactivar` | SOL-023 (inactivar) |
| `PATCH` | `/solicitudes/{id}/sedes/{sede}/direccion` | SOL-025 |
| `GET` | `/solicitudes/{id}/sedes` | SOL-028 |
| `POST` | `/solicitudes/{id}/sedes/validar` | SOL-029 |
| `GET` | `/solicitudes/{id}/sedes/excel` | SOL-030 |
