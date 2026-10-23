import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import _normalize_role_name
from modules.solicitudes.solicitud_service import SolicitudService


# Quien administra ve y decide cualquier apelacion; el Comite solo las suyas.
ROLES_ADMINISTRACION = {"superadmin", "admin", "auxiliar"}

APELACION_EDITABLE = {"ENVIADA", "EN_REVISION", "INFORMACION_SOLICITADA"}
APELACION_FINAL = {"APROBADA", "RECHAZADA", "CANCELADA"}
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
CARPETA_EVIDENCIAS = RAIZ_PROYECTO / "storage" / "apelaciones"
EXTENSIONES_EVIDENCIA = {".pdf", ".doc", ".docx", ".jpg", ".jpeg", ".png"}


def estado_es_rechazada(estado) -> bool:
    """
    ¿La solicitud está rechazada?

    Cada módulo escribe el estado a su manera: el Comité guarda 'RECHAZADO'
    (modules/comite/comite_service.py) y M5 define 'Rechazada'. Comparar con
    un texto exacto dejaba sin apelación a las solicitudes rechazadas desde
    el Comité, que son casi todas.
    """
    texto = unicodedata.normalize("NFD", str(estado or ""))
    texto = texto.encode("ascii", "ignore").decode().strip().upper()
    return texto.startswith("RECHAZ")

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

    async def _esta_asignado(self, id_apelacion: UUID, id_usuario) -> bool:
        resultado = await self.db.execute(
            text("""
                SELECT 1 FROM apelacion_comite
                WHERE id_apelacion = :id_apelacion AND id_usuario = :id_usuario;
            """),
            {"id_apelacion": str(id_apelacion), "id_usuario": str(id_usuario)},
        )
        return resultado.scalar() is not None

    async def exigir_acceso(self, id_apelacion: UUID, usuario: dict) -> None:
        """
        Un miembro del Comité solo entra a las apelaciones que le asignaron.

        Antes cualquier cuenta con rol Comité podía ver y decidir todas, sin
        importar si pertenecía al comité de esa apelación.
        """
        if self._rol(usuario) != "comite":
            return
        if not await self._esta_asignado(id_apelacion, usuario.get("id_usuario")):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No pertenece al comité asignado a esta apelación.",
            )

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
        Miembros del Comité que el Administrador puede asignar a la apelación.

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

        # Se listan los del Comité y también los Auditores: un auditor puede
        # ser designado para resolver una apelación, y al asignarlo el sistema
        # le pasa el rol (ver `assign_committee`).
        resultado = await self.db.execute(
            text("""
                SELECT u.id_usuario, u.nombre, u.correo, r.nombre AS rol
                FROM usuario u
                JOIN rol r ON r.id_rol = u.rol_id
                WHERE u.estado = 'Activo'
                  AND (LOWER(r.nombre) LIKE 'comit%' OR LOWER(r.nombre) LIKE 'auditor%')
                ORDER BY r.nombre, u.nombre;
            """)
        )
        miembros = []
        for fila in resultado.mappings().all():
            identificador = str(fila["id_usuario"])
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
        return dict(row) if row else None

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
        destino.write_bytes(contenido)
        ruta_relativa = str(destino.relative_to(RAIZ_PROYECTO))
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
        return dict(row) if row else None

    async def get_all_apelaciones(self, usuario: dict) -> list[dict]:
        from modules.solicitudes.solicitud_permissions import normalizar_rol, ROL_EMP

        filtro_empresa = normalizar_rol(usuario.get("role_name")) == ROL_EMP
        solo_asignadas = self._rol(usuario) == "comite"
        query = text("""
            SELECT a.id, a.id_solicitud,
                   a.id_empresa, a.estado, a.radicado, a.fecha, a.motivo,
                   a.razones_rechazo, a.fallo
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
            ))
            ORDER BY a.fecha DESC, a.id DESC;
        """)
        result = await self.db.execute(query, {
            "filtro_empresa": filtro_empresa,
            "solo_asignadas": solo_asignadas,
            "id_usuario": str(usuario.get("id_usuario")),
        })
        return [dict(row) for row in result.mappings().all()]

    async def get_apelacion_by_id(self, id_apelacion: UUID, usuario: dict | None = None) -> dict:
        query = text("""
            SELECT id, id_solicitud,
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
        return dict(row) if row else None

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
        return dict(row) if row else None

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
        if not ruta.is_relative_to(CARPETA_EVIDENCIAS.resolve()) or not ruta.is_file():
            return None
        return ruta, evidence["nombre_archivo"]