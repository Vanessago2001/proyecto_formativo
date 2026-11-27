from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core import almacen_archivos
from core.security import _normalize_role_name
from modules.solicitudes import estado_solicitud as estados
from modules.solicitudes.solicitud_service import SolicitudService


# Quien administra ve y decide cualquier apelacion; el Comite solo las suyas.
ROLES_ADMINISTRACION = {"admin", "auxiliar"}

APELACION_EDITABLE = {"ENVIADA", "EN_REVISION", "INFORMACION_SOLICITADA"}
APELACION_FINAL = {"APROBADA", "RECHAZADA", "CANCELADA"}
# Estados de una apelación que ya tiene el fallo favorable a la empresa.
APELACION_FAVORABLE = {"APROBADA", "NOTIFICADA", "CERRADA"}
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
CARPETA_EVIDENCIAS = RAIZ_PROYECTO / "storage" / "apelaciones"
EXTENSIONES_EVIDENCIA = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}


TEXTO_ESTADO_APELACION = {
    "ENVIADA": "Enviada",
    "EN_REVISION": "En revisión",
    "INFORMACION_SOLICITADA": "Información solicitada",
    "APROBADA": "Aprobada",
    "RECHAZADA": "No aprobada",
    "CANCELADA": "Cancelada",
}


def texto_estado_apelacion(estado, fallo=None) -> str:
    """
    El estado de la apelación como lo lee la empresa. NOTIFICADA y CERRADA
    no dicen el resultado; se completa con el fallo (False = a favor).
    """
    clave = str(estado or "").strip().upper()
    if clave in {"NOTIFICADA", "CERRADA"}:
        etapa = "notificada" if clave == "NOTIFICADA" else "cerrada"
        if fallo is False:
            return f"Aprobada ({etapa})"
        if fallo is True:
            return f"No aprobada ({etapa})"
        return etapa.capitalize()
    return TEXTO_ESTADO_APELACION.get(clave, clave.capitalize() or "Sin estado")


def estado_es_rechazada(estado) -> bool:
    """
    Una solicitud rechazada es apelable, se haya escrito como se haya escrito.

    El Comite guardaba 'RECHAZADO' y M5 'Rechazada'; ahora las dos llegan al
    mismo valor por el catalogo de estados del proyecto.
    """
    return estados.es(estado, estados.RECHAZADA)


# La base solo admite estos tipos (restriccion chk_tipo_evidencia), asi que se
# traduce la extension del archivo a uno de ellos.
TIPOS_EVIDENCIA = {
    ".pdf": "Documento PDF",
    ".jpg": "Fotografía",
    ".jpeg": "Fotografía",
    ".png": "Fotografía",
    ".doc": "Informe Técnico",
    ".docx": "Informe Técnico",
}
TIPO_EVIDENCIA_POR_DEFECTO = "Otro"
TAMANO_MAXIMO_EVIDENCIA = 10 * 1024 * 1024


class ApelacionesService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _generar_radicado(self) -> str:
        result = await self.db.execute(text("SELECT nextval('apelacion_radicado_seq') AS siguiente;"))
        siguiente = result.scalar() or 1
        anio = datetime.now(timezone.utc).year
        return f"APE-{anio}-{siguiente:06d}"

    async def motivo_rechazo_del_comite(self, id_solicitud: UUID) -> str | None:
        """
        Texto con el que el Comité rechazó la solicitud.

        El Comité guarda cada acción en `comite_accion`, con el comentario
        dentro de la columna `datos`. Antes la apelación mostraba las
        observaciones de la solicitud, que son otra cosa.
        """
        resultado = await self.db.execute(
            text("""
                SELECT datos->>'comentario' AS comentario
                FROM comite_accion
                WHERE id_solicitud = :id_solicitud
                  AND accion IN ('rechazar', 'decision-definitiva', 'decisiones')
                  AND COALESCE(datos->>'comentario', '') <> ''
                ORDER BY
                    CASE WHEN accion = 'rechazar' THEN 0 ELSE 1 END,
                    fecha DESC
                LIMIT 1;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return resultado.scalar()

    async def contexto_de_solicitud(self, id_solicitud: UUID, usuario: dict) -> dict:
        """
        Lo que la pantalla de apelación necesita antes de crear una: si la
        solicitud se puede apelar y por qué fue rechazada.
        """
        solicitud = await SolicitudService(self.db).consultar(id_solicitud, usuario)
        motivo = await self.motivo_rechazo_del_comite(id_solicitud)
        return {
            "id_solicitud": str(id_solicitud),
            "numero_radicado": solicitud.get("numero_radicado"),
            "estado": solicitud.get("estado"),
            "apelable": estado_es_rechazada(solicitud.get("estado")),
            "motivo_rechazo": motivo or solicitud.get("observaciones"),
        }

    @staticmethod
    def _rol(usuario: dict | None) -> str:
        return _normalize_role_name((usuario or {}).get("role_name"))

    async def _esta_asignado(self, id_apelacion: UUID, usuario: dict) -> int | None:
        """
        None si no pertenece al comité de la apelación; 1 si pertenece y la
        puede ver; -1 si pertenece pero está impedido para la solicitud (la
        decidió en una ronda anterior o decidió OTRA apelación suya).
        """
        from modules.comite.imparcialidad import filtro_visible

        params: dict = {"id_apelacion": str(id_apelacion), "id_usuario": str(usuario.get("id_usuario"))}
        visible = filtro_visible(usuario, "a.id_solicitud", params, columna_apelacion_propia="a.id")
        condicion = visible.replace("AND", "", 1).strip() if visible else "TRUE"
        resultado = await self.db.execute(
            text(f"""
                SELECT CASE WHEN {condicion} THEN 1 ELSE -1 END
                FROM apelacion_comite ac
                JOIN apelacion a ON a.id = ac.id_apelacion
                WHERE ac.id_apelacion = :id_apelacion AND ac.id_usuario = :id_usuario;
            """),
            params,
        )
        return resultado.scalar()

    async def exigir_acceso(self, id_apelacion: UUID, usuario: dict) -> None:
        """
        Un miembro del Comité solo entra a las apelaciones que le asignaron.

        Antes cualquier cuenta con rol Comité podía ver y decidir todas, sin
        importar si pertenecía al comité de esa apelación.
        """
        if self._rol(usuario) != "comite":
            return
        acceso = await self._esta_asignado(id_apelacion, usuario)
        if acceso is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No pertenece al comité asignado a esta apelación.",
            )
        # Imparcialidad: impedido para la solicitud → 404, como si no existiera.
        if acceso == -1:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Apelación no encontrada.")

    async def miembros_que_evaluaron(self, id_solicitud: UUID) -> set[str]:
        """Usuarios del Comité que ya actuaron sobre la solicitud original."""
        resultado = await self.db.execute(
            text("""
                SELECT DISTINCT id_usuario
                FROM comite_accion
                WHERE id_solicitud = :id_solicitud
                  AND COALESCE(id_usuario, '') <> '';
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return {str(fila[0]) for fila in resultado.all()}

    async def nombres_de_usuarios(self, identificadores) -> dict[str, str]:
        """Nombre de cada usuario existente, para mensajes y validaciones."""
        valores = [str(i) for i in identificadores]
        if not valores:
            return {}
        resultado = await self.db.execute(
            text("""
                SELECT u.id_usuario, COALESCE(u.nombre, u.correo) AS nombre
                FROM usuario u
                WHERE u.id_usuario::TEXT = ANY(:identificadores);
            """),
            {"identificadores": valores},
        )
        return {str(fila["id_usuario"]): fila["nombre"] for fila in resultado.mappings().all()}

    async def miembros_del_comite(self, id_apelacion: UUID) -> list[dict]:
        resultado = await self.db.execute(
            text("""
                SELECT ac.id_usuario, u.nombre, u.correo, ac.asignado_en
                FROM apelacion_comite ac
                LEFT JOIN usuario u ON u.id_usuario = ac.id_usuario
                WHERE ac.id_apelacion = :id_apelacion
                ORDER BY ac.asignado_en;
            """),
            {"id_apelacion": str(id_apelacion)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def evaluacion_previa(self, id_solicitud: UUID) -> list[dict]:
        """Lo que el Comité hizo con la solicitud original, en orden."""
        resultado = await self.db.execute(
            text("""
                SELECT a.accion,
                       a.datos->>'comentario' AS comentario,
                       a.fecha,
                       COALESCE(u.nombre, u.correo, a.id_usuario) AS usuario
                FROM comite_accion a
                LEFT JOIN usuario u ON u.id_usuario::TEXT = a.id_usuario
                WHERE a.id_solicitud = :id_solicitud
                ORDER BY a.fecha;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        return [dict(fila) for fila in resultado.mappings().all()]

    async def comite_elegible(self, id_apelacion: UUID) -> list[dict]:
        """
        Auditores aprobados y miembros ya asignados a la apelación.

        Marca a quienes ya evaluaron la solicitud original (no pueden revisar
        su propia decisión) y a quienes ya están asignados a la apelación.
        """
        fila = await self.db.execute(
            text("SELECT id_solicitud FROM apelacion WHERE id = :id_apelacion;"),
            {"id_apelacion": str(id_apelacion)},
        )
        id_solicitud = fila.scalar()
        if id_solicitud is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="La apelación no existe.")

        evaluadores = await self.miembros_que_evaluaron(id_solicitud)
        asignados = {str(m["id_usuario"]) for m in await self.miembros_del_comite(id_apelacion)}

        # Los auditores nuevos deben tener postulación aprobada. Los miembros
        # ya asignados también se conservan aunque su rol haya cambiado a Comité.
        resultado = await self.db.execute(
            text("""
                SELECT u.id_usuario, u.nombre, u.correo, r.nombre AS rol
                FROM usuario u
                JOIN rol r ON r.id_rol = u.rol_id
                WHERE u.estado = 'Activo'
                  AND (
                      EXISTS (
                          SELECT 1
                          FROM apelacion_comite ac
                          WHERE ac.id_apelacion = :id_apelacion
                            AND ac.id_usuario = u.id_usuario
                      )
                      OR (
                          LOWER(r.nombre) LIKE 'auditor%'
                          AND u.estado_auditor = 'Activo'
                          AND EXISTS (
                              SELECT 1
                              FROM postulacion_auditor pa
                              WHERE pa.id_usuario = u.id_usuario
                                AND LOWER(pa.estado) IN ('aprobado', 'aprobada')
                          )
                      )
                  )
                ORDER BY r.nombre, u.nombre;
            """),
            {"id_apelacion": str(id_apelacion)},
        )
        miembros = []
        for fila in resultado.mappings().all():
            identificador = str(fila["id_usuario"])
            if identificador in evaluadores:
                continue
            es_comite = (fila["rol"] or "").lower().startswith("comit")
            miembros.append({
                "id_usuario": identificador,
                "nombre": fila["nombre"],
                "correo": fila["correo"],
                "rol_actual": fila["rol"],
                "necesita_cambio_de_rol": not es_comite,
                "ya_evaluo": identificador in evaluadores,
                "asignado": identificador in asignados,
            })
        return miembros

    async def expediente_apelacion(self, id_apelacion: UUID, usuario: dict) -> dict:
        """
        Todo lo que el comité de la apelación necesita para decidir: la
        solicitud original, la evaluación previa, la apelación y sus evidencias.
        """
        apelacion = await self.get_apelacion_by_id(id_apelacion, usuario)
        if not apelacion:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Apelación no encontrada.")

        id_solicitud = UUID(str(apelacion["id_solicitud"]))
        solicitud = await SolicitudService(self.db).consultar_ampliada(id_solicitud, usuario)
        return {
            "apelacion": apelacion,
            "solicitud_original": solicitud,
            "evaluacion_previa": await self.evaluacion_previa(id_solicitud),
            "evidencias": await self.get_evidencias_previas(id_apelacion, usuario),
            "comite_asignado": await self.miembros_del_comite(id_apelacion),
        }

    async def create_apelacion(self, data: dict, usuario: dict) -> dict:
        id_solicitud = UUID(str(data["id_solicitud"]))
        solicitudes = SolicitudService(self.db)
        solicitud = await solicitudes.consultar(id_solicitud, usuario)
        await solicitudes._exigir_propiedad(solicitud, usuario)
        if not estado_es_rechazada(solicitud.get("estado")):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Solo se puede apelar una solicitud en estado Rechazada.",
            )

        existente = await self.db.execute(
            text("SELECT id FROM apelacion WHERE id_solicitud = :id_solicitud;"),
            {"id_solicitud": id_solicitud},
        )
        if existente.scalar() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Esta solicitud ya tiene una apelación registrada.",
            )

        codigo = await self._generar_radicado()
        usuario_id = UUID(str(usuario["id_usuario"]))
        # El motivo que vera la empresa es el que escribio el Comite al rechazar.
        razones_rechazo = (
            await self.motivo_rechazo_del_comite(id_solicitud)
            or solicitud.get("observaciones")
            or data.get("razones_rechazo")
        )
        payload = {
            "id_solicitud": id_solicitud,
            "id_usuario_presenta": usuario_id,
            "id_empresa": UUID(str(solicitud["id_empresa"])),
            "estado": "ENVIADA",
            "radicado": codigo,
            "motivo": data.get("motivo"),
            "razones_rechazo": razones_rechazo or data.get("fallo"),
            "fallo": bool(data.get("fallo", False)),
        }

        query = text("""
            INSERT INTO apelacion (
                id, id_solicitud, id_usuario_presenta, id_empresa, estado, radicado,
                fecha, motivo, razones_rechazo, fallo
            )
            VALUES (
                gen_random_uuid(), :id_solicitud, :id_usuario_presenta, :id_empresa, :estado, :radicado,
                CURRENT_TIMESTAMP, :motivo, :razones_rechazo, :fallo
            )
            RETURNING id, id_solicitud, id_empresa, estado,
                      radicado, fecha, motivo, razones_rechazo, fallo;
        """)
        try:
            result = await self.db.execute(query, payload)
        except IntegrityError as exc:
            await self.db.rollback()
            # Solo es duplicado si choca con la unicidad por solicitud; cualquier
            # otro fallo de integridad se deja ver tal cual, en vez de disfrazarlo.
            origen = getattr(exc, "orig", None)
            if getattr(origen, "sqlstate", None) == "23505":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="La solicitud ya tiene una apelación registrada.",
                ) from exc
            raise
        await self.db.commit()
        row = result.mappings().first()
        return {**dict(row), "numero_radicado": solicitud.get("numero_radicado")} if row else None

    async def add_evidence(
        self,
        id_apelacion: UUID,
        archivo: UploadFile,
        descripcion: str | None,
        usuario: dict,
    ) -> dict:
        apelacion = await self.get_apelacion_by_id(id_apelacion, usuario)
        if not apelacion:
            return None
        if apelacion.get("estado") not in APELACION_EDITABLE:
            raise HTTPException(status_code=409, detail="La apelación ya no admite evidencias.")

        nombre = Path(archivo.filename or "evidencia").name
        extension = Path(nombre).suffix.lower()
        contenido = await archivo.read()
        if extension not in EXTENSIONES_EVIDENCIA:
            raise HTTPException(status_code=415, detail="Formato no permitido para evidencia.")
        if not contenido:
            raise HTTPException(status_code=400, detail="El archivo está vacío.")
        if len(contenido) > TAMANO_MAXIMO_EVIDENCIA:
            raise HTTPException(status_code=413, detail="El tamaño máximo permitido es 10 MB.")

        carpeta = CARPETA_EVIDENCIAS / str(id_apelacion)
        carpeta.mkdir(parents=True, exist_ok=True)
        nombre_disco = f"{uuid4()}{extension}"
        destino = carpeta / nombre_disco
        ruta_relativa = str(destino.relative_to(RAIZ_PROYECTO))
        # Disco local + base compartida (la fila queda en esta misma transacción).
        await almacen_archivos.guardar(
            ruta_relativa, contenido, db=self.db, disco=destino, nombre=nombre, usuario=usuario
        )
        payload = {
            "id_apelacion": id_apelacion,
            "id_usuario_subio": UUID(str(usuario["id_usuario"])),
            "nombre_archivo": nombre,
            "tipo_evidencia": TIPOS_EVIDENCIA.get(extension, TIPO_EVIDENCIA_POR_DEFECTO),
            "url_archivo": ruta_relativa,
            "descripcion": descripcion,
        }

        query = text("""
            INSERT INTO evidencia_apelacion (
                id_apelacion, id_usuario_subio, nombre_archivo, tipo_evidencia,
                url_archivo, descripcion, fecha_subida
            )
            VALUES (
                :id_apelacion, :id_usuario_subio, :nombre_archivo, :tipo_evidencia,
                :url_archivo, :descripcion, CURRENT_TIMESTAMP
            )
            RETURNING id_evidencia, id_apelacion, id_usuario_subio AS id_usuario,
                      nombre_archivo, tipo_evidencia, url_archivo, descripcion, fecha_subida;
        """)
        try:
            result = await self.db.execute(query, payload)
            await self.db.commit()
            row = result.mappings().first()
            return dict(row) if row else None
        except Exception:
            destino.unlink(missing_ok=True)
            await self.db.rollback()
            raise

    async def add_evidences(
        self, id_apelacion: UUID, archivos: list, descripcion: str | None, usuario: dict
    ) -> dict:
        """
        Adjunta varios documentos de una vez, sin tocar los que ya estaban.

        Cada archivo se añade como una evidencia más: el botón de adjuntar
        suma, nunca reemplaza. Si el Comité había pedido documentos, la
        entrega los da por atendidos.
        """
        if not archivos:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se recibió ningún archivo.",
            )

        agregadas = []
        for archivo in archivos:
            agregadas.append(await self.add_evidence(id_apelacion, archivo, descripcion, usuario))

        atendidos = await self._atender_requerimientos(id_apelacion)
        await self.db.commit()

        return {
            "agregadas": len(agregadas),
            "evidencias": agregadas,
            "requerimientos_atendidos": atendidos,
        }

    async def update_apelacion(self, id_apelacion: UUID, data: dict, usuario: dict) -> dict:
        existing = await self.get_apelacion_by_id(id_apelacion, usuario)
        if not existing:
            return None
        if existing.get("estado") not in APELACION_EDITABLE:
            return None

        payload = {
            "id": id_apelacion,
            "motivo": data.get("motivo", existing.get("motivo")),
        }

        query = text("""
            UPDATE apelacion
            SET motivo = :motivo
            WHERE id = :id
            RETURNING id, id_solicitud, id_empresa,
                      estado, radicado, fecha, motivo, razones_rechazo, fallo;
        """)
        result = await self.db.execute(query, payload)
        await self.db.commit()
        row = result.mappings().first()
        return {**dict(row), "numero_radicado": existing.get("numero_radicado")} if row else None

    async def get_all_apelaciones(self, usuario: dict) -> list[dict]:
        from modules.solicitudes.solicitud_permissions import normalizar_rol, ROL_EMP

        filtro_empresa = normalizar_rol(usuario.get("role_name")) == ROL_EMP
        solo_asignadas = self._rol(usuario) == "comite"
        # Imparcialidad: al miembro del Comité impedido para la solicitud no le
        # aparecen sus apelaciones (sí la que él mismo decidió, para cerrarla).
        from modules.comite.imparcialidad import filtro_visible

        params_imp: dict = {}
        oculto = filtro_visible(usuario, "a.id_solicitud", params_imp, columna_apelacion_propia="a.id")
        query = text(f"""
            SELECT a.id, a.id_solicitud,
                   a.id_empresa, a.estado, a.radicado, a.fecha, a.motivo,
                   a.razones_rechazo, a.fallo,
                   -- Para la lista "Por asignar comité" del Coordinador.
                   (SELECT COUNT(*) FROM apelacion_comite ac2 WHERE ac2.id_apelacion = a.id) AS comite_asignados
            FROM apelacion a
            WHERE (NOT :filtro_empresa OR a.id_solicitud IN (
                SELECT s.id_solicitud
                FROM solicitud s
                JOIN user_empresa ue ON ue.id_empresa = s.id_empresa
                WHERE ue.id_usuario::TEXT = :id_usuario AND ue.estado = 'Activo'
            ))
              AND (NOT :solo_asignadas OR a.id IN (
                SELECT ac.id_apelacion FROM apelacion_comite ac
                WHERE ac.id_usuario::TEXT = :id_usuario
            )){oculto}
            ORDER BY a.fecha DESC, a.id DESC;
        """)
        result = await self.db.execute(query, {
            "filtro_empresa": filtro_empresa,
            "solo_asignadas": solo_asignadas,
            "id_usuario": str(usuario.get("id_usuario")),
            **params_imp,
        })
        return [dict(row) for row in result.mappings().all()]

    async def mis_apelaciones(self, usuario: dict) -> list[dict]:
        """
        Portal de la empresa: sus apelaciones con lo que necesita saber de
        cada una (estado, requerimientos pendientes, decisión y en qué va la
        solicitud y el certificado). Solo las de empresas a las que el usuario
        está asociado y activo en user_empresa.
        """
        resultado = await self.db.execute(text("""
            SELECT a.id, a.id_solicitud, a.radicado, a.estado, a.fecha, a.fallo,
                   a.fecha_decision, a.observaciones,
                   s.numero_radicado, s.estado AS estado_solicitud,
                   e.nombre AS empresa,
                   (SELECT COUNT(*) FROM requerimiento_apelacion r
                     WHERE r.id_apelacion = a.id AND r.estado = 'Pendiente') AS requerimientos_pendientes,
                   cert.codigo_verificacion AS certificado_codigo,
                   TRIM(cert.estado_certificado) AS certificado_estado
            FROM apelacion a
            JOIN solicitud s ON s.id_solicitud = a.id_solicitud AND s.deleted_at IS NULL
            JOIN empresa e ON e.id_empresa = s.id_empresa
            LEFT JOIN LATERAL (
                SELECT c.codigo_verificacion, c.estado_certificado
                FROM certificado c
                WHERE c.id_solicitud = a.id_solicitud
                ORDER BY c.fecha_registro DESC NULLS LAST
                LIMIT 1
            ) cert ON TRUE
            WHERE s.id_empresa IN (
                SELECT ue.id_empresa FROM user_empresa ue
                WHERE ue.id_usuario::TEXT = :id_usuario AND ue.estado = 'Activo'
            )
            ORDER BY a.fecha DESC, a.id DESC;
        """), {"id_usuario": str(usuario.get("id_usuario"))})
        filas = []
        for fila in resultado.mappings().all():
            fila = dict(fila)
            estado = str(fila.get("estado") or "").upper()
            # Registros antiguos: el pedido de documentos quedó solo en el
            # estado, sin fila en requerimiento_apelacion.
            if estado == "INFORMACION_SOLICITADA" and not fila["requerimientos_pendientes"]:
                fila["requerimientos_pendientes"] = 1
            fila["estado_texto"] = texto_estado_apelacion(estado, fila.get("fallo"))
            filas.append(fila)
        return filas

    async def get_apelacion_by_id(self, id_apelacion: UUID, usuario: dict | None = None) -> dict:
        query = text("""
            SELECT id, id_solicitud,
                   (SELECT s.numero_radicado FROM solicitud s
                    WHERE s.id_solicitud = apelacion.id_solicitud) AS numero_radicado,
                   id_empresa, id_auditor_evaluador, estado, radicado, fecha,
                   motivo, razones_rechazo, fallo, observaciones, fecha_decision
            FROM apelacion
            WHERE id = :id_apelacion;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        row = result.mappings().first()
        appeal = dict(row) if row else None
        if appeal and usuario:
            await self.exigir_acceso(id_apelacion, usuario)
        if appeal and usuario and appeal.get("id_solicitud"):
            try:
                await SolicitudService(self.db).consultar(UUID(str(appeal["id_solicitud"])), usuario)
            except (ValueError, HTTPException):
                return None
        return appeal

    async def assign_committee(self, id_apelacion: UUID, miembros_comite: list[UUID], id_auditor_evaluador: UUID | None = None) -> dict:
        if not miembros_comite:
            raise ValueError("Debe indicar al menos un miembro del comité.")
        if id_auditor_evaluador is not None and any(miembro == id_auditor_evaluador for miembro in miembros_comite):
            raise ValueError("No se puede asignar un auditor que evaluó la solicitud original al comité de apelación.")

        fila = await self.db.execute(
            text("SELECT id_solicitud FROM apelacion WHERE id = :id_apelacion;"),
            {"id_apelacion": id_apelacion},
        )
        id_solicitud = fila.scalar()
        if id_solicitud is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La apelación no existe.",
            )

        # Sin esto, un identificador inexistente rompía con un error de llave
        # foránea que llegaba a la pantalla como "error interno".
        nombres = await self.nombres_de_usuarios(miembros_comite)
        desconocidos = [str(m) for m in miembros_comite if str(m) not in nombres]
        if desconocidos:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No existe el usuario " + ", ".join(desconocidos),
            )

        auditores_no_aprobados = await self.db.execute(
            text("""
                SELECT u.id_usuario
                FROM usuario u
                JOIN rol r ON r.id_rol = u.rol_id
                WHERE u.id_usuario::TEXT = ANY(:miembros)
                  AND LOWER(r.nombre) LIKE 'auditor%'
                  AND (
                    COALESCE(u.estado, '') <> 'Activo'
                    OR COALESCE(u.estado_auditor, '') <> 'Activo'
                    OR NOT EXISTS (
                        SELECT 1
                        FROM postulacion_auditor pa
                        WHERE pa.id_usuario = u.id_usuario
                          AND LOWER(pa.estado) IN ('aprobado', 'aprobada')
                    )
                  );
            """),
            {"miembros": [str(m) for m in miembros_comite]},
        )
        no_aprobados = [str(fila["id_usuario"]) for fila in auditores_no_aprobados.mappings().all()]
        if no_aprobados:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo se pueden asignar auditores activos con postulación aprobada.",
            )

        # La apelación la revisa un comité distinto al que evaluó la solicitud.
        evaluadores = await self.miembros_que_evaluaron(id_solicitud)
        repetidos = [str(m) for m in miembros_comite if str(m) in evaluadores]
        if repetidos:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El comité de la apelación debe ser distinto al que evaluó la "
                    "solicitud original. Ya participaron: "
                    + ", ".join(nombres.get(m, m) for m in repetidos)
                ),
            )

        # Si no se indica, se toma de la base quién evaluó, para dejar la traza.
        if id_auditor_evaluador is None and evaluadores:
            id_auditor_evaluador = sorted(evaluadores)[0]

        # Quien va a resolver una apelación necesita el rol Comité: si viene
        # como Auditor, se le cambia aquí. Se devuelve la lista de cambios
        # para que la pantalla lo diga y quede claro qué se modificó.
        cambios_de_rol = await self._asegurar_rol_comite(miembros_comite)

        await self.db.execute(
            text("DELETE FROM apelacion_comite WHERE id_apelacion = :id_apelacion;"),
            {"id_apelacion": id_apelacion},
        )

        for miembro in miembros_comite:
            await self.db.execute(
                text("""
                    INSERT INTO apelacion_comite (id_apelacion, id_usuario, asignado_en)
                    VALUES (:id_apelacion, :id_usuario, CURRENT_TIMESTAMP)
                """),
                {"id_apelacion": id_apelacion, "id_usuario": miembro},
            )

        await self.db.execute(
            text("""
                UPDATE apelacion
                SET id_auditor_evaluador = :id_auditor_evaluador,
                    estado = CASE
                        WHEN estado IN ('ENVIADA', 'INFORMACION_SOLICITADA') THEN 'EN_REVISION'
                        ELSE estado
                    END
                WHERE id = :id_apelacion;
            """),
            {"id_apelacion": id_apelacion, "id_auditor_evaluador": id_auditor_evaluador},
        )

        await self.db.commit()
        return {
            "id_apelacion": id_apelacion,
            "miembros_comite": miembros_comite,
            "cambios_de_rol": cambios_de_rol,
        }

    async def _asegurar_rol_comite(self, miembros) -> list[dict]:
        """
        Pasa a Comité a los miembros que todavía son Auditores.

        Solo se toca a quien se está asignando, y se deja constancia del rol
        que tenía: cambiar un rol no es inocuo y tiene que poder revisarse.
        """
        identificadores = [str(m) for m in miembros]
        if not identificadores:
            return []

        resultado = await self.db.execute(
            text("""
                SELECT u.id_usuario, COALESCE(u.nombre, u.correo) AS nombre, r.nombre AS rol
                FROM usuario u
                JOIN rol r ON r.id_rol = u.rol_id
                WHERE u.id_usuario::TEXT = ANY(:identificadores)
                  AND LOWER(r.nombre) NOT LIKE 'comit%';
            """),
            {"identificadores": identificadores},
        )
        por_cambiar = [dict(fila) for fila in resultado.mappings().all()]
        if not por_cambiar:
            return []

        id_rol_comite = (await self.db.execute(
            text("SELECT id_rol FROM rol WHERE LOWER(nombre) LIKE 'comit%' LIMIT 1;")
        )).scalar()
        if id_rol_comite is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No existe el rol Comité en la base de datos.",
            )

        cambios = []
        for usuario in por_cambiar:
            await self.db.execute(
                text("UPDATE usuario SET rol_id = :id_rol WHERE id_usuario = :id_usuario;"),
                {"id_rol": id_rol_comite, "id_usuario": usuario["id_usuario"]},
            )
            cambios.append({
                "id_usuario": str(usuario["id_usuario"]),
                "nombre": usuario["nombre"],
                "rol_anterior": usuario["rol"],
                "rol_nuevo": "Comité",
            })
        return cambios

    async def cancelar_apelacion(self, id_apelacion: UUID, usuario: dict) -> dict:
        current = await self.get_apelacion_by_id(id_apelacion, usuario)
        if not current:
            return None
        if current.get("estado") in APELACION_FINAL:
            return None
        query = text("""
            UPDATE apelacion
            SET estado = 'CANCELADA'
            WHERE id = :id_apelacion
              AND estado IN ('ENVIADA', 'EN_REVISION', 'INFORMACION_SOLICITADA')
            RETURNING id, id_solicitud, id_empresa, estado, radicado, fecha, motivo, razones_rechazo, fallo;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        await self.db.commit()
        row = result.mappings().first()
        return dict(row) if row else None

    async def get_historial(self, id_apelacion: UUID, usuario: dict) -> list[dict]:
        apelacion = await self.get_apelacion_by_id(id_apelacion, usuario)
        if not apelacion:
            return []

        query = text("""
            SELECT id_evidencia, id_apelacion, id_usuario_subio AS id_usuario,
                   nombre_archivo, tipo_evidencia, url_archivo, descripcion, fecha_subida
            FROM evidencia_apelacion
            WHERE id_apelacion = :id_apelacion
            ORDER BY fecha_subida DESC;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        evidencias = [dict(row) for row in result.mappings().all()]

        historial = [apelacion]
        historial.extend(evidencias)
        return historial

    async def get_evidencias_previas(self, id_apelacion: UUID, usuario: dict) -> list[dict]:
        if not await self.get_apelacion_by_id(id_apelacion, usuario):
            return []
        query = text("""
            SELECT id_evidencia, id_apelacion, id_usuario_subio AS id_usuario,
                   nombre_archivo, tipo_evidencia, url_archivo, descripcion, fecha_subida
            FROM evidencia_apelacion
            WHERE id_apelacion = :id_apelacion;
        """)
        result = await self.db.execute(query, {"id_apelacion": id_apelacion})
        return [dict(row) for row in result.mappings().all()]

    async def solicitar_info_adicional(
        self,
        id_apelacion: UUID,
        requerimiento: str,
        usuario: dict,
        observaciones: str | None = None,
    ) -> dict:
        """
        El Comité pide documentos concretos y los deja por escrito.

        El texto va a `requerimiento_apelacion`, no a `apelacion.observaciones`:
        así cada petición queda guardada con su fecha y su autor, y la empresa
        ve exactamente qué le están pidiendo, incluso si se pide dos veces.
        """
        apelacion = await self.get_apelacion_by_id(id_apelacion, usuario)
        if not apelacion or apelacion.get("estado") not in APELACION_EDITABLE:
            return None

        detalle = (requerimiento or "").strip()
        if len(detalle) < 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Escriba qué documentos debe adjuntar la empresa; con menos "
                    "de diez caracteres no se entiende el requerimiento."
                ),
            )

        creado = await self.db.execute(
            text("""
                INSERT INTO requerimiento_apelacion (
                    id_apelacion, documentos, observaciones, estado, id_usuario_solicita
                )
                VALUES (:id_apelacion, :documentos, :observaciones, 'Pendiente', :id_usuario)
                RETURNING id_requerimiento, id_apelacion, documentos, observaciones,
                          estado, fecha_solicitud;
            """),
            {
                "id_apelacion": str(id_apelacion),
                "documentos": detalle,
                "observaciones": observaciones,
                "id_usuario": usuario.get("id_usuario"),
            },
        )
        requerimiento_creado = dict(creado.mappings().first())

        query = text("""
            UPDATE apelacion
            SET estado = 'INFORMACION_SOLICITADA',
                id_usuario_revisa = :id_usuario,
                fecha_decision = CURRENT_TIMESTAMP
            WHERE id = :id_apelacion
              AND estado IN ('ENVIADA', 'EN_REVISION', 'INFORMACION_SOLICITADA')
            RETURNING id, estado, observaciones;
        """)
        result = await self.db.execute(query, {
            "id_apelacion": id_apelacion,
            "id_usuario": usuario.get("id_usuario"),
        })
        await self.db.commit()
        row = result.mappings().first()
        if not row:
            return None
        return {**dict(row), "requerimiento": requerimiento_creado}

    async def listar_requerimientos(self, id_apelacion: UUID, usuario: dict) -> list[dict]:
        """Todo lo que el Comité ha pedido en esta apelación, de lo nuevo a lo viejo."""
        if not await self.get_apelacion_by_id(id_apelacion, usuario):
            return []

        resultado = await self.db.execute(
            text("""
                SELECT r.id_requerimiento, r.documentos, r.observaciones, r.estado,
                       r.fecha_solicitud, r.fecha_atendido,
                       COALESCE(u.nombre, u.correo) AS solicitado_por
                FROM requerimiento_apelacion r
                LEFT JOIN usuario u ON u.id_usuario = r.id_usuario_solicita
                WHERE r.id_apelacion = :id_apelacion
                ORDER BY r.fecha_solicitud DESC;
            """),
            {"id_apelacion": str(id_apelacion)},
        )
        requerimientos = [dict(fila) for fila in resultado.mappings().all()]

        # Antes de que existiera esta tabla, el requerimiento se guardaba en
        # `apelacion.observaciones`. Los que quedaron así se siguen mostrando
        # para que ninguna empresa se quede sin saber qué le pidieron.
        apelacion = await self.get_apelacion_by_id(id_apelacion, usuario)
        anterior = (apelacion or {}).get("observaciones")
        if not requerimientos and anterior and apelacion.get("estado") == "INFORMACION_SOLICITADA":
            requerimientos.append({
                "id_requerimiento": None,
                "documentos": anterior,
                "observaciones": None,
                "estado": "Pendiente",
                "fecha_solicitud": apelacion.get("fecha_decision"),
                "fecha_atendido": None,
                "solicitado_por": "el comité",
            })

        return requerimientos

    async def _atender_requerimientos(self, id_apelacion: UUID) -> int:
        """
        Marca como atendidos los requerimientos pendientes.

        Se llama cuando la empresa adjunta evidencias: si el Comité había
        pedido documentos, ya los recibió y la apelación vuelve a revisión.
        """
        resultado = await self.db.execute(
            text("""
                UPDATE requerimiento_apelacion
                SET estado = 'Atendido', fecha_atendido = CURRENT_TIMESTAMP
                WHERE id_apelacion = :id_apelacion AND estado = 'Pendiente'
                RETURNING id_requerimiento;
            """),
            {"id_apelacion": str(id_apelacion)},
        )
        atendidos = len(resultado.all())
        if atendidos:
            await self.db.execute(
                text("""
                    UPDATE apelacion SET estado = 'EN_REVISION'
                    WHERE id = :id_apelacion AND estado = 'INFORMACION_SOLICITADA';
                """),
                {"id_apelacion": str(id_apelacion)},
            )
        return atendidos

    async def registrar_decision_final(self, id_apelacion: UUID, decision: str, observaciones: str | None, usuario: dict) -> dict:
        if not await self.get_apelacion_by_id(id_apelacion, usuario):
            return None
        query = text("""
            UPDATE apelacion
            SET estado = CAST(:decision AS VARCHAR),
                observaciones = :observaciones,
                fallo = (CAST(:decision AS VARCHAR) = 'RECHAZADA'),
                id_usuario_revisa = :id_usuario,
                fecha_decision = CURRENT_TIMESTAMP
            WHERE id = :id_apelacion
              AND estado IN ('ENVIADA', 'EN_REVISION', 'INFORMACION_SOLICITADA')
            RETURNING id, estado, observaciones, fecha_decision;
        """)
        result = await self.db.execute(query, {
            "id_apelacion": id_apelacion,
            "decision": decision,
            "observaciones": observaciones,
            "id_usuario": usuario.get("id_usuario"),
        })
        await self.db.commit()
        row = result.mappings().first()
        if not row:
            return None
        respuesta = dict(row)
        if respuesta.get("estado") == "APROBADA":
            respuesta["certificacion"] = await self.aplicar_apelacion_favorable(id_apelacion, usuario)
        return respuesta

    async def cambiar_estado_dictamen(self, id_apelacion: UUID, nuevo_estado: str, usuario: dict) -> dict:
        apelacion = await self.get_apelacion_by_id(id_apelacion, usuario)
        transiciones = {
            "APROBADA": APELACION_EDITABLE,
            "RECHAZADA": APELACION_EDITABLE,
            "NOTIFICADA": {"APROBADA", "RECHAZADA"},
            "CERRADA": {"NOTIFICADA"},
        }
        estados_anteriores = transiciones.get(nuevo_estado)
        if not estados_anteriores:
            raise ValueError("El dictamen no es válido.")
        if not apelacion or apelacion.get("estado") not in estados_anteriores:
            return None
        query = text("""
            UPDATE apelacion
            SET estado = CAST(:nuevo_estado AS VARCHAR),
                fallo = CASE
                    WHEN CAST(:nuevo_estado AS VARCHAR) = 'APROBADA' THEN FALSE
                    WHEN CAST(:nuevo_estado AS VARCHAR) = 'RECHAZADA' THEN TRUE
                    ELSE fallo
                END,
                id_usuario_revisa = :id_usuario,
                fecha_decision = CURRENT_TIMESTAMP
            WHERE id = :id_apelacion
              AND estado = :estado_anterior
            RETURNING id, estado, fallo, fecha_decision;
        """)
        result = await self.db.execute(query, {
            "id_apelacion": id_apelacion,
            "nuevo_estado": nuevo_estado,
            "estado_anterior": apelacion["estado"],
            "id_usuario": usuario.get("id_usuario"),
        })
        await self.db.commit()
        row = result.mappings().first()
        if not row:
            return None
        respuesta = dict(row)
        if respuesta.get("estado") in APELACION_FAVORABLE and respuesta.get("fallo") is False:
            respuesta["certificacion"] = await self.aplicar_apelacion_favorable(id_apelacion, usuario)
        return respuesta

    async def aplicar_apelacion_favorable(self, id_apelacion: UUID, usuario: dict) -> dict:
        """
        Una apelación aprobada revoca el rechazo: la solicitud vuelve a
        'Aprobada' y se crea el borrador del certificado (PENDIENTE_FIRMA)
        asignado al líder vigente del Comité, igual que al aprobar en el Comité.

        Antes la apelación pasaba a APROBADA/NOTIFICADA/CERRADA y la solicitud
        se quedaba en 'Rechazada': nadie podía generar el certificado (exige
        solicitud aprobada) ni el Comité podía aprobarla (ya tenía dictamen).

        Es idempotente: se llama al aprobar, notificar y cerrar; si la
        solicitud ya está aprobada no la toca, y el borrador no se repite
        porque `crear_borrador_automatico` no crea uno si ya hay certificado.
        """
        resultado = await self.db.execute(text("""
            SELECT a.id_solicitud, a.radicado, a.estado, a.fallo,
                   s.estado AS estado_solicitud, s.numero_radicado, s.id_empresa
            FROM apelacion a
            JOIN solicitud s ON s.id_solicitud = a.id_solicitud
            WHERE a.id = :id_apelacion
              AND s.deleted_at IS NULL
            FOR UPDATE OF s;
        """), {"id_apelacion": str(id_apelacion)})
        fila = resultado.mappings().first()
        if not fila or fila["estado"] not in APELACION_FAVORABLE or fila["fallo"] is not False:
            return {"solicitud_actualizada": False, "certificado": None}

        id_solicitud = fila["id_solicitud"]
        radicado = fila["radicado"] or "sin radicado"
        solicitud_actualizada = False
        if estado_es_rechazada(fila["estado_solicitud"]):
            await self.db.execute(text("""
                UPDATE solicitud SET estado = :estado
                WHERE id_solicitud = :id_solicitud AND deleted_at IS NULL;
            """), {"estado": estados.APROBADA, "id_solicitud": str(id_solicitud)})
            await self.db.execute(text("""
                INSERT INTO historial_estado (id_solicitud, estado, fecha, observacion)
                VALUES (:id_solicitud, :estado, CURRENT_DATE, :observacion);
            """), {
                "id_solicitud": str(id_solicitud),
                "estado": estados.APROBADA,
                "observacion": (
                    f"[APE] Apelación {radicado} aprobada: se revoca el rechazo y la solicitud "
                    "queda aprobada para certificar."
                )[:255],
            })
            solicitud_actualizada = True
        await self.db.commit()

        if not estados.es((await self._estado_solicitud(id_solicitud)), estados.APROBADA):
            # Cerrada, cancelada u otro estado: no se certifica desde aquí.
            return {"solicitud_actualizada": solicitud_actualizada, "certificado": None}

        from modules.certificados.certificados_service import CertificadosService

        certificados = CertificadosService(self.db)
        borrador = await certificados.crear_borrador_automatico(id_solicitud, usuario)
        if solicitud_actualizada or borrador.get("creado"):
            # Se avisa al líder del comité de ESTE expediente (o al global sin el SQL).
            from modules.comite.lider_expediente import lider_de_expediente

            await self._notificar_apelacion_favorable(
                fila, borrador, await lider_de_expediente(self.db, fila["id_solicitud"])
            )
        return {"solicitud_actualizada": solicitud_actualizada, "certificado": borrador}

    async def _estado_solicitud(self, id_solicitud) -> str | None:
        resultado = await self.db.execute(text(
            "SELECT estado FROM solicitud WHERE id_solicitud = :id_solicitud;"
        ), {"id_solicitud": str(id_solicitud)})
        return resultado.scalar_one_or_none()

    async def _notificar_apelacion_favorable(self, fila: dict, borrador: dict, lider: dict | None) -> None:
        """Avisa a la empresa y, si hay borrador, al líder que debe firmarlo."""
        radicado = fila["radicado"] or "sin radicado"
        solicitud = fila["numero_radicado"] or str(fila["id_solicitud"])
        if borrador.get("creado"):
            detalle = (
                f"El certificado {borrador.get('codigo_verificacion')} quedó pendiente de la firma "
                "del líder del Comité."
            )
        else:
            detalle = "El certificado se generará desde Gestión de certificados."
        mensaje_empresa = (
            f"Su apelación {radicado} fue aprobada: la solicitud {solicitud} queda aprobada. {detalle}"
        )[:255]
        await self.db.execute(text("""
            INSERT INTO notificacion (id_notificacion, id_usuario, asunto, mensaje, estado, fecha_envio)
            SELECT gen_random_uuid(), ue.id_usuario, :asunto, :mensaje, 'Pendiente', CURRENT_DATE
            FROM user_empresa ue
            WHERE ue.id_empresa = :id_empresa AND ue.estado = 'Activo';
        """), {
            "asunto": "Apelación aprobada",
            "mensaje": mensaje_empresa,
            "id_empresa": str(fila["id_empresa"]),
        })
        if borrador.get("creado") and lider:
            await self.db.execute(text("""
                INSERT INTO notificacion (id_notificacion, id_usuario, asunto, mensaje, estado, fecha_envio)
                VALUES (gen_random_uuid(), :id_usuario, :asunto, :mensaje, 'Pendiente', CURRENT_DATE);
            """), {
                "id_usuario": str(lider["id_usuario"]),
                "asunto": "Certificado pendiente de firma",
                "mensaje": (
                    f"La apelación {radicado} fue aprobada. El certificado "
                    f"{borrador.get('codigo_verificacion')} de la solicitud {solicitud} espera su firma."
                )[:255],
            })
        await self.db.commit()

    async def obtener_archivo_evidencia(self, id_apelacion: UUID, id_evidencia: UUID, usuario: dict) -> tuple[Path, str] | None:
        if not await self.get_apelacion_by_id(id_apelacion, usuario):
            return None
        result = await self.db.execute(text("""
            SELECT nombre_archivo, url_archivo
            FROM evidencia_apelacion
            WHERE id_apelacion = :id_apelacion AND id_evidencia = :id_evidencia;
        """), {"id_apelacion": id_apelacion, "id_evidencia": id_evidencia})
        evidence = result.mappings().first()
        if not evidence:
            return None
        ruta = (RAIZ_PROYECTO / evidence["url_archivo"]).resolve()
        if not ruta.is_relative_to(CARPETA_EVIDENCIAS.resolve()):
            return None
        # Si se subió en otro computador, se trae de la base compartida.
        ruta = await almacen_archivos.ruta_local(evidence["url_archivo"], db=self.db, disco=ruta)
        if ruta is None:
            return None
        return ruta, evidence["nombre_archivo"]