"""
M5 — GESTIÓN DE SOLICITUDES
Lógica de negocio del Bloque 1 (SOL-001 a SOL-010).

Trabaja sobre las tablas que ya existen en la base de datos del proyecto:
`solicitud`, `historial_estado` y `user_empresa`. Se usa SQL nativo con
`text()` para mantener la convención del resto de módulos.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.datetime_utils import system_now
from modules.solicitudes.solicitud_permissions import (
    ROL_EMP,
    ROL_SUPERADM,
    normalizar_rol,
)
from modules.solicitudes.solicitud_schema import (
    ESTADOS_CANCELABLES,
    ESTADOS_EDITABLES,
    EstadoSolicitud,
    SolicitudCancelar,
    SolicitudCrear,
    SolicitudEditar,
)

# Columnas devueltas por todas las consultas de lectura del módulo.
COLUMNAS_SOLICITUD = """
    id_solicitud,
    numero_radicado,
    estado,
    id_empresa,
    id_norma,
    alcance_certificacion,
    numero_empleados,
    numero_sedes,
    persona_contacto,
    observaciones,
    motivo_cancelacion,
    ciclo_renovacion,
    usuario_creador,
    fecha,
    fecha_creacion,
    fecha_radicacion,
    fecha_cancelacion
"""

# Campos que deben estar diligenciados para poder radicar (SOL-005).
CAMPOS_OBLIGATORIOS_AL_RADICAR = (
    "id_norma",
    "alcance_certificacion",
    "numero_empleados",
    "numero_sedes",
)


class SolicitudService:
    """Operaciones del ciclo de vida de una solicitud de certificación."""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ========================================================
    # AYUDANTES INTERNOS
    # ========================================================

    @staticmethod
    def _ve_todas(usuario: dict) -> bool:
        """
        True si el rol puede consultar solicitudes de cualquier empresa.

        La empresa solo ve las suyas; los demás roles con permiso de consulta
        (ADM, AUX, AUD, COM, APR y SUPERADM) ven todas.
        """
        return normalizar_rol(usuario.get("role_name")) != ROL_EMP

    async def _empresas_del_usuario(self, usuario: dict) -> list[str]:
        """Empresas activas a las que está vinculado el usuario autenticado."""
        resultado = await self.db.execute(
            text("""
                SELECT id_empresa
                FROM user_empresa
                WHERE id_usuario = :id_usuario
                  AND estado = 'Activo';
            """),
            {"id_usuario": str(usuario.get("id_usuario"))},
        )
        return [str(fila["id_empresa"]) for fila in resultado.mappings().all()]

    async def _registrar_historial(
        self,
        id_solicitud: UUID | str,
        estado: str,
        usuario: dict,
        detalle: str | None = None,
    ) -> None:
        """
        Deja constancia del cambio en `historial_estado`.

        La tabla no tiene columna de usuario, así que la traza de quién hizo
        qué se guarda en `observacion` junto al código de permiso aplicado.
        El Bloque 6 (SOL-055, bitácora inmutable) formaliza este registro.
        """
        partes = [f"[{usuario.get('permiso_codigo', 'M5')}]"]
        if usuario.get("nombre"):
            partes.append(f"por {usuario['nombre']}")
        if detalle:
            partes.append(f"- {detalle}")

        await self.db.execute(
            text("""
                INSERT INTO historial_estado (
                    id_solicitud, estado, fecha, observacion
                )
                VALUES (
                    :id_solicitud, :estado, CURRENT_DATE, :observacion
                );
            """),
            {
                "id_solicitud": str(id_solicitud),
                "estado": estado,
                "observacion": " ".join(partes)[:255],
            },
        )

    async def _obtener_o_404(self, id_solicitud: UUID) -> dict:
        """Trae una solicitud viva (no eliminada) o lanza 404."""
        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_SOLICITUD}
                FROM solicitud
                WHERE id_solicitud = :id_solicitud
                  AND deleted_at IS NULL;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        fila = resultado.mappings().first()

        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La solicitud no existe o fue eliminada.",
            )

        return dict(fila)

    async def _obtener_accesible_o_404(
        self,
        id_solicitud: UUID,
        usuario: dict,
    ) -> dict:
        """Trae la solicitud validando que el usuario tenga derecho a verla."""
        solicitud = await self._obtener_o_404(id_solicitud)

        if self._ve_todas(usuario):
            return solicitud

        empresas = await self._empresas_del_usuario(usuario)
        if str(solicitud["id_empresa"]) not in empresas:
            # Se responde 404 en lugar de 403 para no revelar la existencia
            # de solicitudes de otras empresas.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La solicitud no existe o fue eliminada.",
            )

        return solicitud

    async def _exigir_propiedad(self, solicitud: dict, usuario: dict) -> None:
        """
        Las acciones de escritura del Bloque 1 pertenecen a la empresa titular.

        El SuperAdministrador puede intervenir cualquier solicitud.
        """
        if normalizar_rol(usuario.get("role_name")) == ROL_SUPERADM:
            return

        empresas = await self._empresas_del_usuario(usuario)
        if str(solicitud["id_empresa"]) not in empresas:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo la empresa titular puede modificar esta solicitud.",
            )

    async def _resolver_empresa(
        self,
        usuario: dict,
        id_empresa: UUID | None,
    ) -> str:
        """
        Determina sobre qué empresa se crea la solicitud.

        Si el usuario está vinculado a una sola empresa se toma esa; si está
        vinculado a varias debe indicar cuál, y siempre se valida que la
        empresa pedida sea una de las suyas.
        """
        if normalizar_rol(usuario.get("role_name")) == ROL_SUPERADM:
            if id_empresa is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="El SuperAdministrador debe indicar 'id_empresa'.",
                )
            return str(id_empresa)

        empresas = await self._empresas_del_usuario(usuario)

        if not empresas:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "El usuario no está asociado a ninguna empresa activa, "
                    "así que no puede crear solicitudes."
                ),
            )

        if id_empresa is not None:
            if str(id_empresa) not in empresas:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="El usuario no pertenece a la empresa indicada.",
                )
            return str(id_empresa)

        if len(empresas) > 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "El usuario está asociado a varias empresas: indique "
                    "'id_empresa' en la solicitud."
                ),
            )

        return empresas[0]

    async def _generar_radicado(self) -> str:
        """
        Genera el número de radicado consecutivo: SOL-<año>-<consecutivo>.

        El consecutivo sale de una secuencia de PostgreSQL, así que sigue
        siendo único aunque dos empresas radiquen al mismo tiempo.
        """
        resultado = await self.db.execute(
            text("SELECT nextval('solicitud_radicado_seq') AS consecutivo;")
        )
        return f"SOL-{system_now().year}-{resultado.scalar():06d}"

    # ========================================================
    # SOL-001 / SOL-002 — CREAR SOLICITUD Y GUARDAR BORRADOR
    # ========================================================

    async def crear_borrador(
        self,
        data: SolicitudCrear,
        usuario: dict,
    ) -> dict:
        """
        SOL-001 (Crear solicitud) y SOL-002 (Guardar borrador).

        Ambos permisos comparten la operación: la solicitud nace siempre en
        estado Borrador y solo se vuelve formal al radicarla (SOL-005).
        """
        id_empresa = await self._resolver_empresa(usuario, data.id_empresa)

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO solicitud (
                    id_empresa, estado, fecha, id_norma,
                    alcance_certificacion, numero_empleados, numero_sedes,
                    persona_contacto, observaciones, usuario_creador
                )
                VALUES (
                    :id_empresa, :estado, CURRENT_DATE, :id_norma,
                    :alcance_certificacion, :numero_empleados, :numero_sedes,
                    :persona_contacto, :observaciones, :usuario_creador
                )
                RETURNING {COLUMNAS_SOLICITUD};
            """),
            {
                "id_empresa": id_empresa,
                "estado": EstadoSolicitud.borrador.value,
                "id_norma": str(data.id_norma) if data.id_norma else None,
                "alcance_certificacion": data.alcance_certificacion,
                "numero_empleados": data.numero_empleados,
                "numero_sedes": data.numero_sedes,
                "persona_contacto": data.persona_contacto,
                "observaciones": data.observaciones,
                "usuario_creador": str(usuario.get("id_usuario")),
            },
        )
        solicitud = dict(resultado.mappings().one())

        await self._registrar_historial(
            solicitud["id_solicitud"],
            EstadoSolicitud.borrador.value,
            usuario,
            "Creacion del borrador",
        )
        await self.db.commit()

        return solicitud

    # ========================================================
    # SOL-003 — EDITAR BORRADOR
    # ========================================================

    async def editar_borrador(
        self,
        id_solicitud: UUID,
        data: SolicitudEditar,
        usuario: dict,
    ) -> dict:
        """SOL-003: solo se edita mientras la solicitud siga en Borrador."""
        solicitud = await self._obtener_accesible_o_404(id_solicitud, usuario)
        await self._exigir_propiedad(solicitud, usuario)
        self._exigir_estado_editable(solicitud)

        cambios = data.model_dump(exclude_unset=True, exclude_none=True)
        if not cambios:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se recibió ningún campo para actualizar.",
            )

        if "id_norma" in cambios:
            cambios["id_norma"] = str(cambios["id_norma"])

        # Los nombres de columna salen del modelo Pydantic, nunca del cliente,
        # y los valores siempre viajan como parámetros ligados.
        asignaciones = ", ".join(f"{campo} = :{campo}" for campo in cambios)

        resultado = await self.db.execute(
            text(f"""
                UPDATE solicitud
                SET {asignaciones}
                WHERE id_solicitud = :id_solicitud
                RETURNING {COLUMNAS_SOLICITUD};
            """),
            {**cambios, "id_solicitud": str(id_solicitud)},
        )
        actualizada = dict(resultado.mappings().one())

        await self._registrar_historial(
            id_solicitud,
            actualizada["estado"],
            usuario,
            f"Edicion de: {', '.join(sorted(cambios))}",
        )
        await self.db.commit()

        return actualizada

    @staticmethod
    def _exigir_estado_editable(solicitud: dict) -> None:
        """Corta la operación si la solicitud dejó de ser un borrador."""
        if EstadoSolicitud(solicitud["estado"]) not in ESTADOS_EDITABLES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Solo se puede modificar una solicitud en estado Borrador. "
                    f"Estado actual: {solicitud['estado']}."
                ),
            )

    # ========================================================
    # SOL-004 — ELIMINAR BORRADOR
    # ========================================================

    async def eliminar_borrador(
        self,
        id_solicitud: UUID,
        usuario: dict,
    ) -> dict:
        """
        SOL-004: borrado lógico usando las columnas `deleted_at`/`deleted_by`
        que ya trae la tabla.

        Nunca se hace DELETE físico: el expediente debe seguir siendo
        auditable aunque la empresa descarte el borrador.
        """
        solicitud = await self._obtener_accesible_o_404(id_solicitud, usuario)
        await self._exigir_propiedad(solicitud, usuario)

        if EstadoSolicitud(solicitud["estado"]) not in ESTADOS_EDITABLES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Solo se puede eliminar una solicitud en estado Borrador. "
                    "Una solicitud radicada se cancela con SOL-009."
                ),
            )

        await self._registrar_historial(
            id_solicitud,
            solicitud["estado"],
            usuario,
            "Eliminacion logica del borrador",
        )

        await self.db.execute(
            text("""
                UPDATE solicitud
                SET deleted_at = NOW(),
                    deleted_by = :deleted_by
                WHERE id_solicitud = :id_solicitud;
            """),
            {
                "deleted_by": str(usuario.get("id_usuario")),
                "id_solicitud": str(id_solicitud),
            },
        )
        await self.db.commit()

        return {
            "id_solicitud": str(id_solicitud),
            "mensaje": "Borrador eliminado correctamente.",
        }

    # ========================================================
    # SOL-005 — RADICAR SOLICITUD FORMALMENTE
    # ========================================================

    async def radicar(
        self,
        id_solicitud: UUID,
        usuario: dict,
    ) -> dict:
        """
        SOL-005: convierte el borrador en solicitud formal.

        Asigna número de radicado y congela la edición.
        """
        solicitud = await self._obtener_accesible_o_404(id_solicitud, usuario)
        await self._exigir_propiedad(solicitud, usuario)

        if EstadoSolicitud(solicitud["estado"]) is not EstadoSolicitud.borrador:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Solo se radica una solicitud en estado Borrador. "
                    f"Estado actual: {solicitud['estado']}."
                ),
            )

        faltantes = [
            campo
            for campo in CAMPOS_OBLIGATORIOS_AL_RADICAR
            if solicitud.get(campo) in (None, "")
        ]
        if faltantes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "No se puede radicar: faltan campos obligatorios "
                    f"({', '.join(faltantes)})."
                ),
            )

        radicado = await self._generar_radicado()

        resultado = await self.db.execute(
            text(f"""
                UPDATE solicitud
                SET estado = :estado,
                    numero_radicado = :numero_radicado,
                    fecha_radicacion = NOW()
                WHERE id_solicitud = :id_solicitud
                RETURNING {COLUMNAS_SOLICITUD};
            """),
            {
                "estado": EstadoSolicitud.radicada.value,
                "numero_radicado": radicado,
                "id_solicitud": str(id_solicitud),
            },
        )
        radicada = dict(resultado.mappings().one())

        await self._registrar_historial(
            id_solicitud,
            EstadoSolicitud.radicada.value,
            usuario,
            f"Radicado asignado: {radicado}",
        )
        await self.db.commit()

        return radicada

    # ========================================================
    # SOL-006 — CONSULTAR SOLICITUD
    # ========================================================

    async def consultar(self, id_solicitud: UUID, usuario: dict) -> dict:
        """SOL-006: detalle de una solicitud."""
        return await self._obtener_accesible_o_404(id_solicitud, usuario)

    async def consultar_ampliada(self, id_solicitud: UUID, usuario: dict) -> dict:
        """
        Igual que `consultar`, pero resolviendo los nombres de empresa y norma.

        La solicitud guarda `id_empresa` e `id_norma` como UUID, que no le
        dicen nada a una persona. Para el PDF (SOL-007), que es un documento
        que sale de la aplicacion, hacen falta el nombre y el NIT de la
        empresa y el codigo de la norma.
        """
        # Primero se valida el acceso con la consulta normal.
        await self._obtener_accesible_o_404(id_solicitud, usuario)

        resultado = await self.db.execute(
            text(f"""
                SELECT
                    s.{', s.'.join(c.strip() for c in COLUMNAS_SOLICITUD.split(',') if c.strip())},
                    e.nombre  AS empresa_nombre,
                    e.nit     AS empresa_nit,
                    n.codigo  AS norma_codigo,
                    n.nombre  AS norma_nombre,
                    n.version AS norma_version
                FROM solicitud s
                LEFT JOIN empresa e ON e.id_empresa = s.id_empresa
                LEFT JOIN norma   n ON n.id_norma   = s.id_norma
                WHERE s.id_solicitud = :id_solicitud
                  AND s.deleted_at IS NULL;
            """),
            {"id_solicitud": str(id_solicitud)},
        )
        fila = resultado.mappings().first()

        if not fila:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="La solicitud no existe o fue eliminada.",
            )

        return dict(fila)

    async def listar(
        self,
        usuario: dict,
        estado: EstadoSolicitud | None = None,
        limite: int = 50,
        desplazamiento: int = 0,
    ) -> list[dict]:
        """
        SOL-006: listado paginado.

        La empresa solo obtiene las solicitudes de las empresas a las que está
        vinculada; el resto de roles con permiso de consulta ven todas.
        """
        condiciones = ["deleted_at IS NULL"]
        parametros: dict = {"limite": limite, "desplazamiento": desplazamiento}

        if not self._ve_todas(usuario):
            empresas = await self._empresas_del_usuario(usuario)
            if not empresas:
                return []
            condiciones.append("id_empresa = ANY(:empresas)")
            parametros["empresas"] = empresas

        if estado is not None:
            condiciones.append("estado = :estado")
            parametros["estado"] = estado.value

        resultado = await self.db.execute(
            text(f"""
                SELECT {COLUMNAS_SOLICITUD}
                FROM solicitud
                WHERE {' AND '.join(condiciones)}
                ORDER BY fecha_creacion DESC
                LIMIT :limite OFFSET :desplazamiento;
            """),
            parametros,
        )

        return [dict(fila) for fila in resultado.mappings().all()]

    # ========================================================
    # SOL-008 — DUPLICAR SOLICITUD
    # ========================================================

    async def duplicar(self, id_solicitud: UUID, usuario: dict) -> dict:
        """
        SOL-008: copia los datos técnicos en un borrador nuevo.

        La copia nunca hereda el radicado ni el estado: nace en Borrador.
        """
        original = await self._obtener_accesible_o_404(id_solicitud, usuario)
        await self._exigir_propiedad(original, usuario)

        resultado = await self.db.execute(
            text(f"""
                INSERT INTO solicitud (
                    id_empresa, estado, fecha, id_norma,
                    alcance_certificacion, numero_empleados, numero_sedes,
                    persona_contacto, observaciones, usuario_creador
                )
                SELECT
                    id_empresa, :estado, CURRENT_DATE, id_norma,
                    alcance_certificacion, numero_empleados, numero_sedes,
                    persona_contacto, observaciones, :usuario_creador
                FROM solicitud
                WHERE id_solicitud = :id_solicitud
                RETURNING {COLUMNAS_SOLICITUD};
            """),
            {
                "estado": EstadoSolicitud.borrador.value,
                "usuario_creador": str(usuario.get("id_usuario")),
                "id_solicitud": str(id_solicitud),
            },
        )
        copia = dict(resultado.mappings().one())

        await self._registrar_historial(
            copia["id_solicitud"],
            EstadoSolicitud.borrador.value,
            usuario,
            f"Copia de {original.get('numero_radicado') or id_solicitud}",
        )
        await self.db.commit()

        return copia

    # ========================================================
    # SOL-009 — CANCELAR SOLICITUD ANTES DE REVISIÓN
    # ========================================================

    async def cancelar(
        self,
        id_solicitud: UUID,
        data: SolicitudCancelar,
        usuario: dict,
    ) -> dict:
        """
        SOL-009: la empresa retira la solicitud mientras nadie la haya tomado.

        En cuanto pasa a 'En revision' deja de ser cancelable.
        """
        solicitud = await self._obtener_accesible_o_404(id_solicitud, usuario)
        await self._exigir_propiedad(solicitud, usuario)

        if EstadoSolicitud(solicitud["estado"]) not in ESTADOS_CANCELABLES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "La solicitud ya no se puede cancelar. "
                    f"Estado actual: {solicitud['estado']}."
                ),
            )

        resultado = await self.db.execute(
            text(f"""
                UPDATE solicitud
                SET estado = :estado,
                    motivo_cancelacion = :motivo,
                    fecha_cancelacion = NOW()
                WHERE id_solicitud = :id_solicitud
                RETURNING {COLUMNAS_SOLICITUD};
            """),
            {
                "estado": EstadoSolicitud.cancelada.value,
                "motivo": data.motivo,
                "id_solicitud": str(id_solicitud),
            },
        )
        cancelada = dict(resultado.mappings().one())

        await self._registrar_historial(
            id_solicitud,
            EstadoSolicitud.cancelada.value,
            usuario,
            f"Motivo: {data.motivo}",
        )
        await self.db.commit()

        return cancelada

    # ========================================================
    # SOL-010 — CONSULTAR ESTADO DE SOLICITUD
    # ========================================================

    async def consultar_estado(self, id_solicitud: UUID, usuario: dict) -> dict:
        """SOL-010: vista reducida, solo el estado y sus fechas."""
        solicitud = await self._obtener_accesible_o_404(id_solicitud, usuario)

        return {
            "id_solicitud": solicitud["id_solicitud"],
            "numero_radicado": solicitud["numero_radicado"],
            "estado": solicitud["estado"],
            "fecha_creacion": solicitud["fecha_creacion"],
            "fecha_radicacion": solicitud["fecha_radicacion"],
            "fecha_cancelacion": solicitud["fecha_cancelacion"],
        }
