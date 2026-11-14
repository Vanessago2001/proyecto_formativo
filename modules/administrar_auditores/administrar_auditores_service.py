from uuid import UUID

from fastapi import HTTPException, status

from sqlalchemy import text

from sqlalchemy.ext.asyncio import AsyncSession

# Longitud mínima del motivo de rechazo y de la justificación al aprobar un
# auditor sin competencias validadas.
MIN_MOTIVO_RECHAZO = 10
MIN_JUSTIFICACION_SIN_COMPETENCIAS = 10
# Cabecera con la que el 409 avisa a la pantalla que debe pedir confirmación.
CABECERA_CONFIRMACION = "X-Requiere-Confirmacion"
VALOR_SIN_COMPETENCIAS = "sin-competencias"


def _describir_competencia_no_valida(fila: dict, hoy) -> str:
    nombre = str(fila.get("tipo_competencia") or "Competencia").strip()
    estado = str(fila.get("estado_validacion") or "Pendiente").strip()
    if estado == "Validado":
        fecha_fin = fila.get("fecha_fin")
        if not fila.get("es_vigente") or (fecha_fin is not None and fecha_fin < hoy):
            return f"{nombre} (vencida o no vigente)"
        return nombre
    return f"{nombre} ({estado.lower()})"


def competencias_vigentes_y_faltantes(filas: list[dict], hoy) -> tuple[list[dict], list[str]]:
    """Separa las competencias validadas y vigentes de las que no cuentan.

    Una competencia sirve para asignaciones solo si está Validada, marcada
    vigente y su fecha fin no pasó (misma regla que Asignación de auditores).
    """
    vigentes, faltantes = [], []
    for fila in filas:
        fecha_fin = fila.get("fecha_fin")
        if (
            str(fila.get("estado_validacion") or "") == "Validado"
            and fila.get("es_vigente")
            and (fecha_fin is None or fecha_fin >= hoy)
        ):
            vigentes.append(fila)
        else:
            faltantes.append(_describir_competencia_no_valida(fila, hoy))
    return vigentes, faltantes


class AdministrarAuditoresService:

    def __init__(self, db: AsyncSession):

        self.db = db

    # ========================================================

    # BANCO DE AUDITORES

    # LISTAR SOLICITUDES

    # ========================================================

    async def listar_solicitudes(

        self,

        estado: str | None = None,

    ):

        """

        Lista las postulaciones de auditores para el administrador.

        Permite filtrar por estado:

            - Enviado

            - En Revisión

            - Correcciones

            - Aprobado

            - Rechazado

            - Cancelado

        Si no se envía estado, devuelve todas.

        """

        consulta = """

            SELECT

                pa.id_postulacion,

                pa.id_usuario,

                pa.estado AS estado_postulacion,

                pa.fecha_postulacion,

                pa.fecha_revision,

                u.nombre,

                u.correo,

                u.tipo_doc,

                u.num_doc,

                u.estado AS estado_usuario,

                u.estado_auditor,

                r.nombre AS rol

            FROM postulacion_auditor pa

            INNER JOIN usuario u

                ON u.id_usuario = pa.id_usuario

            LEFT JOIN rol r

                ON r.id_rol = u.rol_id

            WHERE 1 = 1

            -- Los borradores no se gestionan en el banco de auditores.

            AND LOWER(pa.estado) <> 'borrador'

        """

        parametros = {}

        # ----------------------------------------------------

        # FILTRO POR ESTADO

        # ----------------------------------------------------

        if estado:

            consulta += """

                AND LOWER(pa.estado) = LOWER(:estado)

            """

            parametros["estado"] = estado.strip()

        # ----------------------------------------------------

        # ORDEN

        # ----------------------------------------------------

        consulta += """

            ORDER BY

                pa.fecha_postulacion DESC

        """

        result = await self.db.execute(

            text(consulta),

            parametros,

        )

        solicitudes = result.mappings().all()

        # ----------------------------------------------------

        # RESPUESTA

        # ----------------------------------------------------

        return [

            {

                "id_postulacion": solicitud["id_postulacion"],

                "id_usuario": solicitud["id_usuario"],

                "nombre": solicitud["nombre"],

                "correo": solicitud["correo"],

                "tipo_doc": solicitud["tipo_doc"],

                "num_doc": solicitud["num_doc"],

                "estado_usuario": solicitud["estado_usuario"],

                "estado_auditor": solicitud["estado_auditor"],

                "rol": solicitud["rol"],

                "estado_postulacion": solicitud["estado_postulacion"],

                "fecha_postulacion": solicitud["fecha_postulacion"],

                "fecha_revision": solicitud["fecha_revision"],

            }

            for solicitud in solicitudes

        ]

    # ========================================================

    # DETALLE DE UNA SOLICITUD

    # ========================================================


    async def listar_conflictos_general(self):
        result = await self.db.execute(
            text("""
                SELECT
                    c.id_conflicto,
                    c.id_usuario,
                    u.nombre AS auditor,
                    u.tipo_doc,
                    u.num_doc,
                    u.correo,
                    c.id_empresa,
                    e.nombre AS empresa,
                    e.nit,
                    c.tipo_conflicto,
                    c.descripcion,
                    c.bloquea_asignacion,
                    c.fecha_declaracion,
                    c.estado,
                    c.id_postulacion
                FROM conflicto_interes c
                INNER JOIN usuario u
                    ON u.id_usuario = c.id_usuario
                INNER JOIN empresa e
                    ON e.id_empresa = c.id_empresa
                ORDER BY c.fecha_declaracion DESC
            """)
        )
        return [dict(row) for row in result.mappings().all()]


    async def obtener_solicitud(

        self,

        id_postulacion: UUID,

    ):

        """

        Obtiene toda la información necesaria para que

        el administrador revise una postulación.

        """

        # ----------------------------------------------------

        # DATOS DE LA POSTULACIÓN

        # ----------------------------------------------------

        result = await self.db.execute(

            text("""

                SELECT

                    pa.id_postulacion,

                    pa.id_usuario,

                    pa.estado AS estado_postulacion,

                    pa.observaciones_tecnicas,

                    pa.fecha_postulacion,

                    pa.fecha_revision,

                    u.nombre,

                    u.correo,

                    u.tipo_doc,

                    u.num_doc,

                    u.estado AS estado_usuario,

                    u.estado_auditor,

                    r.nombre AS rol

                FROM postulacion_auditor pa

                INNER JOIN usuario u

                    ON u.id_usuario = pa.id_usuario

                LEFT JOIN rol r

                    ON r.id_rol = u.rol_id

                WHERE pa.id_postulacion = :id_postulacion

                LIMIT 1

            """),

            {

                "id_postulacion": id_postulacion,

            },

        )

        solicitud = result.mappings().first()

        if not solicitud:

            raise HTTPException(

                status_code=status.HTTP_404_NOT_FOUND,

                detail="No se encontró la postulación.",

            )

        # ----------------------------------------------------

        # PERFIL

        # ----------------------------------------------------

        result = await self.db.execute(

            text("""

                SELECT

                    ciudad_residencia,

                    departamento_residencia,

                    modalidad_preferida,

                    foto_url,

                    resumen_profesional,

                    calificacion_promedio

                FROM perfil_auditor

                WHERE id_usuario = :id_usuario

                  AND id_postulacion = :id_postulacion

                LIMIT 1

            """),

            {

                "id_usuario": solicitud["id_usuario"],

                "id_postulacion": id_postulacion,

            },

        )

        perfil = result.mappings().first()

        if perfil is None:

            result = await self.db.execute(

                text("""

                    SELECT

                        ciudad_residencia,

                        departamento_residencia,

                        modalidad_preferida,

                        foto_url,

                        resumen_profesional,

                        calificacion_promedio

                    FROM perfil_auditor

                    WHERE id_usuario = :id_usuario

                      AND id_postulacion IS NULL

                    LIMIT 1

                """),

                {

                    "id_usuario": solicitud["id_usuario"],

                },

            )

            perfil = result.mappings().first()

        # ----------------------------------------------------

        # COMPETENCIAS

        # ----------------------------------------------------

        result = await self.db.execute(

            text("""

                SELECT

                    id_competencia,

                    id_norma,

                    tipo_competencia,

                    codigo_sector_iaf,

                    titulo_institucion,

                    descripcion,

                    fecha_inicio,

                    fecha_fin,

                    es_vigente,

                    estado_validacion

                FROM competencia_auditor

                WHERE id_usuario = :id_usuario

                  AND id_postulacion = :id_postulacion

                ORDER BY fecha_inicio DESC

            """),

            {

                "id_usuario": solicitud["id_usuario"],

                "id_postulacion": id_postulacion,

            },

        )

        competencias = result.mappings().all()

        if not competencias:

            result = await self.db.execute(

                text("""

                    SELECT

                        id_competencia,

                        id_norma,

                        tipo_competencia,

                        codigo_sector_iaf,

                        titulo_institucion,

                        descripcion,

                        fecha_inicio,

                        fecha_fin,

                        es_vigente,

                        estado_validacion

                    FROM competencia_auditor

                    WHERE id_usuario = :id_usuario

                      AND id_postulacion IS NULL

                    ORDER BY fecha_inicio DESC

                """),

                {

                    "id_usuario": solicitud["id_usuario"],

                },

            )

            competencias = result.mappings().all()

        # ----------------------------------------------------

        # CONFLICTOS DE INTERÉS

        # ----------------------------------------------------

        # Todos los conflictos que declaró el auditor (en esta postulación o
        # después del registro, sin postulación), con el nombre de la empresa
        # para que la tabla no muestre el UUID.
        result = await self.db.execute(
            text("""
                SELECT
                    c.id_conflicto,
                    c.id_empresa,
                    e.nombre AS empresa_nombre,
                    c.tipo_conflicto,
                    c.descripcion,
                    c.bloquea_asignacion,
                    c.fecha_declaracion,
                    c.estado
                FROM conflicto_interes c
                LEFT JOIN empresa e
                    ON e.id_empresa = c.id_empresa
                WHERE c.id_usuario = :id_usuario
                  AND (
                        c.id_postulacion = :id_postulacion
                        OR c.id_postulacion IS NULL
                  )
                ORDER BY c.fecha_declaracion DESC
            """),
            {
                "id_usuario": solicitud["id_usuario"],
                "id_postulacion": id_postulacion,
            },
        )
        conflictos = [dict(fila) for fila in result.mappings().all()]

        # ----------------------------------------------------

        # DOCUMENTOS

        #

        # IMPORTANTE:

        # Estos sí están relacionados directamente con

        # id_postulacion.

        # ----------------------------------------------------

        result = await self.db.execute(

            text("""

                SELECT

                    id_documento,

                    id_postulacion,

                    id_usuario,

                    nombre_archivo,

                    tipo_documento,

                    url_archivo,

                    fecha_subida,

                    estado_revision,

                    categoria_documento,

                    id_titulo,

                    id_experiencia_laboral,

                    id_experiencia_auditoria,

                    observacion_revision,

                    revisado_por,

                    fecha_revision

                FROM documento_auditor

                WHERE id_postulacion = :id_postulacion

                ORDER BY fecha_subida DESC

            """),

            {

                "id_postulacion": id_postulacion,

            },

        )

        documentos = result.mappings().all()

        # ----------------------------------------------------

        # FORMACIÓN Y EXPERIENCIAS

        # ----------------------------------------------------

        result = await self.db.execute(text("""

            SELECT id_titulo, nivel, titulo, institucion, fecha_grado,

                   estado_validacion, observacion_validacion

            FROM titulo_academico

            WHERE id_usuario = :id_usuario

              AND id_postulacion = :id_postulacion

            ORDER BY fecha_grado DESC NULLS LAST, created_at DESC

        """), {"id_usuario": solicitud["id_usuario"], "id_postulacion": id_postulacion})

        titulos = result.mappings().all()

        if not titulos:

            result = await self.db.execute(text("""

                SELECT id_titulo, nivel, titulo, institucion, fecha_grado,

                       estado_validacion, observacion_validacion

                FROM titulo_academico

                WHERE id_usuario = :id_usuario

                  AND id_postulacion IS NULL

                ORDER BY fecha_grado DESC NULLS LAST, created_at DESC

            """), {"id_usuario": solicitud["id_usuario"]})

            titulos = result.mappings().all()

        result = await self.db.execute(text("""

            SELECT id_experiencia, empresa, cargo, fecha_inicio, fecha_fin,

                   descripcion, estado_validacion, observacion_validacion

            FROM experiencia_laboral

            WHERE id_usuario = :id_usuario

              AND id_postulacion = :id_postulacion

            ORDER BY fecha_inicio DESC

        """), {"id_usuario": solicitud["id_usuario"], "id_postulacion": id_postulacion})

        experiencias_laborales = result.mappings().all()

        if not experiencias_laborales:

            result = await self.db.execute(text("""

                SELECT id_experiencia, empresa, cargo, fecha_inicio, fecha_fin,

                       descripcion, estado_validacion, observacion_validacion

                FROM experiencia_laboral

                WHERE id_usuario = :id_usuario

                  AND id_postulacion IS NULL

                ORDER BY fecha_inicio DESC

            """), {"id_usuario": solicitud["id_usuario"]})

            experiencias_laborales = result.mappings().all()

        result = await self.db.execute(text("""

            SELECT id_experiencia, organizacion, rol_auditoria, tipo_auditoria,

                   fecha_inicio, fecha_fin, descripcion, estado_validacion,

                   observacion_validacion

            FROM experiencia_auditoria

            WHERE id_usuario = :id_usuario

              AND id_postulacion = :id_postulacion

            ORDER BY fecha_inicio DESC

        """), {"id_usuario": solicitud["id_usuario"], "id_postulacion": id_postulacion})

        experiencias_auditoria = result.mappings().all()

        if not experiencias_auditoria:

            result = await self.db.execute(text("""

                SELECT id_experiencia, organizacion, rol_auditoria, tipo_auditoria,

                       fecha_inicio, fecha_fin, descripcion, estado_validacion,

                       observacion_validacion

                FROM experiencia_auditoria

                WHERE id_usuario = :id_usuario

                  AND id_postulacion IS NULL

                ORDER BY fecha_inicio DESC

            """), {"id_usuario": solicitud["id_usuario"]})

            experiencias_auditoria = result.mappings().all()

        # ----------------------------------------------------

        # RESPUESTA

        # ----------------------------------------------------

        return {

            "id_postulacion": solicitud["id_postulacion"],

            "id_usuario": solicitud["id_usuario"],

            "nombre": solicitud["nombre"],

            "correo": solicitud["correo"],

            "tipo_doc": solicitud["tipo_doc"],

            "num_doc": solicitud["num_doc"],

            "estado_usuario": solicitud["estado_usuario"],

            "estado_auditor": solicitud["estado_auditor"],

            "rol": solicitud["rol"],

            "estado_postulacion": solicitud["estado_postulacion"],

            "observaciones_tecnicas": (

                solicitud["observaciones_tecnicas"]

                or ""

            ),

            "fecha_postulacion": solicitud["fecha_postulacion"],

            "fecha_revision": solicitud["fecha_revision"],

            "perfil": (

                dict(perfil)

                if perfil

                else None

            ),

            "competencias": [

                dict(item)

                for item in competencias

            ],

            "tiene_conflicto": bool(conflictos),

            "decision_conflicto": (

                "Sí, tiene conflicto de interés"

                if conflictos

                else "No, declara que no tiene conflicto de interés"

            ),

            "conflictos": [

                dict(item)

                for item in conflictos

            ],

            "titulos": [dict(item) for item in titulos],

            "experiencias_laborales": [dict(item) for item in experiencias_laborales],

            "experiencias_auditoria": [dict(item) for item in experiencias_auditoria],

            "documentos": [

                dict(item)

                for item in documentos

            ],

        }

        # ========================================================

        # CAMBIAR ESTADO DE UNA POSTULACIÓN

        # ========================================================

    async def cambiar_estado(

        self,

        id_postulacion: UUID,

        nuevo_estado: str,

        observaciones: str | None,

        id_usuario_actor: UUID,

        confirmar_sin_competencias: bool = False,

        justificacion_sin_competencias: str | None = None,

        rol_confirmacion: str | None = None,

    ):

        """

        Cambia el estado de una postulación de auditor.

        Estados permitidos:

            - En Revisión

            - Correcciones

            - Aprobado

            - Rechazado

        Además:

            - registra observación

            - registra fecha del cambio

            - registra administrador que realizó el cambio

            - registra historial

            - crea notificación para el auditor

        """

        estados_permitidos = {

            "En Revisión",

            "Correcciones",

            "Aprobado",

            "Rechazado",

        }

        if nuevo_estado not in estados_permitidos:

            raise HTTPException(

                status_code=status.HTTP_400_BAD_REQUEST,

                detail=(

                    f"Estado '{nuevo_estado}' no válido. "

                    f"Estados permitidos: "

                    f"{', '.join(estados_permitidos)}."

                ),

            )

        # ----------------------------------------------------

        # BUSCAR POSTULACIÓN

        # ----------------------------------------------------

        result = await self.db.execute(

            text("""

                SELECT

                    pa.id_postulacion,

                    pa.id_usuario,

                    pa.estado,

                    pa.observaciones_tecnicas,

                    u.nombre,

                    u.correo

                FROM postulacion_auditor pa

                INNER JOIN usuario u

                    ON u.id_usuario = pa.id_usuario

                WHERE pa.id_postulacion = :id_postulacion

                LIMIT 1

            """),

            {

                "id_postulacion": id_postulacion,

            },

        )

        postulacion = result.mappings().first()

        if not postulacion:

            raise HTTPException(

                status_code=status.HTTP_404_NOT_FOUND,

                detail="No se encontró la postulación.",

            )

        estado_anterior = postulacion["estado"]

        # ----------------------------------------------------

        # VALIDAR QUE PUEDA SER MODIFICADA

        # ----------------------------------------------------

        if estado_anterior in (

            "Aprobado",

            "Rechazado",

            "Cancelado",

        ):

            raise HTTPException(

                status_code=status.HTTP_409_CONFLICT,

                detail=(

                    f"La postulación ya se encuentra en estado "

                    f"'{estado_anterior}' y no puede ser modificada."

                ),

            )

        # Un borrador todavía no fue enviado por el auditor: el banco no lo
        # lista y el Coordinador no puede revisarlo, aprobarlo ni rechazarlo.
        if str(estado_anterior or "").strip().lower() == "borrador":

            raise HTTPException(

                status_code=status.HTTP_409_CONFLICT,

                detail=(
                    "La postulación sigue en Borrador: el auditor aún no la "
                    "ha enviado, por eso no puede revisarse."
                ),

            )

        # Rechazar exige explicarle al auditor por qué (decisión de negocio
        # del 14/11): mínimo 10 caracteres reales, no solo espacios. Se valida
        # después de Borrador/cerrada para que esos casos sigan dando 409.
        if nuevo_estado == "Rechazado" and len((observaciones or "").strip()) < MIN_MOTIVO_RECHAZO:

            raise HTTPException(

                status_code=422,

                detail=(
                    "El motivo del rechazo es obligatorio: escriba al menos "
                    f"{MIN_MOTIVO_RECHAZO} caracteres explicando las razones."
                ),

            )

        if nuevo_estado == "Aprobado":

            pendientes = []

            result = await self.db.execute(

                text("SELECT COUNT(*) FROM documento_auditor WHERE id_postulacion = :id_postulacion AND estado_revision <> 'Aprobado'"),

                {"id_postulacion": id_postulacion},

            )

            if (result.scalar() or 0) > 0:

                pendientes.append("documentos adjuntos")

            # Competencias sin revisar (ni validadas ni rechazadas): igual que
            # los documentos, primero hay que revisarlas.
            result = await self.db.execute(

                text(
                    "SELECT COUNT(*) FROM competencia_auditor "
                    "WHERE id_postulacion = :id_postulacion "
                    "AND COALESCE(estado_validacion, 'Pendiente') NOT IN ('Validado', 'Rechazado')"
                ),

                {"id_postulacion": id_postulacion},

            )

            if (result.scalar() or 0) > 0:

                pendientes.append("competencias")

            if pendientes:

                raise HTTPException(

                    status_code=status.HTTP_400_BAD_REQUEST,

                    detail=(

                        "No se puede aprobar la postulacion. "

                        "Faltan elementos validados o aprobados: "

                        + ", ".join(pendientes) + "."

                    ),

                )

        # ----------------------------------------------------

        # OBSERVACIONES

        # ----------------------------------------------------

        observaciones_finales = (

            observaciones.strip()

            if observaciones

            else ""

        )

        # Aprobar sin competencias validadas y vigentes (o con alguna
        # rechazada/vencida) se permite, pero solo con confirmación explícita
        # y justificación: el auditor no será elegible en esas normas.
        nota_sin_competencias = ""

        if nuevo_estado == "Aprobado":

            from datetime import date as _date

            result = await self.db.execute(
                text("""
                    SELECT tipo_competencia, estado_validacion, es_vigente, fecha_fin
                    FROM competencia_auditor
                    WHERE id_postulacion = :id_postulacion
                    ORDER BY tipo_competencia
                """),
                {"id_postulacion": id_postulacion},
            )
            filas_competencias = [dict(f) for f in result.mappings().all()]
            vigentes, faltantes = competencias_vigentes_y_faltantes(filas_competencias, _date.today())

            if not vigentes or faltantes:

                if not vigentes:
                    motivo = (
                        "El auditor no tiene competencias validadas y vigentes "
                        + ("(no registró ninguna)" if not filas_competencias
                           else "(" + ", ".join(faltantes) + ")")
                        + ". Si lo aprueba, no será elegible para asignaciones "
                        "hasta que tenga una competencia vigente."
                    )
                else:
                    motivo = (
                        "Estas competencias del auditor no están validadas o vigentes: "
                        + ", ".join(faltantes)
                        + ". No será elegible para asignaciones en esas áreas."
                    )

                if not confirmar_sin_competencias:

                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            motivo + " Para aprobarlo debe confirmar expresamente "
                            "y escribir una justificación."
                        ),
                        headers={CABECERA_CONFIRMACION: VALOR_SIN_COMPETENCIAS},
                    )

                justificacion = (justificacion_sin_competencias or "").strip()

                if len(justificacion) < MIN_JUSTIFICACION_SIN_COMPETENCIAS:

                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "La justificación para aprobar sin competencias "
                            f"validadas es obligatoria (mínimo {MIN_JUSTIFICACION_SIN_COMPETENCIAS} caracteres)."
                        ),
                    )

                nota_sin_competencias = (
                    "Aprobado sin competencias validadas y vigentes "
                    f"(confirmado por {rol_confirmacion or 'Coordinador'}). "
                    f"{motivo} Justificación: {justificacion}"
                )

        # ----------------------------------------------------

        if nuevo_estado == "Aprobado":
            for tabla in (
                "titulo_academico",
                "experiencia_laboral",
                "experiencia_auditoria",
            ):
                await self.db.execute(
                    text(
                        f"""
                        UPDATE {tabla}
                        SET estado_validacion = 'Aprobado'
                        WHERE id_postulacion = :id_postulacion
                        """
                    ),
                    {"id_postulacion": id_postulacion},
                )

        # ACTUALIZAR POSTULACIÓN

        # ----------------------------------------------------

        result = await self.db.execute(

            text("""

                UPDATE postulacion_auditor

                SET

                    estado = :nuevo_estado,

                    observaciones_tecnicas = :observaciones,

                    fecha_revision = CURRENT_TIMESTAMP,

                    id_usuario_revisor = :id_usuario_revisor,

                    -- Auditores registrados lee estas columnas para la
                    -- fecha de aprobación o rechazo de la postulación.
                    fecha_aprobacion = CASE WHEN CAST(:nuevo_estado AS VARCHAR) = 'Aprobado'
                        THEN CURRENT_TIMESTAMP ELSE fecha_aprobacion END,

                    fecha_rechazo = CASE WHEN CAST(:nuevo_estado AS VARCHAR) = 'Rechazado'
                        THEN CURRENT_TIMESTAMP ELSE fecha_rechazo END,

                    motivo_rechazo = CASE WHEN CAST(:nuevo_estado AS VARCHAR) = 'Rechazado'
                        THEN NULLIF(CAST(:observaciones AS TEXT), '') ELSE motivo_rechazo END

                WHERE id_postulacion = :id_postulacion

                RETURNING

                    id_postulacion,

                    id_usuario,

                    estado,

                    observaciones_tecnicas,

                    fecha_revision

            """),

            {

                "nuevo_estado": nuevo_estado,

                "observaciones": observaciones_finales,

                "id_postulacion": id_postulacion,

                "id_usuario_revisor": id_usuario_actor,

            },

        )

        actualizada = result.mappings().first()

        if not actualizada:

            await self.db.rollback()

            raise HTTPException(

                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,

                detail="No fue posible actualizar la postulación.",

            )

        # ----------------------------------------------------

        # ACTUALIZAR ESTADO DEL AUDITOR

        # ----------------------------------------------------

        if nuevo_estado == "Aprobado":

            await self.db.execute(

                text("""

                    UPDATE usuario

                    SET estado_auditor = 'Activo'

                    WHERE id_usuario = :id_usuario

                """),

                {

                    "id_usuario": postulacion["id_usuario"],

                },

            )

        elif nuevo_estado == "Rechazado":

            await self.db.execute(

                text("""

                    UPDATE usuario

                    SET estado_auditor = 'Postulante'

                    WHERE id_usuario = :id_usuario

                """),

                {

                    "id_usuario": postulacion["id_usuario"],

                },

            )

        else:

            await self.db.execute(

                text("""

                    UPDATE usuario

                    SET estado_auditor = 'Postulante'

                    WHERE id_usuario = :id_usuario

                """),

                {

                    "id_usuario": postulacion["id_usuario"],

                },

            )

        # ----------------------------------------------------

        # ----------------------------------------------------
        # HISTORIAL DEL CAMBIO
        # ----------------------------------------------------
        # No se usa historial_estado: su FK apunta a solicitud.id_solicitud,
        # mientras este flujo trabaja con postulacion_auditor.id_postulacion.
        # Registramos el evento en el historial específico de postulaciones.
        await self.db.execute(
            text("""
                INSERT INTO historial_postulacion_auditor (
                    id_historial,
                    id_postulacion,
                    id_usuario_auditor,
                    id_usuario_administrador,
                    estado_anterior,
                    estado_nuevo,
                    observaciones,
                    fecha_cambio
                )
                VALUES (
                    gen_random_uuid(),
                    :id_postulacion,
                    :id_usuario_auditor,
                    :id_usuario_administrador,
                    :estado_anterior,
                    :estado_nuevo,
                    :observaciones,
                    CURRENT_TIMESTAMP
                )
            """),
            {
                "id_postulacion": id_postulacion,
                "id_usuario_auditor": postulacion["id_usuario"],
                "id_usuario_administrador": id_usuario_actor,
                "estado_anterior": estado_anterior,
                "estado_nuevo": nuevo_estado,
                # Si se aprobó sin competencias, el historial deja quién lo
                # confirmó (id_usuario_administrador) y la justificación.
                "observaciones": (
                    " ".join(p for p in (nota_sin_competencias, observaciones_finales) if p)
                    or None
                ),
            },
        )

        # NOTIFICACIÓN AL AUDITOR

        # ----------------------------------------------------

        mensajes = {

            "En Revisión": (

                "Su postulación como auditor pasó a estado "

                "'En Revisión'."

            ),

            "Correcciones": (

                "Su postulación como auditor requiere "

                "correcciones."

            ),

            "Aprobado": (

                "Su postulación como auditor fue aprobada."

            ),

            "Rechazado": (

                "Su postulación como auditor fue rechazada."

            ),

        }

        asuntos = {

            "En Revisión": "Postulación en revisión",

            "Correcciones": "Correcciones requeridas",

            "Aprobado": "Postulación aprobada",

            "Rechazado": "Postulación rechazada",

        }

        mensaje = mensajes[nuevo_estado]

        if nuevo_estado == "Rechazado":

            mensaje += f" Motivo del rechazo: {observaciones_finales}"

        elif observaciones_finales:

            mensaje += (

                f" Observaciones del coordinador: "

                f"{observaciones_finales}"

            )

        if nota_sin_competencias:

            mensaje += (
                " Aún no tiene competencias validadas y vigentes en todas las "
                "áreas: no recibirá asignaciones en ellas hasta registrarlas y "
                "que sean validadas."
            )

        # notificacion.mensaje es VARCHAR(255): un motivo largo no debe
        # romper el cambio de estado (el texto completo queda en la
        # postulación y en Consultar estado de registro).
        if len(mensaje) > 255:

            mensaje = mensaje[:252].rstrip() + "..."

        await self.db.execute(

            text("""

                INSERT INTO notificacion (

                    id_notificacion,

                    id_usuario,

                    asunto,

                    mensaje,

                    estado,

                    fecha_envio

                )

                VALUES (

                    gen_random_uuid(),

                    :id_usuario,

                    :asunto,

                    :mensaje,

                    'Pendiente',

                    CURRENT_DATE

                )

            """),

            {

                "id_usuario": postulacion["id_usuario"],

                "asunto": asuntos[nuevo_estado],

                "mensaje": mensaje,

            },

        )

        # ----------------------------------------------------

        # CONFIRMAR

        # ----------------------------------------------------

        await self.db.commit()

        return {

            "mensaje": (

                f"La postulación fue cambiada correctamente "

                f"de '{estado_anterior}' a '{nuevo_estado}'."

            ),

            "id_postulacion": actualizada["id_postulacion"],

            "id_usuario": actualizada["id_usuario"],

            "estado_anterior": estado_anterior,

            "estado_nuevo": actualizada["estado"],

            "observaciones": (

                actualizada["observaciones_tecnicas"]

                or ""

            ),

            "fecha_revision": actualizada["fecha_revision"],

            "id_usuario_actor": id_usuario_actor,

            "notificacion_creada": True,

        }

    # ========================================================

    # REVISIÓN INDIVIDUAL DE DOCUMENTOS

    # ========================================================

    async def revisar_documento(

        self,

        id_documento: UUID,

        estado_revision: str,

        observacion: str | None,

        id_usuario_actor: UUID,

    ):

        if estado_revision not in {"Aprobado", "Rechazado"}:

            raise HTTPException(400, "Estado de documento no válido.")

        observacion_final = (observacion or "").strip()

        if estado_revision == "Rechazado" and not observacion_final:

            raise HTTPException(

                400,

                "Debe indicar la observación que explica el rechazo del documento.",

            )

        result = await self.db.execute(text("""

            SELECT

                id_documento,

                id_postulacion,

                id_usuario,

                estado_revision,

                tipo_documento,

                nombre_archivo

            FROM documento_auditor

            WHERE id_documento = :id_documento

            LIMIT 1

        """), {"id_documento": id_documento})

        documento = result.mappings().first()

        if not documento:

            raise HTTPException(404, "No se encontró el documento.")

        if documento["estado_revision"] == "Aprobado":

            raise HTTPException(

                409,

                "El documento ya fue aprobado y no puede volver a modificarse.",

            )

        result = await self.db.execute(text("""

            UPDATE documento_auditor

            SET

                estado_revision = :estado_revision,

                observacion_revision = :observacion,

                revisado_por = :id_usuario_actor,

                fecha_revision = CURRENT_TIMESTAMP

            WHERE id_documento = :id_documento

            RETURNING

                id_documento,

                id_postulacion,

                estado_revision,

                observacion_revision,

                revisado_por,

                fecha_revision

        """), {

            "id_documento": id_documento,

            "estado_revision": estado_revision,

            "observacion": observacion_final,

            "id_usuario_actor": id_usuario_actor,

        })

        actualizado = result.mappings().first()

        if estado_revision == "Rechazado":

            devuelta = await self.db.execute(text("""

                UPDATE postulacion_auditor

                SET estado = 'Correcciones',

                    fecha_revision = CURRENT_TIMESTAMP,

                    observaciones_tecnicas = COALESCE(observaciones_tecnicas, '')

                WHERE id_postulacion = :id_postulacion

                  AND estado NOT IN ('Aprobado', 'Rechazado', 'Cancelado')

                RETURNING id_postulacion

            """), {"id_postulacion": documento["id_postulacion"]})

            # Solo vuelve a "Postulante" quien tiene su postulación abierta
            # devuelta a Correcciones. Rechazar un documento de una postulación
            # ya cerrada (p. ej. una rechazada antigua) no debe quitarle el
            # estado Activo a un auditor aprobado en otra postulación.
            if devuelta.first() is not None:

                await self.db.execute(text("""

                    UPDATE usuario

                    SET estado_auditor = 'Postulante'

                    WHERE id_usuario = :id_usuario

                """), {"id_usuario": documento["id_usuario"]})

        asunto_notificacion = (
            "Documento aprobado"
            if estado_revision == "Aprobado"
            else "Documento rechazado"
        )
        mensaje_notificacion = (
            f"Su documento '{documento['tipo_documento']}' fue aprobado."
            if estado_revision == "Aprobado"
            else (
                f"Su documento '{documento['tipo_documento']}' fue rechazado. "
                f"Observación del coordinador: {observacion_final}"
            )
        )

        await self.db.execute(text("""

            INSERT INTO notificacion (

                id_notificacion,

                id_usuario,

                asunto,

                mensaje,

                estado,

                fecha_envio,

                leida

            )

            VALUES (

                gen_random_uuid(),

                :id_usuario,

                :asunto,

                :mensaje,

                'Pendiente',

                CURRENT_DATE,

                FALSE

            )

        """), {

            "id_usuario": documento["id_usuario"],

            "asunto": asunto_notificacion,

            "mensaje": mensaje_notificacion,

        })

        await self.db.commit()

        return {

            "mensaje": (

                "Documento aprobado correctamente."

                if estado_revision == "Aprobado"

                else "Documento rechazado. El auditor podrá reemplazarlo en Correcciones."

            ),

            "documento": dict(actualizado),

        }

    async def revisar_validacion_competencia(
        self,
        id_competencia: UUID,
        estado_validacion: str,
        observacion: str | None,
        id_usuario_actor: UUID,
    ):
        """Revisa una competencia con las mismas reglas que un documento.

        El panel envia "Aprobado" y aqui se guarda "Validado", que es el valor
        con el que la tabla de competencias registra la aprobacion.
        """

        if estado_validacion == "Aprobado":
            estado_validacion = "Validado"

        if estado_validacion not in {"Validado", "Rechazado", "Pendiente"}:
            raise HTTPException(400, "Estado de validacion no valido.")

        observacion_final = (observacion or "").strip()

        if estado_validacion == "Rechazado" and not observacion_final:
            raise HTTPException(
                400,
                "La observacion es obligatoria para rechazar la competencia.",
            )

        result = await self.db.execute(text("""
            SELECT
                id_competencia,
                id_postulacion,
                id_usuario,
                tipo_competencia,
                estado_validacion
            FROM competencia_auditor
            WHERE id_competencia = :id_competencia
            LIMIT 1
        """), {"id_competencia": id_competencia})

        competencia = result.mappings().first()

        if not competencia:
            raise HTTPException(404, "No se encontro la competencia.")

        if competencia["estado_validacion"] == "Validado":
            raise HTTPException(
                409,
                "La competencia ya fue aprobada y no puede volver a modificarse.",
            )

        result = await self.db.execute(text("""
            UPDATE competencia_auditor
            SET
                estado_validacion = :estado_validacion,
                observacion_validacion = :observacion
            WHERE id_competencia = :id_competencia
            RETURNING
                id_competencia,
                id_postulacion,
                id_usuario,
                tipo_competencia,
                estado_validacion,
                observacion_validacion
        """), {
            "id_competencia": id_competencia,
            "estado_validacion": estado_validacion,
            "observacion": observacion_final,
        })

        actualizada = result.mappings().first()

        # La devolucion afecta a la postulacion propia de la competencia, igual
        # que hace el rechazo de un documento. Solo las filas antiguas, que no
        # la tienen, recurren a la postulacion activa del auditor.
        id_postulacion = competencia["id_postulacion"]

        if id_postulacion is None:
            result = await self.db.execute(text("""
                SELECT id_postulacion
                FROM postulacion_auditor
                WHERE id_usuario = :id_usuario
                  AND estado IN ('Borrador', 'Correcciones', 'Enviado', 'En Revisión')
                ORDER BY fecha_postulacion DESC
                LIMIT 1
            """), {"id_usuario": competencia["id_usuario"]})

            activa = result.mappings().first()
            id_postulacion = activa["id_postulacion"] if activa else None

        if estado_validacion == "Rechazado":
            devuelta = await self.db.execute(text("""
                UPDATE postulacion_auditor
                SET estado = 'Correcciones',
                    fecha_revision = CURRENT_TIMESTAMP
                WHERE id_postulacion = :id_postulacion
                  AND estado NOT IN ('Aprobado', 'Rechazado', 'Cancelado')
                RETURNING id_postulacion
            """), {"id_postulacion": id_postulacion})

            # Igual que con los documentos: un auditor aprobado no pierde su
            # estado Activo porque se devuelva una competencia de una
            # postulación cerrada o una competencia nueva de su perfil.
            if devuelta.first() is not None:
                await self.db.execute(text("""
                    UPDATE usuario
                    SET estado_auditor = 'Postulante'
                    WHERE id_usuario = :id_usuario
                """), {"id_usuario": competencia["id_usuario"]})

        # El aviso llega al buzon del auditor para que sepa que tiene una
        # correccion pendiente, con la misma forma que usan los documentos.
        if estado_validacion in ("Validado", "Rechazado"):
            tipo_competencia = competencia["tipo_competencia"] or "Competencia"
            aprobada = estado_validacion == "Validado"

            asunto_notificacion = (
                "Competencia aprobada"
                if aprobada
                else "Competencia rechazada"
            )

            mensaje_notificacion = (
                f"Su competencia '{tipo_competencia}' fue aprobada."
                if aprobada
                else (
                    f"Su competencia '{tipo_competencia}' fue rechazada. "
                    f"Observación del coordinador: {observacion_final}"
                )
            )

            await self.db.execute(text("""
                INSERT INTO notificacion (
                    id_notificacion,
                    id_usuario,
                    asunto,
                    mensaje,
                    estado,
                    fecha_envio,
                    leida
                )
                VALUES (
                    gen_random_uuid(),
                    :id_usuario,
                    :asunto,
                    :mensaje,
                    'Pendiente',
                    CURRENT_DATE,
                    FALSE
                )
            """), {
                "id_usuario": competencia["id_usuario"],
                "asunto": asunto_notificacion,
                "mensaje": mensaje_notificacion,
            })

        await self.db.commit()

        return {
            "mensaje": (
                "Competencia aprobada correctamente."
                if estado_validacion == "Validado"
                else (
                    "Competencia rechazada. "
                    "El auditor podra corregirla en Correcciones."
                    if estado_validacion == "Rechazado"
                    else "Competencia revisada correctamente."
                )
            ),
            "competencia": dict(actualizada),
        }
