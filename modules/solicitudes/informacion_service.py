"""
M5 — GESTIÓN DE SOLICITUDES
Lógica del Bloque 2 (información general, SOL-011 a SOL-020).

Trabaja sobre tablas que ya existen en la base de datos:

  · `solicitud`          -> norma ISO, número de empleados y de sedes.
  · `alcance_solicitud`  -> líneas del alcance técnico.
  · `proceso_solicitud`  -> procesos clave de la empresa.

En la hoja, "registrar" y "editar" son permisos distintos, así que se
separan igual que subir (SOL-031) y reemplazar (SOL-032) un documento:

  · Registrar -> el dato todavía no existe. Si ya existe responde 409 e
                 indica qué permiso usar para cambiarlo.
  · Editar    -> el dato ya existe. Si no existe responde 409 e indica qué
                 permiso usar para registrarlo.

Toda escritura exige que la solicitud siga en Borrador y sea de la empresa.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.solicitudes.informacion_schema import (
    AlcanceCrear,
    AlcanceEditar,
    EstadoRegistro,
    ProcesoCrear,
    ProcesoEditar,
)
from modules.solicitudes.sede_schema import EstadoSedeSolicitud
from modules.solicitudes.solicitud_service import (
    CAMPOS_OBLIGATORIOS_AL_RADICAR,
    COLUMNAS_SOLICITUD,
    SolicitudService,
)

COLUMNAS_ALCANCE = "id_alcance, id_solicitud, descripcion, estado, fecha_registro"
COLUMNAS_PROCESO = (
    "id_proceso, id_solicitud, nombre, descripcion, estado, fecha_registro"
)


def _conflicto(mensaje: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=mensaje)


def _cambios(data) -> dict:
    """Campos enviados en un cuerpo de edición; 400 si no llegó ninguno."""
    cambios = data.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    if not cambios:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se recibió ningún campo para actualizar.",
        )
    return cambios


class InformacionService:
    """Datos técnicos de la solicitud: norma, alcance, procesos y tamaño."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.solicitudes = SolicitudService(db)

    # ========================================================
    # AYUDANTES
    # ========================================================

    async def _actualizar_solicitud(
        self,
        id_solicitud: UUID,
        campo: str,
        valor,
        usuario: dict,
        detalle: str,
    ) -> dict:
        """
        Cambia un único campo de `solicitud` y lo deja en el historial.

        `campo` siempre sale del propio servicio, nunca del cliente.
        """
        resultado = await self.db.execute(
            text(f"""
                UPDATE solicitud
                SET {campo} = :{campo}
                WHERE id_solicitud = :id_solicitud
                RETURNING {COLUMNAS_SOLICITUD};
            """),
            {campo: valor, "id_solicitud": str(id_solicitud)},
        )
        actualizada = dict(resultado.mappings().one())

        await self.solicitudes._registrar_historial(
            id_solicitud, actualizada["estado"], usuario, detalle
        )
        await self.db.commit()

        return actualizada

    async def _obtener_norma_o_404(self, id_norma: UUID) -> dict:
        resultado = await self.db.execute(
            text("""
                SELECT id_norma, codigo, nombre, version
                FROM norma
                WHERE id_norma = :id_norma;
            """),
            {"id_norma": str(id_norma)},
        )
        fila = resultado.mappings().first()

        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La norma indicada no existe.",
            )

        return dict(fila)

    @staticmethod
    def _nombre_norma(norma: dict) -> str:
        return norma.get("codigo") or norma.get("nombre") or str(norma["id_norma"])

    async def _obtener_detalle_o_404(
        self,
        tabla: str,
        columnas: str,
        clave: str,
        id_detalle: UUID,
        id_solicitud: UUID,
        mensaje: str,
    ) -> dict:
        """Trae un alcance o un proceso, comprobando que sea de la solicitud."""
        resultado = await self.db.execute(
            text(f"""
                SELECT {columnas}
                FROM {tabla}
                WHERE {clave} = :{clave}
                  AND id_solicitud = :id_solicitud;
            """),
            {clave: str(id_detalle), "id_solicitud": str(id_solicitud)},
        )
        fila = resultado.mappings().first()

        if not fila:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=mensaje)

        return dict(fila)

    async def _actualizar_detalle(
        self,
        tabla: str,
        columnas: str,
        clave: str,
        id_detalle: UUID,
        cambios: dict,
    ) -> dict:
        # Los nombres de columna salen del modelo Pydantic, nunca del cliente.
        asignaciones = ", ".join(f"{campo} = :{campo}" for campo in cambios)

        resultado = await self.db.execute(
            text(f"""
                UPDATE {tabla}
                SET {asignaciones}
                WHERE {clave} = :{clave}
                RETURNING {columnas};
            """),
            {**cambios, clave: str(id_detalle)},
        )
        return dict(resultado.mappings().one())

    async def _listar_detalle(
        self,
        tabla: str,
        columnas: str,
        id_solicitud: UUID,
    ) -> list[dict]:
        resultado = await self.db.execute(
            text(f"""
                SELECT {columnas}
                FROM {tabla}
                WHERE id_solicitud = :id_solicitud
                ORDER BY fecha_registro;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    # ========================================================
    # SOL-011 / SOL-012 — NORMA ISO
    # ========================================================

    async def registrar_norma(
        self,
        id_solicitud: UUID,
        id_norma: UUID,
        usuario: dict,
    ) -> dict:
        """SOL-011: asigna la norma a una solicitud que todavía no tiene."""
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)

        if solicitud["id_norma"] is not None:
            raise _conflicto(
                "La solicitud ya tiene una norma ISO registrada. Para cambiarla "
                "use SOL-012 (editar norma ISO)."
            )

        norma = await self._obtener_norma_o_404(id_norma)

        return await self._actualizar_solicitud(
            id_solicitud,
            "id_norma",
            str(id_norma),
            usuario,
            f"Norma registrada: {self._nombre_norma(norma)}",
        )

    async def editar_norma(
        self,
        id_solicitud: UUID,
        id_norma: UUID,
        usuario: dict,
    ) -> dict:
        """SOL-012: cambia la norma ya registrada."""
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)

        if solicitud["id_norma"] is None:
            raise _conflicto(
                "La solicitud todavía no tiene norma ISO. Regístrela primero "
                "con SOL-011 (registrar norma ISO solicitada)."
            )

        norma = await self._obtener_norma_o_404(id_norma)

        return await self._actualizar_solicitud(
            id_solicitud,
            "id_norma",
            str(id_norma),
            usuario,
            f"Norma cambiada a: {self._nombre_norma(norma)}",
        )

    # ========================================================
    # SOL-013 / SOL-014 — ALCANCE TÉCNICO
    # ========================================================

    async def registrar_alcance(
        self,
        id_solicitud: UUID,
        data: AlcanceCrear,
        usuario: dict,
    ) -> dict:
        """SOL-013: añade una línea al alcance técnico de la solicitud."""
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO alcance_solicitud (id_solicitud, descripcion, estado)
                VALUES (:id_solicitud, :descripcion, :estado)
                RETURNING {COLUMNAS_ALCANCE};
            """),
            {
                "id_solicitud": str(id_solicitud),
                "descripcion": data.descripcion,
                "estado": EstadoRegistro.activo.value,
            },
        )
        alcance = dict(resultado.mappings().one())

        await self.solicitudes._registrar_historial(
            id_solicitud, solicitud["estado"], usuario, "Alcance tecnico registrado"
        )
        await self.db.commit()

        return alcance

    async def editar_alcance(
        self,
        id_solicitud: UUID,
        id_alcance: UUID,
        data: AlcanceEditar,
        usuario: dict,
    ) -> dict:
        """SOL-014: cambia la descripción o desactiva una línea del alcance."""
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)
        await self._obtener_detalle_o_404(
            "alcance_solicitud",
            COLUMNAS_ALCANCE,
            "id_alcance",
            id_alcance,
            id_solicitud,
            "El alcance no existe en esta solicitud.",
        )
        cambios = _cambios(data)

        alcance = await self._actualizar_detalle(
            "alcance_solicitud", COLUMNAS_ALCANCE, "id_alcance", id_alcance, cambios
        )

        await self.solicitudes._registrar_historial(
            id_solicitud,
            solicitud["estado"],
            usuario,
            f"Alcance editado ({', '.join(sorted(cambios))})",
        )
        await self.db.commit()

        return alcance

    # ========================================================
    # SOL-015 / SOL-016 — PROCESOS CLAVE
    # ========================================================

    async def _exigir_proceso_unico(
        self,
        id_solicitud: UUID,
        nombre: str,
        excluir: UUID | None = None,
    ) -> None:
        """No puede haber dos procesos activos con el mismo nombre."""
        consulta = """
            SELECT id_proceso
            FROM proceso_solicitud
            WHERE id_solicitud = :id_solicitud
              AND LOWER(nombre) = LOWER(:nombre)
              AND estado = :activo
        """
        parametros = {
            "id_solicitud": str(id_solicitud),
            "nombre": nombre,
            "activo": EstadoRegistro.activo.value,
        }

        if excluir is not None:
            consulta += " AND id_proceso <> :id_proceso"
            parametros["id_proceso"] = str(excluir)

        repetido = await self.db.execute(text(consulta + ";"), parametros)

        if repetido.scalar() is not None:
            raise _conflicto(
                f"Ya hay un proceso activo llamado '{nombre}' en esta solicitud."
            )

    async def registrar_proceso(
        self,
        id_solicitud: UUID,
        data: ProcesoCrear,
        usuario: dict,
    ) -> dict:
        """SOL-015: registra un proceso clave de la empresa."""
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)
        await self._exigir_proceso_unico(id_solicitud, data.nombre)

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO proceso_solicitud (
                    id_solicitud, nombre, descripcion, estado
                )
                VALUES (:id_solicitud, :nombre, :descripcion, :estado)
                RETURNING {COLUMNAS_PROCESO};
            """),
            {
                "id_solicitud": str(id_solicitud),
                "nombre": data.nombre,
                "descripcion": data.descripcion,
                "estado": EstadoRegistro.activo.value,
            },
        )
        proceso = dict(resultado.mappings().one())

        await self.solicitudes._registrar_historial(
            id_solicitud,
            solicitud["estado"],
            usuario,
            f"Proceso clave registrado: {data.nombre}",
        )
        await self.db.commit()

        return proceso

    async def editar_proceso(
        self,
        id_solicitud: UUID,
        id_proceso: UUID,
        data: ProcesoEditar,
        usuario: dict,
    ) -> dict:
        """SOL-016: cambia nombre o descripción, o desactiva el proceso."""
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)
        actual = await self._obtener_detalle_o_404(
            "proceso_solicitud",
            COLUMNAS_PROCESO,
            "id_proceso",
            id_proceso,
            id_solicitud,
            "El proceso no existe en esta solicitud.",
        )
        cambios = _cambios(data)

        # Si el proceso queda activo, su nombre no puede repetirse.
        nombre_final = cambios.get("nombre", actual["nombre"])
        estado_final = cambios.get("estado", actual["estado"])
        if estado_final == EstadoRegistro.activo.value:
            await self._exigir_proceso_unico(id_solicitud, nombre_final, excluir=id_proceso)

        proceso = await self._actualizar_detalle(
            "proceso_solicitud", COLUMNAS_PROCESO, "id_proceso", id_proceso, cambios
        )

        await self.solicitudes._registrar_historial(
            id_solicitud,
            solicitud["estado"],
            usuario,
            f"Proceso editado: {nombre_final} ({', '.join(sorted(cambios))})",
        )
        await self.db.commit()

        return proceso

    # ========================================================
    # SOL-017 / SOL-018 — NÚMERO DE EMPLEADOS
    # ========================================================

    async def registrar_numero_empleados(
        self,
        id_solicitud: UUID,
        numero: int,
        usuario: dict,
    ) -> dict:
        """SOL-017: registra el número de empleados si aún no se declaró."""
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)

        if solicitud["numero_empleados"] is not None:
            raise _conflicto(
                "La solicitud ya tiene registrado el número de empleados "
                f"({solicitud['numero_empleados']}). Para cambiarlo use SOL-018 "
                "(editar número de empleados)."
            )

        return await self._actualizar_solicitud(
            id_solicitud,
            "numero_empleados",
            numero,
            usuario,
            f"Numero de empleados registrado: {numero}",
        )

    async def editar_numero_empleados(
        self,
        id_solicitud: UUID,
        numero: int,
        usuario: dict,
    ) -> dict:
        """SOL-018: corrige el número de empleados ya declarado."""
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)
        anterior = solicitud["numero_empleados"]

        if anterior is None:
            raise _conflicto(
                "La solicitud todavía no tiene número de empleados. Regístrelo "
                "primero con SOL-017 (registrar número de empleados)."
            )

        return await self._actualizar_solicitud(
            id_solicitud,
            "numero_empleados",
            numero,
            usuario,
            f"Numero de empleados: {anterior} -> {numero}",
        )

    # ========================================================
    # SOL-019 — NÚMERO DE SEDES
    # ========================================================

    async def registrar_numero_sedes(
        self,
        id_solicitud: UUID,
        numero: int,
        usuario: dict,
    ) -> dict:
        """
        SOL-019: registra cuántas sedes declara la empresa.

        Es el número declarado; las sedes concretas se agregan en el Bloque 3 y
        SOL-029 comprueba que ambos coincidan.
        """
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)

        if solicitud["numero_sedes"] is not None:
            raise _conflicto(
                "La solicitud ya tiene registrado el número de sedes "
                f"({solicitud['numero_sedes']}). La hoja no define un permiso "
                "para editarlo por separado: corríjalo editando el borrador "
                "(SOL-003)."
            )

        return await self._actualizar_solicitud(
            id_solicitud,
            "numero_sedes",
            numero,
            usuario,
            f"Numero de sedes registrado: {numero}",
        )

    # ========================================================
    # SOL-020 — CONSULTAR INFORMACIÓN GENERAL
    # ========================================================

    async def informacion_general(self, id_solicitud: UUID, usuario: dict) -> dict:
        """
        SOL-020: la solicitud completa con sus detalles técnicos.

        Reúne empresa, norma, alcances, procesos y el número de sedes ya
        agregadas, y señala qué falta para poder radicar.
        """
        solicitud = await self.solicitudes.consultar_ampliada(id_solicitud, usuario)

        alcances = await self._listar_detalle(
            "alcance_solicitud", COLUMNAS_ALCANCE, id_solicitud
        )
        procesos = await self._listar_detalle(
            "proceso_solicitud", COLUMNAS_PROCESO, id_solicitud
        )

        sedes = await self.db.execute(
            text("""
                SELECT COUNT(*)
                FROM solicitud_sede
                WHERE id_solicitud = :id_solicitud
                  AND estado <> :excluida;
            """),
            {
                "id_solicitud": str(id_solicitud),
                "excluida": EstadoSedeSolicitud.excluida.value,
            },
        )

        return {
            **solicitud,
            "alcances": alcances,
            "procesos": procesos,
            "sedes_incluidas": sedes.scalar() or 0,
            "campos_pendientes": [
                campo
                for campo in CAMPOS_OBLIGATORIOS_AL_RADICAR
                if solicitud.get(campo) in (None, "")
            ],
        }
