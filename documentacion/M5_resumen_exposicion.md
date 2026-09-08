# M5 — Gestión de Solicitudes · Chuleta

**Qué hice:** el módulo que gestiona la solicitud de certificación de una
empresa y los documentos que debe adjuntar.
**Números:** 23 endpoints · 20 permisos · 173 tests · 0 tablas nuevas.

---

## 1. Abre así (30 s)

> "Una empresa que quiere certificarse tiene que hacer dos cosas: **presentar
> una solicitud** diciendo qué norma ISO quiere y con qué alcance, y **adjuntar
> los documentos** que la respaldan. M5 cubre las dos: el trámite y sus papeles."

---

## 2. Lo más fuerte que tienes: la matriz de permisos (4 min)

**El problema:** el Excel define, para 70 acciones, qué puede hacer cada uno de
los 8 roles. Si esas reglas se escriben a mano dentro de cada endpoint, se
repiten, se contradicen y cuando el Excel cambia nadie se entera.

**Lo que hice:** la matriz vive en **un solo archivo**, escrita igual que la hoja:

```python
PERMISOS_M5 = {
    #                                    SUPERADM ADM AUX EMP AUD COM APR PUB
    "SOL-001": ("Crear solicitud",             (V,  F,  F,  V,  F,  F,  F,  F)),
    "SOL-005": ("Radicar solicitud",           (V,  F,  F,  V,  F,  F,  F,  F)),
}
```

Y cada endpoint solo declara qué permiso exige:

```python
usuario: dict = Depends(requiere_permiso("SOL-005"))
```

**El remate:** un test **abre `permisos.xlsx`** y compara celda por celda contra
el código. Si alguien cambia un permiso en la hoja y no lo lleva al programa,
la suite falla señalando la celda exacta.

> "La hoja de cálculo deja de ser un documento que se desactualiza y pasa a ser
> la fuente de verdad."

---

## 3. Tres decisiones que demuestran criterio (4 min)

**Una solicitud ajena responde `404`, no `403`.**
Un `403` confirmaría que esa solicitud existe. Probando radicados uno por uno,
una empresa podría deducir si un competidor está tramitando una certificación.

**La titularidad va por empresa, no por usuario.**
Si el gerente crea la solicitud y se va de vacaciones, su compañero de la misma
empresa la continúa. Con titularidad por usuario quedaría bloqueada.

**No creé ninguna tabla.**
El esquema ya existía. Cero tablas nuevas, cero columnas alteradas.
→ *Mi módulo no rompe a nadie.*

---

## 4. El ciclo de vida (3 min)

```
  Borrador ──radicar──► Radicada ──► Cancelada / En revisión
     ▲  │
     └──┘ editar, eliminar, duplicar
```

- Solo se edita o elimina en **Borrador**
- Radicar exige norma, alcance, empleados y sedes
- El radicado (`SOL-2026-000001`) sale de una **secuencia de PostgreSQL**: si
  dos empresas radican a la vez, cada una recibe un número distinto
- `SOL-004` **nunca borra**: marca `deleted_at`. Es un expediente, debe poder
  auditarse quién lo creó y quién lo descartó

---

## 5. Documentos (3 min)

**Versionado:** al reemplazar un documento, la versión anterior se archiva.

```
  documento_solicitud          historial_documento_solicitud
  │ camara v2  Pendiente │ ←── │ camara v1  Rechazado │
      (la vigente)              (lo que se presentó antes)
```

**Validación automática:** solo `.pdf .doc .docx .jpg .png`, máximo 10 MB.

**Seguridad:** el nombre que envía el usuario **nunca** construye la ruta real.
En disco el archivo se llama como su id. Si no, alguien podría subir un archivo
llamado `../../.env` y escribir fuera de la carpeta.

**Estados:** Pendiente → Aprobado / Rechazado / Corrección.
Un documento aprobado ya no se puede cambiar.

---

## 6. Demo en vivo (5 min)

Entrar en `/login` como **Empresa**:

1. **Nueva solicitud** → norma, alcance, empleados, sedes → *Guardar borrador*
2. **Documentos** → subir un PDF → **recargar**: sigue ahí
3. Subir otro del mismo tipo → aparece como **versión 2**
4. Intentar subir un `.exe` → **rechazado**
5. **Radicar** → `SOL-2026-000001`, ya no es editable
6. **PDF** → se descarga legible

**Para enseñar los permisos:** entrar como **Auditor** → ve la solicitud pero
**no puede crear ninguna** (`403`).

---

## 7. Cierra así (30 s)

> "Están hechos los bloques 1 y 4 de los siete. Faltan datos técnicos, sedes,
> asignación de auditores, trazabilidad y cálculo de tiempos. La matriz ya
> soporta los códigos `REQ` y `SA` que necesitan esos bloques."

---

## Si preguntan…

**"¿Y si cambia el Excel?"**
→ El test falla y señala la celda. Se actualiza una línea en un solo archivo.

**"¿Por qué 8 columnas y 7 roles?"**
→ El aprobador es el administrador, no es un rol aparte. Revisé las 70 filas:
ADM y APR difieren en 29 y en todas ADM es el más permisivo, así que unificarlos
no le quita permisos a nadie.

**"¿Y si falla la base al arrancar?"**
→ El módulo abre su propia sesión. Si falla otra parte de la siembra inicial,
M5 se prepara igual.

**"¿Cuántos tests?"**
→ 173, y ninguno necesita base de datos: usan un doble en memoria.

**"¿Qué falta?"**
→ Decidir de dónde sale qué documentos exige cada norma ISO. Hoy la lista está
fija en el código; puede pasar a una tabla para que la administración la edite.
