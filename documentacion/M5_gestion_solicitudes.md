# M5 — Gestión de Solicitudes

Documentación del módulo M5, correspondiente a la hoja
`M5 — GESTIÓN DE SOLICITUDES` del archivo `documentacion/permisos.xlsx`.

| | |
|---|---|
| **Rama** | `feature/M5-gestion-solicitudes` |
| **Implementado** | Bloque 1 (SOL-001 → 010) y Bloque 4 (SOL-031 → 040) |
| **Pendiente** | Bloques 2, 3, 5, 6 y 7 |
| **Responsables** | Marlon y Vanessa — apoyo de Javier (hoja `responsables`) |

> Esta rama toca **únicamente lo que M5 necesita**. Los demás módulos los
> llevan otros integrantes y no se han modificado, salvo dos correcciones sin
> las cuales nadie puede autenticarse; están detalladas en la sección 7.

---

## 1. Permisos implementados

### Bloque 1 — Ciclo de vida (SOL-001 a SOL-010)

| Código | Permiso | SUPERADM | ADM | AUX | EMP | AUD | COM | APR | PUB |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| SOL-001 | Crear solicitud | V | F | F | V | F | F | F | F |
| SOL-002 | Guardar borrador | V | F | F | V | F | F | F | F |
| SOL-003 | Editar borrador | V | F | F | V | F | F | F | F |
| SOL-004 | Eliminar borrador | V | F | F | V | F | F | F | F |
| SOL-005 | Radicar solicitud formalmente | V | F | F | V | F | F | F | F |
| SOL-006 | Consultar solicitud radicada | V | V | V | V | V | V | V | F |
| SOL-007 | Descargar solicitud en PDF | V | V | V | V | V | V | V | F |
| SOL-008 | Duplicar solicitud | V | F | F | V | F | F | F | F |
| SOL-009 | Cancelar antes de revisión | V | F | F | V | F | F | F | F |
| SOL-010 | Consultar estado | V | V | V | V | V | V | V | F |

### Bloque 4 — Documentos adjuntos (SOL-031 a SOL-040)

| Código | Permiso | SUPERADM | ADM | AUX | EMP | AUD | COM | APR | PUB |
|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| SOL-031 | Subir documento requerido | V | F | F | V | F | F | F | F |
| SOL-032 | Reemplazar documento legal | V | F | F | V | F | F | F | F |
| SOL-033 | Eliminar documento técnico | V | F | F | V | F | F | F | F |
| SOL-034 | Descargar documento adjunto | V | V | V | V | V | V | V | F |
| SOL-035 | Consultar documento en visor | V | V | V | V | V | V | V | F |
| SOL-036 | Validar formato (Automático) | V | V | V | V | V | V | V | F |
| SOL-037 | Rechazar documento | V | V | V | F | F | F | F | F |
| SOL-038 | Aprobar documento adjunto | V | V | V | F | F | F | F | F |
| SOL-039 | Solicitar corrección | V | V | V | F | F | F | F | F |
| SOL-040 | Consultar historial documental | V | V | V | V | F | F | V | F |

**El patrón:** la empresa crea, modifica y adjunta; la administración revisa y
decide; los demás roles solo consultan; el rol público no accede a nada.

### Significado de los códigos

| Código | Significado | Cómo se implementa |
|---|---|---|
| `V` | Concedido | Acceso permitido |
| `F` | Denegado | Respuesta `403` |
| `REQ` | Requiere aprobación de un superior | Concedido y marcado en `permiso_nivel` |
| `SA` | Exclusivo del SuperAdministrador | Solo pasa si el rol es SuperAdministrador |

`REQ` y `SA` no aparecen en los bloques 1 y 4, pero el mecanismo ya está
construido porque los bloques 5, 6 y 7 sí los usan.

---

## 2. Archivos del módulo

```
modules/solicitudes/
├── solicitud_permissions.py   Matriz de permisos y dependencia de autorización
├── solicitud_schema.py        Modelos y estados del ciclo de vida
├── solicitud_service.py       Lógica del Bloque 1
├── solicitud_router.py        Endpoints del Bloque 1
├── solicitud_pdf.py           PDF de la solicitud (SOL-007)
├── solicitud_bootstrap.py     Secuencia, índices y siembra del rol Publico
├── documento_schema.py        Modelos del Bloque 4
├── documento_service.py       Lógica del Bloque 4
└── documento_router.py        Endpoints del Bloque 4

core/pdf.py                    Generador de PDF (librería estándar, sin dependencias)

static/empresa.html            Portal de la empresa, conectado a la API

tests/
├── fake_db.py                       Doble de base de datos en memoria
├── test_solicitudes_bloque1.py      Bloque 1
└── test_documentos_bloque4.py       Bloque 4
```

---

## 3. Endpoints

### Ciclo de vida

| Método | Ruta | Permiso |
|---|---|---|
| `POST` | `/solicitudes/` | SOL-001 crear |
| `POST` | `/solicitudes/borradores` | SOL-002 guardar borrador |
| `GET` | `/solicitudes/` | SOL-006 listar (filtrable por estado) |
| `GET` | `/solicitudes/{id}` | SOL-006 detalle |
| `GET` | `/solicitudes/{id}/estado` | SOL-010 estado y fechas |
| `GET` | `/solicitudes/{id}/pdf` | SOL-007 PDF |
| `PATCH` | `/solicitudes/{id}` | SOL-003 editar |
| `DELETE` | `/solicitudes/{id}` | SOL-004 borrado lógico |
| `POST` | `/solicitudes/{id}/radicar` | SOL-005 radicar |
| `POST` | `/solicitudes/{id}/duplicar` | SOL-008 duplicar |
| `POST` | `/solicitudes/{id}/cancelar` | SOL-009 cancelar |
| `GET` | `/solicitudes/normas` | catálogo de normas ISO |

### Documentos

| Método | Ruta | Permiso |
|---|---|---|
| `GET` | `/solicitudes/documentos/formatos-permitidos` | SOL-036 reglas de formato |
| `POST` | `/solicitudes/{id}/documentos` | SOL-031 subir |
| `GET` | `/solicitudes/{id}/documentos` | SOL-035 listar |
| `PUT` | `/solicitudes/{id}/documentos/{doc}` | SOL-032 reemplazar |
| `DELETE` | `/solicitudes/{id}/documentos/{doc}` | SOL-033 eliminar |
| `GET` | `/solicitudes/{id}/documentos/{doc}/descargar` | SOL-034 descargar |
| `GET` | `/solicitudes/{id}/documentos/{doc}/ver` | SOL-035 visor |
| `POST` | `/solicitudes/{id}/documentos/{doc}/aprobar` | SOL-038 aprobar |
| `POST` | `/solicitudes/{id}/documentos/{doc}/rechazar` | SOL-037 rechazar |
| `POST` | `/solicitudes/{id}/documentos/{doc}/solicitar-correccion` | SOL-039 corrección |
| `GET` | `/solicitudes/{id}/documentos/historial` | SOL-040 historial |

Son **23 endpoints**. SOL-001 y SOL-002 comparten implementación porque
describen la misma acción; se exponen aparte para que cada código de la matriz
tenga su ruta.

---

## 4. Ciclo de vida

```
                  SOL-001 / SOL-002
                         │
                         ▼
                    ┌──────────┐
      SOL-003 ─────►│ Borrador │◄───── SOL-008 (duplicar)
      SOL-004 ─────►└────┬─────┘
                         │ SOL-005 (radicar)
                         ▼
                   ┌───────────┐
                   │ Radicada  │
                   └─────┬─────┘
          SOL-009        │        (Bloque 6)
       ┌─────────────────┴────────────────┐
       ▼                                  ▼
 ┌────────────┐                    ┌──────────────┐
 │ Cancelada  │                    │ En revision  │
 └────────────┘                    └──────────────┘
```

### Reglas que impone el código

| Regla | Respuesta si se incumple |
|---|---|
| Solo se edita o elimina en `Borrador` | `409` |
| Radicar exige norma, alcance, empleados y sedes | `422` con los campos faltantes |
| Se cancela solo desde `Borrador` o `Radicada` | `409` |
| La cancelación exige motivo de 5 a 500 caracteres | `422` |
| Una empresa no ve ni toca solicitudes de otra | `404`, no `403` |
| Formato de archivo no permitido | `415` |
| Archivo de más de 10 MB | `413` |
| Documento repetido del mismo tipo | `409` (use SOL-032) |
| Reemplazar o eliminar un documento aprobado | `409` |

Ante una solicitud ajena se responde `404` en lugar de `403` a propósito: un
`403` confirmaría que esa solicitud existe.

### Número de radicado

Formato `SOL-<año>-<consecutivo de 6 dígitos>`, por ejemplo `SOL-2026-000042`.
El consecutivo sale de la secuencia PostgreSQL `solicitud_radicado_seq`, así
que sigue siendo único aunque dos empresas radiquen a la vez.

### Versionado de documentos

`documento_solicitud` guarda la versión vigente. Al reemplazar (SOL-032), la
anterior se copia a `historial_documento_solicitud` y la nueva sube de versión.
Nunca se pierde lo que la empresa presentó antes.

---

## 5. Base de datos

**No se creó ni alteró ninguna tabla.** Todo el esquema ya existía. El módulo
trabaja sobre `solicitud`, `documento_solicitud`,
`historial_documento_solicitud`, `historial_estado`, `user_empresa`, `empresa`
y `norma`.

Al arrancar, `preparar_modulo_solicitudes()` solo añade lo que faltaba, con
sentencias idempotentes y **en su propia sesión**, para no depender de que el
resto de la siembra inicial funcione:

- la secuencia `solicitud_radicado_seq`;
- tres índices parciales para los filtros del listado;
- el rol `Publico` en la tabla `rol`.

### De quién es cada solicitud

La titularidad **no** se resuelve por `usuario_creador` sino por `id_empresa`,
cruzando con `user_empresa`. Así, si varias personas de la misma empresa tienen
cuenta, todas ven las solicitudes de su empresa.

- Usuario vinculado a **una** empresa → se deduce automáticamente.
- Vinculado a **varias** → debe enviar `id_empresa` (`422` si no lo hace).
- **Sin** empresa activa → `409`, no puede crear solicitudes.

### Almacenamiento de archivos

Los archivos van a `storage/solicitudes/<id_solicitud>/` y en `url_archivo`
queda la ruta relativa. En disco el nombre del fichero es el id del documento,
nunca el nombre que envía el cliente, que se sanea y solo se usa para mostrar
y descargar.

`storage/` está en el `.gitignore`.

> **Para producción:** si el sistema pasa a varios servidores habrá que mover
> esto a un almacenamiento compartido. Solo hay que cambiar `_guardar_archivo`
> y `ruta_absoluta` en `documento_service.py`.

### Historial

Cada operación escribe en `historial_estado` con el estado resultante y una
observación del tipo `[SOL-005] por vanessa - Radicado asignado: ...`.

> **Pendiente para el Bloque 6:** `historial_estado` no tiene columna de
> usuario, así que la traza de *quién* va dentro del texto. SOL-055 (bitácora
> inmutable) debería añadir `usuario_id` y `permiso_codigo` como columnas
> propias. No se hizo aquí para no modificar una tabla compartida.

---

## 6. Roles

La hoja tiene **ocho columnas**, pero el sistema tiene **siete roles**: el
aprobador no es un rol aparte, **el aprobador es el administrador**.

| Columna | Rol en la tabla `rol` |
|---|---|
| SUPERADM | `Super Administrador` |
| ADM | `Administrador` |
| **APR** | `Administrador` — sin rol propio |
| AUX | `Auxiliar` |
| EMP | `Empresa` |
| AUD | `Auditor` |
| COM | `Comité` |
| PUB | `Publico` (lo crea el bootstrap) |

**Por qué fusionar APR con ADM es seguro:** revisando las 70 filas de M5, ADM y
APR difieren en 29, y en las 29 ADM es el más permisivo. No hay ninguna fila
donde APR conceda algo que ADM no conceda. En los bloques 1 y 4 son idénticas.

`ALIAS_ROLES` normaliza cómo se escriba el rol: `Comité`, `comite` y `COM`
resuelven al mismo, y `Aprobador` o `APR` resuelven a `Administrador`.

> **Supuestos abiertos:** el Excel no trae leyenda de siglas. `COM` se
> interpretó como *Comité de certificación* (por M8) y `PUB` como *Consulta
> pública* (por M11). Se corrigen en `ROLES_A_COLUMNA` y `ALIAS_ROLES`.

---

## 7. Lo que se tocó fuera de M5

Solo **tres archivos**, con el cambio mínimo. Sin estas correcciones nadie
puede autenticarse, así que M5 tampoco funcionaría.

| Archivo | Cambio | Por qué es imprescindible |
|---|---|---|
| `main.py` | Importa y registra los dos routers, y llama al bootstrap. **Solo añade líneas, no modifica ninguna.** | Es como se enchufa el módulo |
| `core/security.py` | `u.id` → `u.id_usuario` (1 línea) | La tabla `usuario` tiene como PK `id_usuario` y no existe columna `id`. `get_current_user` fallaba siempre, así que **todos** los endpoints autenticados devolvían 401 |
| `modules/auth/auth_service.py` | `_ahora()` devuelve UTC naive; `int(rol_id)` → `str(rol_id)` | `_ahora()` devolvía hora de Bogotá con zona y se comparaba contra fechas sin zona: el login daba 500. Y `rol_id` es UUID, así que `int()` reventaba en cuanto un usuario tenía rol |

Las tres se verificaron ejecutando las consultas contra la base de datos.

### Otros fallos detectados, **no corregidos aquí**

Se encontraron al auditar, pero pertenecen a módulos de otros integrantes:

| Módulo | Problema |
|---|---|
| M1 / M2 (`auth`, `users`, `roles`, `mfa`, `alejandra`) | Más referencias a la columna inexistente `usuario.id`, y esquemas que declaran `rol_id: int` cuando en la base es `UUID` |
| `modules/tareas/` | La tabla `tareas` no existe en esta base; sus endpoints dan 500. Parece código heredado de otro proyecto |
| `static/register.html`, `static/dashboard.html` | Envían `parseInt(uuid)` = `NaN` al crear usuarios o cambiar roles |
| `query_db.py` | **Usuario y contraseña de la base en texto plano**, ya en el historial de Git. Conviene rotar esas credenciales |
| `requirements.txt` | Guardado en UTF-16: `pip install -r` falla |
| `core/deps.py` | Importa `app.core.redis_client`, ruta que no existe |
| `main.py` | Registra `alejandra_router` dos veces |

El detalle de cada uno está en la rama `feature/M5-solicitudes-bloque1`, que
los tiene corregidos por si el equipo quiere aprovecharlos.

---

## 8. Cómo ejecutar los tests

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pytest

pytest tests/ -q
```

### Qué cubren los 175 tests

| Grupo | Tests | Qué comprueba |
|---|---|---|
| Conformidad con el Excel | 6 | Que la matriz del código sea idéntica a la hoja, celda por celda |
| Autorización Bloque 1 | 71 | 10 acciones × 7 roles, más el caso sin token |
| Ciclo de vida | 18 | Estados, radicado consecutivo, borrado lógico, aislamiento entre empresas, historial y PDF |
| Autorización Bloque 4 | 71 | 10 acciones × 7 roles |
| Documentos | 7 | Reglas de formato y saneado del nombre de archivo |
| *(del proyecto, ya existían)* | 2 | Comité de certificación |

El test `test_la_matriz_del_codigo_coincide_con_el_excel` lee directamente
`documentacion/permisos.xlsx`: si alguien cambia un permiso en la hoja y no lo
refleja en el código, la suite falla y señala la celda exacta.

Los tests no necesitan base de datos: usan el doble en memoria de
`tests/fake_db.py`.

---

## 9. Portal de la empresa

`static/empresa.html` estaba maquetado pero sin conectar: cero llamadas al
backend y los `<input type="file">` sin ningún manejador, por eso no guardaba
nada. Ahora:

- lista las solicitudes de la empresa con su estado;
- crea borradores, los radica y descarga el PDF;
- sube documentos, que **quedan guardados** y no se vuelven a pedir;
- al reemplazar uno, muestra la versión nueva;
- muestra el estado de revisión con las observaciones de la administración.

---

## 10. Qué sigue

| Bloque | Permisos | Tema |
|---|---|---|
| 2 | SOL-011 → 020 | Datos técnicos: norma, alcance, procesos, empleados |
| 3 | SOL-021 → 030 | Sedes de la solicitud |
| 5 | SOL-041 → 050 | Asignación de auditores (primeros `REQ` y `SA`) |
| 6 | SOL-051 → 060 | Trazabilidad, bitácora inmutable y cierre |
| 7 | SOL-061 → 070 | Cálculo del tiempo de auditoría |

El estado `En revision` ya está en el `Enum` pero ninguna acción lo asigna
todavía: eso llega con SOL-054, en el Bloque 6.

Para el Bloque 4 queda una decisión pendiente: **de dónde sale qué documentos
exige cada norma ISO**. Hoy la lista de tipos sugeridos es fija en
`documento_service.py`; cuando se decida, puede pasar a una tabla para que la
administración la edite.
