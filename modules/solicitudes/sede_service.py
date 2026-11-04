"""
M5 — GESTIÓN DE SOLICITUDES
Lógica del Bloque 3 (sedes de la solicitud, SOL-021 a SOL-030).

Trabaja sobre tablas que ya existen en la base de datos:

  · `sede_empresa`   -> las sedes físicas de la empresa.
  · `solicitud_sede` -> qué sedes entran en cada solicitud y en qué estado.

Una sede es de la EMPRESA y puede reutilizarse en varias solicitudes; la
solicitud solo guarda el vínculo. De ahí salen las reglas:

  · SOL-021 incluye una sede ya registrada; SOL-024 registra una nueva con su
    dirección y la incluye.
  · Ciudad, departamento y país solo se indican al registrar la sede
    (SOL-026 y SOL-027 se verifican en ese momento). No se editan: si están
    mal, la sede se inactiva y se registra otra.
  · Quitar una sede (SOL-023) no la borra: el vínculo pasa a 'Excluida' y se
    reactiva si se vuelve a incluir. Inactivarla además la marca 'Inactiva'
    en la empresa para que no se vuelva a usar.
  · Los datos de una sede no se cambian si ya forma parte de otra solicitud
    radicada, porque se alteraría un expediente ya presentado.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from modules.solicitudes.sede_excel import generar_excel_sedes
from modules.solicitudes.sede_schema import (
    ESTADO_SEDE_ACTIVA,
    ESTADO_SEDE_INACTIVA,
    EstadoSedeSolicitud,
    SedeEditar,
    SedeNueva,
)
from modules.solicitudes.solicitud_permissions import exigir_permisos
from modules.solicitudes.solicitud_schema import EstadoSolicitud
from modules.solicitudes.solicitud_service import SolicitudService

COLUMNAS_SEDE_EMPRESA = """
    id_sede, id_empresa, nombre_sede, direccion, ciudad,
    departamento, pais, es_principal, estado
"""

# Sedes vigentes de una solicitud (todo menos las excluidas).
CONSULTA_SEDES_DE_SOLICITUD = """
    SELECT
        ss.id_solicitud_sede,
        ss.id_solicitud,
        ss.estado AS estado_en_solicitud,
        ss.fecha_registro AS fecha_inclusion,
        se.id_sede,
        se.nombre_sede,
        se.direccion,
        se.ciudad,
        se.departamento,
        se.pais,
        se.es_principal,
        se.estado AS estado_sede
    FROM solicitud_sede ss
    JOIN sede_empresa se ON se.id_sede = ss.id_sede
    WHERE ss.id_solicitud = :id_solicitud
      AND ss.estado <> :excluida
"""

# Datos que Administración exige en cada sede al validar (SOL-029).
CAMPOS_OBLIGATORIOS_DE_SEDE = ("direccion", "ciudad", "departamento")

PAIS_POR_DEFECTO = "Colombia"


class SedeService:
    """Operaciones sobre las sedes incluidas en una solicitud."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.solicitudes = SolicitudService(db)

    # ========================================================
    # AYUDANTES
    # ========================================================

    async def _listar_sedes(self, id_solicitud: UUID) -> list[dict]:
        resultado = await self.db.execute(
            text(CONSULTA_SEDES_DE_SOLICITUD + " ORDER BY se.es_principal DESC, se.nombre_sede;"),
            {
                "id_solicitud": str(id_solicitud),
                "excluida": EstadoSedeSolicitud.excluida.value,
            },
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def _sede_en_solicitud_o_404(self, id_solicitud: UUID, id_sede: UUID) -> dict:
        resultado = await self.db.execute(
            text(CONSULTA_SEDES_DE_SOLICITUD + " AND ss.id_sede = :id_sede;"),
            {
                "id_solicitud": str(id_solicitud),
                "id_sede": str(id_sede),
                "excluida": EstadoSedeSolicitud.excluida.value,
            },
        )
        fila = resultado.mappings().first()

        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La sede no forma parte de esta solicitud.",
            )

        return dict(fila)

    async def _sede_de_empresa_o_404(self, id_sede: UUID, id_empresa) -> dict:
        """
        Trae una sede validando que sea de la empresa de la solicitud.

        Si es de otra empresa se responde 404, igual que con las solicitudes,
        para no revelar que existe.
        """
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_SEDE_EMPRESA}
                FROM sede_empresa
                WHERE id_sede = :id_sede;
            """),
            {"id_sede": str(id_sede)},
        )
        fila = resultado.mappings().first()

        if not fila or str(fila["id_empresa"]) != str(id_empresa):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La sede no existe o no pertenece a la empresa de la solicitud.",
            )

        return dict(fila)

    async def _exigir_sede_no_comprometida(self, id_sede: UUID, id_solicitud: UUID) -> None:
        """Corta la operación si la sede ya está en otra solicitud presentada."""
        resultado = await self.db.execute(
            text("""
                SELECT COUNT(*)
                FROM solicitud_sede ss
                JOIN solicitud s ON s.id_solicitud = ss.id_solicitud
                WHERE ss.id_sede = :id_sede
                  AND ss.id_solicitud <> :id_solicitud
                  AND ss.estado <> :excluida
                  AND s.deleted_at IS NULL
                  AND s.estado NOT IN (:borrador, :cancelada);
            """),
            {
                "id_sede": str(id_sede),
                "id_solicitud": str(id_solicitud),
                "excluida": EstadoSedeSolicitud.excluida.value,
                "borrador": EstadoSolicitud.borrador.value,
                "cancelada": EstadoSolicitud.cancelada.value,
            },
        )

        if resultado.scalar():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La sede ya forma parte de otra solicitud radicada: no se puede "
                    "cambiar ni inactivar porque alteraría ese expediente."
                ),
            )

    async def _preparar_edicion(
        self,
        id_solicitud: UUID,
        id_sede: UUID,
        usuario: dict,
    ) -> tuple[dict, dict]:
        """Borrador propio + sede incluida + sede no comprometida."""
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)
        sede = await self._sede_en_solicitud_o_404(id_solicitud, id_sede)
        await self._exigir_sede_no_comprometida(id_sede, id_solicitud)
        return solicitud, sede

    async def _actualizar_sede(
        self,
        solicitud: dict,
        id_sede: UUID,
        cambios: dict,
        usuario: dict,
        detalle: str,
    ) -> dict:
        # Los nombres de columna salen del servicio o del modelo Pydantic.
        asignaciones = ", ".join(f"{campo} = :{campo}" for campo in cambios)

        await self.db.execute(
            text(f"""
                UPDATE sede_empresa
                SET {asignaciones}
                WHERE id_sede = :id_sede;
            """),
            {**cambios, "id_sede": str(id_sede)},
        )
        sede = await self._sede_en_solicitud_o_404(solicitud["id_solicitud"], id_sede)

        await self.solicitudes._registrar_historial(
            solicitud["id_solicitud"], solicitud["estado"], usuario, detalle
        )
        await self.db.commit()

        return sede

    async def _marcar_vinculo(self, id_solicitud_sede, estado: EstadoSedeSolicitud) -> None:
        await self.db.execute(
            text("""
                UPDATE solicitud_sede
                SET estado = :estado
                WHERE id_solicitud_sede = :id_solicitud_sede;
            """),
            {"estado": estado.value, "id_solicitud_sede": str(id_solicitud_sede)},
        )

    async def _incluir(self, solicitud: dict, sede: dict, usuario: dict, detalle: str) -> dict:
        """Crea o reactiva el vínculo sede-solicitud y lo deja en el historial."""
        id_solicitud = solicitud["id_solicitud"]
        id_sede = sede["id_sede"]

        resultado = await self.db.execute(
            text("""
                SELECT id_solicitud_sede, estado
                FROM solicitud_sede
                WHERE id_solicitud = :id_solicitud
                  AND id_sede = :id_sede;
            """),
            {"id_solicitud": str(id_solicitud), "id_sede": str(id_sede)},
        )
        vinculo = resultado.mappings().first()

        if vinculo and vinculo["estado"] != EstadoSedeSolicitud.excluida.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La sede ya está incluida en esta solicitud.",
            )

        if vinculo:
            # Se había quitado: se reactiva el mismo vínculo.
            await self.db.execute(
                text("""
                    UPDATE solicitud_sede
                    SET estado = :estado,
                        fecha_registro = NOW()
                    WHERE id_solicitud_sede = :id_solicitud_sede;
                """),
                {
                    "estado": EstadoSedeSolicitud.incluida.value,
                    "id_solicitud_sede": str(vinculo["id_solicitud_sede"]),
                },
            )
        else:
            await self.db.execute(
                text("""
                    INSERT INTO solicitud_sede (id_solicitud, id_sede, estado)
                    VALUES (:id_solicitud, :id_sede, :estado);
                """),
                {
                    "id_solicitud": str(id_solicitud),
                    "id_sede": str(id_sede),
                    "estado": EstadoSedeSolicitud.incluida.value,
                },
            )

        incluida = await self._sede_en_solicitud_o_404(id_solicitud, id_sede)

        await self.solicitudes._registrar_historial(
            id_solicitud, solicitud["estado"], usuario, detalle
        )
        await self.db.commit()

        return incluida

    # ========================================================
    # SOL-021 — INCLUIR UNA SEDE YA REGISTRADA
    # ========================================================

    async def disponibles(self, id_solicitud: UUID, usuario: dict) -> list[dict]:
        """
        Sedes activas de la empresa que todavía no están en la solicitud.

        Alimenta el selector de SOL-021, así que exige ese mismo permiso.
        """
        solicitud = await self.solicitudes._obtener_accesible_o_404(id_solicitud, usuario)
        await self.solicitudes._exigir_propiedad(solicitud, usuario)

        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_SEDE_EMPRESA}
                FROM sede_empresa se
                WHERE se.id_empresa = :id_empresa
                  AND se.estado = :activa
                  AND NOT EXISTS (
                      SELECT 1
                      FROM solicitud_sede ss
                      WHERE ss.id_sede = se.id_sede
                        AND ss.id_solicitud = :id_solicitud
                        AND ss.estado <> :excluida
                  )
                ORDER BY se.es_principal DESC, se.nombre_sede;
            """),
            {
                "id_empresa": str(solicitud["id_empresa"]),
                "activa": ESTADO_SEDE_ACTIVA,
                "id_solicitud": str(id_solicitud),
                "excluida": EstadoSedeSolicitud.excluida.value,
            },
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def incluir_existente(self, id_solicitud: UUID, id_sede: UUID, usuario: dict) -> dict:
        """SOL-021: incluye en la solicitud una sede activa de la empresa."""
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)
        sede = await self._sede_de_empresa_o_404(id_sede, solicitud["id_empresa"])

        if sede["estado"] != ESTADO_SEDE_ACTIVA:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"La sede '{sede['nombre_sede']}' está {sede['estado']} "
                    "y no puede incluirse en una solicitud."
                ),
            )

        return await self._incluir(
            solicitud, sede, usuario, f"Sede incluida: {sede['nombre_sede']}"
        )

    # ========================================================
    # SOL-024 — REGISTRAR SEDE NUEVA CON SU DIRECCIÓN
    # ========================================================

    async def registrar_nueva(self, id_solicitud: UUID, data: SedeNueva, usuario: dict) -> dict:
        """
        SOL-024: registra la sede en la empresa y la incluye en la solicitud.

        Es el único momento en que se indican ciudad (SOL-026), departamento
        (SOL-027) y país, así que se verifican esos permisos y el de incluir
        la sede (SOL-021).
        """
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)
        exigir_permisos(usuario, "SOL-021", "SOL-026", "SOL-027")

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO sede_empresa (
                    id_empresa, nombre_sede, direccion, ciudad,
                    departamento, pais, es_principal
                )
                VALUES (
                    :id_empresa, :nombre_sede, :direccion, :ciudad,
                    :departamento, :pais, :es_principal
                )
                RETURNING {COLUMNAS_SEDE_EMPRESA};
            """),
            {
                "id_empresa": str(solicitud["id_empresa"]),
                "nombre_sede": data.nombre_sede,
                "direccion": data.direccion,
                "ciudad": data.ciudad,
                "departamento": data.departamento,
                "pais": data.pais or PAIS_POR_DEFECTO,
                "es_principal": data.es_principal,
            },
        )
        sede = dict(resultado.mappings().one())

        return await self._incluir(
            solicitud,
            sede,
            usuario,
            f"Sede registrada: {sede['nombre_sede']} ({sede['ciudad']}, {sede['departamento']})",
        )

    # ========================================================
    # SOL-022 — EDITAR SEDE EN SOLICITUD
    # ========================================================

    async def editar(
        self,
        id_solicitud: UUID,
        id_sede: UUID,
        data: SedeEditar,
        usuario: dict,
    ) -> dict:
        """SOL-022: nombre o si es la sede principal."""
        solicitud, _ = await self._preparar_edicion(id_solicitud, id_sede, usuario)

        cambios = data.model_dump(exclude_unset=True, exclude_none=True)
        if not cambios:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "No se recibió ningún campo para actualizar. Ciudad, departamento "
                    "y país no se editan: inactive la sede y registre otra."
                ),
            )

        return await self._actualizar_sede(
            solicitud,
            id_sede,
            cambios,
            usuario,
            f"Sede editada ({', '.join(sorted(cambios))})",
        )

    # ========================================================
    # SOL-025 — EDITAR DIRECCIÓN DE SEDE
    # ========================================================

    async def editar_direccion(
        self,
        id_solicitud: UUID,
        id_sede: UUID,
        direccion: str,
        usuario: dict,
    ) -> dict:
        solicitud, sede = await self._preparar_edicion(id_solicitud, id_sede, usuario)

        return await self._actualizar_sede(
            solicitud,
            id_sede,
            {"direccion": direccion},
            usuario,
            f"Direccion de la sede '{sede['nombre_sede']}': {direccion}",
        )

    # ========================================================
    # SOL-023 — QUITAR O INACTIVAR
    # ========================================================

    async def eliminar(self, id_solicitud: UUID, id_sede: UUID, usuario: dict) -> dict:
        """
        SOL-023: quita la sede de la solicitud.

        Solo cambia el vínculo a 'Excluida'; la sede sigue activa en la empresa.
        """
        solicitud = await self.solicitudes._obtener_borrador_propio(id_solicitud, usuario)
        sede = await self._sede_en_solicitud_o_404(id_solicitud, id_sede)

        await self._marcar_vinculo(sede["id_solicitud_sede"], EstadoSedeSolicitud.excluida)

        await self.solicitudes._registrar_historial(
            id_solicitud,
            solicitud["estado"],
            usuario,
            f"Sede quitada: {sede['nombre_sede']}",
        )
        await self.db.commit()

        return {
            "id_sede": str(id_sede),
            "mensaje": "Sede quitada de la solicitud. Sigue registrada en la empresa.",
        }

    async def inactivar(self, id_solicitud: UUID, id_sede: UUID, usuario: dict) -> dict:
        """
        SOL-023: quita la sede de la solicitud y la marca 'Inactiva' en la empresa.

        Es el camino para corregir ciudad, departamento o país: la sede errada
        se inactiva y se registra otra (SOL-024).
        """
        solicitud, sede = await self._preparar_edicion(id_solicitud, id_sede, usuario)

        await self._marcar_vinculo(sede["id_solicitud_sede"], EstadoSedeSolicitud.excluida)
        await self.db.execute(
            text("""
                UPDATE sede_empresa
                SET estado = :estado
                WHERE id_sede = :id_sede;
            """),
            {"estado": ESTADO_SEDE_INACTIVA, "id_sede": str(id_sede)},
        )

        await self.solicitudes._registrar_historial(
            id_solicitud,
            solicitud["estado"],
            usuario,
            f"Sede inactivada: {sede['nombre_sede']}",
        )
        await self.db.commit()

        return {
            "id_sede": str(id_sede),
            "mensaje": "Sede inactivada. Registre una nueva si necesita otra ubicación.",
        }

    # ========================================================
    # SOL-028 — CONSULTAR SEDES AÑADIDAS
    # ========================================================

    async def listar(self, id_solicitud: UUID, usuario: dict) -> list[dict]:
        """SOL-028: sedes vigentes, la principal primero."""
        await self.solicitudes.consultar(id_solicitud, usuario)
        return await self._listar_sedes(id_solicitud)

    # ========================================================
    # SOL-029 — VALIDAR SEDES (ADMINISTRACIÓN)
    # ========================================================

    async def validar(self, id_solicitud: UUID, usuario: dict) -> dict:
        """
        SOL-029: Administración revisa las sedes de una solicitud radicada.

        Cada sede queda 'Validada' o 'Con observaciones' según tenga completos
        dirección, ciudad y departamento y siga activa en la empresa. Además se
        comprueba que haya sedes, que su número coincida con el declarado
        (SOL-019) y que exactamente una sea la principal.
        """
        solicitud = await self.solicitudes._obtener_accesible_o_404(id_solicitud, usuario)

        if solicitud["estado"] in (
            EstadoSolicitud.borrador.value,
            EstadoSolicitud.cancelada.value,
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Solo se validan las sedes de una solicitud radicada. "
                    f"Estado actual: {solicitud['estado']}."
                ),
            )

        sedes = await self._listar_sedes(id_solicitud)
        inconsistencias: list[str] = []
        revisadas: list[dict] = []

        for sede in sedes:
            faltantes = [
                campo
                for campo in CAMPOS_OBLIGATORIOS_DE_SEDE
                if not (sede.get(campo) or "").strip()
            ]
            inactiva = sede.get("estado_sede") == ESTADO_SEDE_INACTIVA

            if faltantes:
                inconsistencias.append(
                    f"La sede '{sede['nombre_sede']}' no tiene: {', '.join(faltantes)}."
                )
            if inactiva:
                inconsistencias.append(
                    f"La sede '{sede['nombre_sede']}' está inactiva en la empresa."
                )

            estado = (
                EstadoSedeSolicitud.con_observaciones
                if faltantes or inactiva
                else EstadoSedeSolicitud.validada
            )
            await self._marcar_vinculo(sede["id_solicitud_sede"], estado)

            revisadas.append(
                {
                    "id_sede": sede["id_sede"],
                    "nombre_sede": sede["nombre_sede"],
                    "estado_en_solicitud": estado.value,
                    "faltantes": faltantes,
                }
            )

        declarado = solicitud.get("numero_sedes")

        if not sedes:
            inconsistencias.append("La solicitud no tiene sedes incluidas.")
        else:
            if declarado is not None and declarado != len(sedes):
                inconsistencias.append(
                    f"Se declararon {declarado} sedes y se incluyeron {len(sedes)}."
                )

            principales = sum(1 for sede in sedes if sede.get("es_principal"))
            if principales != 1:
                inconsistencias.append(
                    f"Debe haber exactamente una sede principal y hay {principales}."
                )

        resumen = (
            "sin observaciones"
            if not inconsistencias
            else f"{len(inconsistencias)} observaciones"
        )
        await self.solicitudes._registrar_historial(
            id_solicitud,
            solicitud["estado"],
            usuario,
            f"Validacion de sedes: {resumen}",
        )
        await self.db.commit()

        return {
            "id_solicitud": solicitud["id_solicitud"],
            "valida": not inconsistencias,
            "numero_sedes_declarado": declarado,
            "sedes_incluidas": len(sedes),
            "inconsistencias": inconsistencias,
            "sedes": revisadas,
        }

    # ========================================================
    # SOL-030 — EXPORTAR SEDES A EXCEL
    # ========================================================

    async def exportar_excel(self, id_solicitud: UUID, usuario: dict) -> tuple[bytes, str]:
        """SOL-030: devuelve el .xlsx y el nombre de archivo sugerido."""
        solicitud = await self.solicitudes.consultar_ampliada(id_solicitud, usuario)
        sedes = await self._listar_sedes(id_solicitud)

        nombre = solicitud.get("numero_radicado") or f"borrador-{id_solicitud}"
        return generar_excel_sedes(solicitud, sedes), f"sedes-{nombre}.xlsx"
