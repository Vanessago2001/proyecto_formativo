"""
M7 — AUDITORÍAS
Ejecución de la auditoría de campo (AUT-001 a AUT-010) y las jornadas de
trabajo en sitio (AUT-061 a AUT-066).

Trabaja sobre las tablas `auditoria` y `jornada_auditoria`, que ya existen.
Una auditoría nace cuando alguien la inicia sobre una solicitud que tiene
auditores asignados (lo que M5 dejó listo en su Bloque 5), pasa por
'En ejecucion' y termina cerrada o suspendida.

El expediente previo (AUT-007) no se copia: se arma leyendo lo que ya
registró M5 (empresa, sedes, alcance, procesos y documentos), para que el
auditor vea en una sola respuesta lo que necesita antes de entrar.
"""

from datetime import date, time
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ESTADO_EN_EJECUCION = "En ejecucion"
ESTADO_SUSPENDIDA = "Suspendida"
ESTADO_CERRADA = "Cerrada"
ESTADO_REABIERTA = "Reabierta"

ESTADOS_ABIERTOS = (ESTADO_EN_EJECUCION, ESTADO_REABIERTA)

COLUMNAS = """
    id_auditoria, id_solicitud, id_programacion, estado,
    fecha_inicio, fecha_fin, hora_inicio, hora_fin,
    observaciones_iniciales, observaciones_cierre, incidencias,
    bloqueada, id_usuario_creacion, fecha_creacion, fecha_cierre
"""

# La misma lista con el alias de la tabla, para las consultas con JOIN.
COLUMNAS_CON_ALIAS = ", ".join(
    f"a.{columna.strip()}" for columna in COLUMNAS.strip().split(",") if columna.strip()
)


class AuditoriaService:
    """Ciclo de la auditoría de campo y sus jornadas."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========================================================
    # AYUDANTES
    # ========================================================

    async def obtener(self, id_auditoria: UUID) -> dict:
        resultado = await self.db.execute(
            text(f"SELECT {COLUMNAS} FROM auditoria WHERE id_auditoria = :id;"),
            {"id": str(id_auditoria)},
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La auditoría no existe.",
            )
        return dict(fila)

    @staticmethod
    def exigir_abierta(auditoria: dict) -> None:
        """Nada se registra sobre una auditoría cerrada o bloqueada."""
        if auditoria.get("bloqueada"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La auditoría está bloqueada: su informe ya fue finalizado.",
            )
        if auditoria.get("estado") not in ESTADOS_ABIERTOS:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"La auditoría está '{auditoria.get('estado')}' y no admite registros.",
            )

    async def _solicitud_de(self, id_solicitud: UUID) -> dict:
        resultado = await self.db.execute(
            text("""
                SELECT s.id_solicitud, s.numero_radicado, s.estado, s.id_empresa,
                       s.alcance_certificacion, s.numero_empleados, s.numero_sedes,
                       s.persona_contacto, s.fecha_radicacion,
                       e.nombre AS empresa, e.nit, e.ciudad, e.direccion, e.correo,
                       n.codigo AS norma_codigo, n.nombre AS norma_nombre, n.version AS norma_version
                FROM solicitud s
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE s.id_solicitud = :id AND s.deleted_at IS NULL;
            """),
            {"id": str(id_solicitud)},
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La solicitud no existe o fue eliminada.",
            )
        return dict(fila)

    # ========================================================
    # AUT-001 · INICIAR LA AUDITORÍA DE CAMPO
    # ========================================================

    async def iniciar(
        self,
        id_solicitud: UUID,
        usuario: dict,
        id_programacion: UUID | None = None,
        observaciones: str | None = None,
    ) -> dict:
        await self._solicitud_de(id_solicitud)

        abierta = await self.db.execute(
            text("""
                SELECT id_auditoria FROM auditoria
                WHERE id_solicitud = :id_solicitud
                  AND estado = ANY(CAST(:abiertos AS VARCHAR[]));
            """),
            {"id_solicitud": str(id_solicitud), "abiertos": list(ESTADOS_ABIERTOS)},
        )
        if abierta.scalar() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esta solicitud ya tiene una auditoría en curso.",
            )

        asignados = await self.db.execute(
            text("""
                SELECT COUNT(*) FROM auditores_solicitud
                WHERE id_solicitud = :id_solicitud
                  AND estado_asignacion NOT IN ('Cancelada', 'Reasignado');
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        if not asignados.scalar():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La solicitud no tiene auditores asignados todavía.",
            )

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO auditoria (
                    id_solicitud, id_programacion, estado, fecha_inicio,
                    observaciones_iniciales, bloqueada, id_usuario_creacion, fecha_creacion
                )
                VALUES (
                    :id_solicitud, :id_programacion, :estado, CURRENT_DATE,
                    :observaciones, FALSE, :usuario, CURRENT_TIMESTAMP
                )
                RETURNING {COLUMNAS};
            """),
            {
                "id_solicitud": str(id_solicitud),
                "id_programacion": str(id_programacion) if id_programacion else None,
                "estado": ESTADO_EN_EJECUCION,
                "observaciones": observaciones,
                "usuario": str(usuario["id_usuario"]),
            },
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    async def listar(
        self, id_solicitud: UUID | None = None, estado: str | None = None
    ) -> list[dict]:
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_CON_ALIAS},
                       s.numero_radicado, e.nombre AS empresa
                FROM auditoria a
                LEFT JOIN solicitud s ON s.id_solicitud = a.id_solicitud
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                WHERE (CAST(:id_solicitud AS UUID) IS NULL
                       OR a.id_solicitud = CAST(:id_solicitud AS UUID))
                  AND (CAST(:estado AS VARCHAR) IS NULL
                       OR a.estado = CAST(:estado AS VARCHAR))
                ORDER BY a.fecha_creacion DESC;
            """),
            {"id_solicitud": str(id_solicitud) if id_solicitud else None, "estado": estado},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    # ========================================================
    # AUT-002 a AUT-007 · LO QUE EL AUDITOR CONSULTA ANTES
    # ========================================================

    async def expediente_previo(self, id_auditoria: UUID) -> dict:
        """
        AUT-002 a AUT-007 en una sola respuesta: la solicitud asignada, la
        empresa, sus sedes, el alcance, los procesos y los documentos.
        """
        auditoria = await self.obtener(id_auditoria)
        solicitud = await self._solicitud_de(auditoria["id_solicitud"])

        sedes = await self.db.execute(
            text("""
                SELECT se.id_sede, se.nombre_sede, se.direccion, se.ciudad,
                       se.departamento, se.es_principal, ss.estado AS estado_en_solicitud
                FROM solicitud_sede ss
                JOIN sede_empresa se ON se.id_sede = ss.id_sede
                WHERE ss.id_solicitud = :id_solicitud
                ORDER BY se.es_principal DESC, se.nombre_sede;
            """),
            {"id_solicitud": str(auditoria["id_solicitud"])},
        )
        procesos = await self.db.execute(
            text("""
                SELECT * FROM proceso_solicitud WHERE id_solicitud = :id_solicitud;
            """),
            {"id_solicitud": str(auditoria["id_solicitud"])},
        )
        documentos = await self.db.execute(
            text("""
                SELECT id_documento, tipo_documento, nombre_archivo, version, estado
                FROM documento_solicitud WHERE id_solicitud = :id_solicitud
                ORDER BY fecha_subida DESC;
            """),
            {"id_solicitud": str(auditoria["id_solicitud"])},
        )
        auditores = await self.db.execute(
            text("""
                SELECT a.id_auditor, a.especialidad, a.estado_asignacion,
                       COALESCE(u.nombre, u.correo) AS auditor
                FROM auditores_solicitud a
                LEFT JOIN usuario u ON u.id_usuario = a.id_auditor
                WHERE a.id_solicitud = :id_solicitud
                  AND a.estado_asignacion NOT IN ('Cancelada', 'Reasignado');
            """),
            {"id_solicitud": str(auditoria["id_solicitud"])},
        )

        return {
            "auditoria": auditoria,
            "solicitud": solicitud,                                    # AUT-002
            "empresa": {                                               # AUT-003
                "nombre": solicitud.get("empresa"),
                "nit": solicitud.get("nit"),
                "ciudad": solicitud.get("ciudad"),
                "direccion": solicitud.get("direccion"),
                "correo": solicitud.get("correo"),
                "persona_contacto": solicitud.get("persona_contacto"),
            },
            "sedes": [dict(f) for f in sedes.mappings().all()],        # AUT-004
            "alcance": {                                               # AUT-005
                "alcance_certificacion": solicitud.get("alcance_certificacion"),
                "norma": solicitud.get("norma_codigo"),
                "norma_nombre": solicitud.get("norma_nombre"),
                "version": solicitud.get("norma_version"),
                "numero_empleados": solicitud.get("numero_empleados"),
                "numero_sedes": solicitud.get("numero_sedes"),
            },
            "procesos": [dict(f) for f in procesos.mappings().all()],  # AUT-006
            "documentos": [dict(f) for f in documentos.mappings().all()],  # AUT-007
            "auditores": [dict(f) for f in auditores.mappings().all()],
        }

    # ========================================================
    # AUT-008 / AUT-009 · CONFIRMAR INICIO Y OBSERVACIONES
    # ========================================================

    async def confirmar_inicio(
        self, id_auditoria: UUID, usuario: dict, hora: time | None = None
    ) -> dict:
        auditoria = await self.obtener(id_auditoria)
        self.exigir_abierta(auditoria)

        if auditoria.get("hora_inicio"):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El inicio formal de esta auditoría ya estaba confirmado.",
            )

        resultado = await self.db.execute(
            text(f"""
                UPDATE auditoria
                SET hora_inicio = COALESCE(CAST(:hora AS TIME), LOCALTIME),
                    fecha_inicio = COALESCE(fecha_inicio, CURRENT_DATE)
                WHERE id_auditoria = :id
                RETURNING {COLUMNAS};
            """),
            {"hora": str(hora) if hora else None, "id": str(id_auditoria)},
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    async def registrar_observaciones_iniciales(
        self, id_auditoria: UUID, observaciones: str, usuario: dict
    ) -> dict:
        auditoria = await self.obtener(id_auditoria)
        self.exigir_abierta(auditoria)

        resultado = await self.db.execute(
            text(f"""
                UPDATE auditoria
                SET observaciones_iniciales = :observaciones
                WHERE id_auditoria = :id
                RETURNING {COLUMNAS};
            """),
            {"observaciones": observaciones, "id": str(id_auditoria)},
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    # ========================================================
    # AUT-010 · SUSPENDER POR ANOMALÍA
    # ========================================================

    async def suspender(self, id_auditoria: UUID, motivo: str, usuario: dict) -> dict:
        auditoria = await self.obtener(id_auditoria)
        self.exigir_abierta(auditoria)

        resultado = await self.db.execute(
            text(f"""
                UPDATE auditoria
                SET estado = :estado,
                    incidencias = COALESCE(incidencias || E'\\n', '') || :motivo
                WHERE id_auditoria = :id
                RETURNING {COLUMNAS};
            """),
            {"estado": ESTADO_SUSPENDIDA, "motivo": f"[Suspensión] {motivo}", "id": str(id_auditoria)},
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    async def reanudar(self, id_auditoria: UUID, usuario: dict) -> dict:
        auditoria = await self.obtener(id_auditoria)
        if auditoria["estado"] != ESTADO_SUSPENDIDA:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Solo se reanuda una auditoría suspendida.",
            )
        resultado = await self.db.execute(
            text(f"""
                UPDATE auditoria SET estado = :estado
                WHERE id_auditoria = :id
                RETURNING {COLUMNAS};
            """),
            {"estado": ESTADO_EN_EJECUCION, "id": str(id_auditoria)},
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    # ========================================================
    # AUT-061 a AUT-066 · JORNADAS EN SITIO
    # ========================================================

    async def abrir_jornada(
        self, id_auditoria: UUID, usuario: dict, fecha: date | None = None, hora: time | None = None
    ) -> dict:
        """AUT-061: hora de inicio en campo."""
        auditoria = await self.obtener(id_auditoria)
        self.exigir_abierta(auditoria)

        abierta = await self.db.execute(
            text("""
                SELECT id_jornada FROM jornada_auditoria
                WHERE id_auditoria = :id AND hora_fin IS NULL;
            """),
            {"id": str(id_auditoria)},
        )
        if abierta.scalar() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya hay una jornada abierta: ciérrela antes de abrir otra.",
            )

        resultado = await self.db.execute(
            text("""
                INSERT INTO jornada_auditoria (
                    id_auditoria, fecha, hora_inicio, estado, fecha_registro
                )
                VALUES (
                    :id_auditoria,
                    COALESCE(CAST(:fecha AS DATE), CURRENT_DATE),
                    COALESCE(CAST(:hora AS TIME), LOCALTIME),
                    'Abierta', CURRENT_TIMESTAMP
                )
                RETURNING id_jornada, id_auditoria, fecha, hora_inicio, hora_fin,
                          incidencias, observaciones, estado, fecha_registro;
            """),
            {
                "id_auditoria": str(id_auditoria),
                "fecha": str(fecha) if fecha else None,
                "hora": str(hora) if hora else None,
            },
        )
        await self.db.commit()
        return dict(resultado.mappings().first())

    async def cerrar_jornada(
        self,
        id_auditoria: UUID,
        id_jornada: UUID,
        usuario: dict,
        hora: time | None = None,
        incidencias: str | None = None,
        observaciones: str | None = None,
    ) -> dict:
        """AUT-062 (hora de finalización), AUT-064 (incidencias) y AUT-065."""
        auditoria = await self.obtener(id_auditoria)
        self.exigir_abierta(auditoria)

        resultado = await self.db.execute(
            text("""
                UPDATE jornada_auditoria
                SET hora_fin = COALESCE(CAST(:hora AS TIME), LOCALTIME),
                    incidencias = COALESCE(:incidencias, incidencias),
                    observaciones = COALESCE(:observaciones, observaciones),
                    estado = 'Cerrada'
                WHERE id_jornada = :id_jornada AND id_auditoria = :id_auditoria
                  AND hora_fin IS NULL
                RETURNING id_jornada, id_auditoria, fecha, hora_inicio, hora_fin,
                          incidencias, observaciones, estado, fecha_registro;
            """),
            {
                "hora": str(hora) if hora else None,
                "incidencias": incidencias,
                "observaciones": observaciones,
                "id_jornada": str(id_jornada),
                "id_auditoria": str(id_auditoria),
            },
        )
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La jornada no existe, no es de esta auditoría o ya estaba cerrada.",
            )
        await self.db.commit()
        return dict(fila)

    async def jornadas(self, id_auditoria: UUID) -> dict:
        """AUT-063: las jornadas y la duración total en horas."""
        await self.obtener(id_auditoria)
        resultado = await self.db.execute(
            text("""
                SELECT id_jornada, fecha, hora_inicio, hora_fin, incidencias,
                       observaciones, estado,
                       CASE
                           WHEN hora_fin IS NULL THEN NULL
                           ELSE EXTRACT(EPOCH FROM (hora_fin - hora_inicio)) / 3600
                       END AS horas
                FROM jornada_auditoria
                WHERE id_auditoria = :id
                ORDER BY fecha, hora_inicio;
            """),
            {"id": str(id_auditoria)},
        )
        filas = [dict(f) for f in resultado.mappings().all()]
        total = sum(float(f["horas"]) for f in filas if f["horas"] is not None)
        return {
            "jornadas": filas,
            "total_jornadas": len(filas),
            "horas_en_campo": round(total, 2),
        }
