import asyncio
import hashlib
import hmac
import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import _normalize_role_name
from modules.certificados.certificados_pdf import generar_pdf_certificado
from modules.certificados.firma_pades import FirmaPadesError, firmar_pdf_pades


ESTADO_PENDIENTE_FIRMA = "PENDIENTE_FIRMA"
ESTADO_VIGENTE = "VIGENTE"
ESTADO_SUSPENDIDO = "SUSPENDIDO"
ESTADOS_VISIBLES_PUBLICOS = {ESTADO_VIGENTE}


def es_usuario_empresa(usuario: dict) -> bool:
    return _normalize_role_name(usuario.get("role_name")) == "empresa"


def es_usuario_publico(usuario: dict) -> bool:
    return _normalize_role_name(usuario.get("role_name")) in {"public", "publico"}


def certificado_esta_vigente(certificado: dict, hoy: date | None = None) -> bool:
    fecha_vencimiento = certificado.get("fecha_vencimiento")
    if isinstance(fecha_vencimiento, str):
        try:
            fecha_vencimiento = date.fromisoformat(fecha_vencimiento[:10])
        except ValueError:
            return False
    return (
        str(certificado.get("estado_certificado", "")).strip().upper() == ESTADO_VIGENTE
        and fecha_vencimiento is not None
        and fecha_vencimiento >= (hoy or date.today())
    )


def validar_transicion(estado_actual: str, estado_nuevo: str) -> None:
    actual = (estado_actual or "").strip().upper()
    nuevo = (estado_nuevo or "").strip().upper()
    permitidas = {
        ESTADO_VIGENTE: {ESTADO_SUSPENDIDO, "CANCELADO"},
        ESTADO_SUSPENDIDO: {ESTADO_VIGENTE, "CANCELADO"},
    }
    if nuevo not in permitidas.get(actual, set()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se permite cambiar el certificado de {actual} a {nuevo}.",
        )


class CertificadosService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _empresas_del_usuario(self, usuario: dict) -> list[str]:
        resultado = await self.db.execute(text("""
            SELECT id_empresa
            FROM user_empresa
            WHERE id_usuario = :id_usuario AND estado = 'Activo';
        """), {"id_usuario": str(usuario.get("id_usuario"))})
        return [str(fila["id_empresa"]) for fila in resultado.mappings().all()]

    async def _obtener(self, id_certificado: UUID | str, usuario: dict | None = None) -> dict:
        resultado = await self.db.execute(text("""
            SELECT
                c.id_certificado, c.codigo_verificacion, c.id_comite,
                c.url_certificado, c.fecha_vencimiento, c.estado_certificado,
                c.fecha_emision, c.publico_certificado, c.id_solicitud,
                c.id_alcance, c.fecha_registro, c.fecha_revocacion,
                c.id_asignacion_lider, c.id_firmante, c.huella_firmante,
                c.codigo_hash, c.huella_pdf, firmante.nombre AS nombre_firmante,
                s.numero_radicado, s.id_empresa,
                e.nombre AS empresa, e.nit,
                n.codigo AS norma_codigo, n.nombre AS norma,
                n.version AS norma_version, a.descripcion AS alcance
            FROM certificado c
            JOIN solicitud s ON s.id_solicitud = c.id_solicitud
            JOIN empresa e ON e.id_empresa = s.id_empresa
            LEFT JOIN norma n ON n.id_norma = s.id_norma
            LEFT JOIN alcance_solicitud a ON a.id_alcance = c.id_alcance
            LEFT JOIN usuario firmante ON firmante.id_usuario = c.id_firmante
            WHERE c.id_certificado = :id_certificado;
        """), {"id_certificado": str(id_certificado)})
        certificado = resultado.mappings().first()
        if not certificado:
            raise HTTPException(status_code=404, detail="Certificado no encontrado.")
        certificado = dict(certificado)

        if usuario and es_usuario_publico(usuario):
            if not certificado.get("publico_certificado") or not certificado_esta_vigente(certificado):
                raise HTTPException(status_code=404, detail="Certificado no encontrado.")
            if (
                not certificado.get("id_firmante")
                or not certificado.get("huella_firmante")
                or not certificado.get("codigo_hash")
                or not certificado.get("huella_pdf")
            ):
                raise HTTPException(status_code=404, detail="Certificado no encontrado.")
            campos_publicos = {
                "codigo_verificacion", "estado_certificado", "fecha_emision",
                "fecha_vencimiento", "numero_radicado", "empresa", "nit",
                "norma_codigo", "norma", "norma_version", "alcance",
                "firmante", "huella_pdf", "huella_certificado",
            }
            return {campo: valor for campo, valor in certificado.items() if campo in campos_publicos}

        if usuario and es_usuario_empresa(usuario):
            empresas = await self._empresas_del_usuario(usuario)
            if str(certificado["id_empresa"]) not in empresas:
                raise HTTPException(status_code=404, detail="Certificado no encontrado.")
        return certificado

    async def listar(self, usuario: dict, limite: int = 100, desplazamiento: int = 0) -> list[dict]:
        params: dict = {"limite": limite, "desplazamiento": desplazamiento}
        if es_usuario_publico(usuario):
            resultado = await self.db.execute(text("""
                SELECT c.codigo_verificacion, c.estado_certificado,
                       c.fecha_emision, c.fecha_vencimiento,
                       s.numero_radicado, e.nombre AS empresa, e.nit,
                       n.codigo AS norma_codigo
                FROM certificado c
                JOIN solicitud s ON s.id_solicitud = c.id_solicitud
                JOIN empresa e ON e.id_empresa = s.id_empresa
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE c.publico_certificado IS TRUE
                                    AND c.id_firmante IS NOT NULL
                                      AND c.huella_firmante IS NOT NULL
                                      AND c.codigo_hash IS NOT NULL
                                      AND c.huella_pdf IS NOT NULL
                                    AND c.id_firmante IS NOT NULL
                                    AND c.codigo_hash IS NOT NULL
                  AND TRIM(UPPER(c.estado_certificado)) = 'VIGENTE'
                  AND c.fecha_vencimiento >= CURRENT_DATE
                ORDER BY c.fecha_emision DESC NULLS LAST
                LIMIT :limite OFFSET :desplazamiento;
            """), params)
            return [dict(fila) for fila in resultado.mappings().all()]

        filtro_empresa = ""
        if es_usuario_empresa(usuario):
            empresas = await self._empresas_del_usuario(usuario)
            if not empresas:
                return []
            filtro_empresa = " AND s.id_empresa IN (" + ", ".join(
                f":empresa_{i}" for i in range(len(empresas))
            ) + ")"
            params.update({f"empresa_{i}": empresa for i, empresa in enumerate(empresas)})

        resultado = await self.db.execute(text(f"""
            SELECT
                c.id_certificado, c.codigo_verificacion, c.fecha_emision,
                c.fecha_vencimiento, c.estado_certificado, c.publico_certificado,
                c.id_solicitud, c.id_alcance, s.numero_radicado,
                e.nombre AS empresa, e.nit, n.codigo AS norma_codigo
            FROM certificado c
            JOIN solicitud s ON s.id_solicitud = c.id_solicitud
            JOIN empresa e ON e.id_empresa = s.id_empresa
            LEFT JOIN norma n ON n.id_norma = s.id_norma
            WHERE 1 = 1 {filtro_empresa}
            ORDER BY c.fecha_emision DESC NULLS LAST, c.fecha_registro DESC
            LIMIT :limite OFFSET :desplazamiento;
        """), params)
        return [dict(fila) for fila in resultado.mappings().all()]

    async def listar_lideres_comite(self) -> list[dict]:
        resultado = await self.db.execute(text("""
            SELECT u.id_usuario, u.nombre, u.correo
            FROM usuario u
            JOIN rol r ON r.id_rol = u.rol_id
            WHERE u.estado = 'Activo'
              AND LOWER(TRANSLATE(r.nombre, 'ÁÉÍÓÚáéíóú', 'AEIOUaeiou'))
                  IN ('comite', 'comite de certificacion')
            ORDER BY u.nombre;
        """))
        return [dict(fila) for fila in resultado.mappings().all()]

    async def lider_comite_actual(self) -> dict | None:
        resultado = await self.db.execute(text("""
            SELECT a.id_asignacion, a.id_usuario, a.fecha_inicio,
                   u.nombre, u.correo
            FROM asignacion_lider_comite a
            JOIN usuario u ON u.id_usuario = a.id_usuario
                        JOIN rol r ON r.id_rol = u.rol_id
                        WHERE a.fecha_fin IS NULL
                            AND u.estado = 'Activo'
              AND LOWER(TRANSLATE(r.nombre, 'ÁÉÍÓÚáéíóú', 'AEIOUaeiou'))
                  IN ('comite', 'comite de certificacion')
            ORDER BY a.fecha_inicio DESC
            LIMIT 1;
        """))
        fila = resultado.mappings().first()
        return dict(fila) if fila else None

    async def mi_liderazgo(self, usuario: dict) -> dict:
        lider = await self.lider_comite_actual()
        es_persona_asignada = bool(
            lider and str(lider["id_usuario"]) == str(usuario.get("id_usuario"))
        )
        rol = _normalize_role_name(usuario.get("role_name"))
        if lider and rol not in {"admin", "superadmin"} and not es_persona_asignada:
            lider = {"nombre": lider["nombre"]}
        return {
            "es_lider": es_persona_asignada,
            "lider": lider,
        }

    async def asignar_lider_comite(self, id_usuario: UUID, actor: dict) -> dict:
        await self.db.execute(text("SELECT pg_advisory_xact_lock(76139521, 11);"))
        candidato = await self.db.execute(text("""
            SELECT u.id_usuario, u.nombre, u.correo
            FROM usuario u
            JOIN rol r ON r.id_rol = u.rol_id
            WHERE u.id_usuario = :id_usuario
              AND u.estado = 'Activo'
              AND LOWER(TRANSLATE(r.nombre, 'ÁÉÍÓÚáéíóú', 'AEIOUaeiou'))
                  IN ('comite', 'comite de certificacion')
            FOR UPDATE OF u;
        """), {"id_usuario": str(id_usuario)})
        lider = candidato.mappings().first()
        if not lider:
            raise HTTPException(
                status_code=422,
                detail="El líder debe ser un usuario activo con rol Comité.",
            )

        actual = await self.db.execute(text("""
            SELECT id_asignacion, id_usuario
            FROM asignacion_lider_comite
            WHERE fecha_fin IS NULL
            FOR UPDATE;
        """))
        asignacion_actual = actual.mappings().first()
        if (
            asignacion_actual
            and str(asignacion_actual["id_usuario"]) == str(id_usuario)
        ):
            await self.db.commit()
            return await self.lider_comite_actual()

        if asignacion_actual:
            await self.db.execute(text("""
                UPDATE asignacion_lider_comite
                SET fecha_fin = CURRENT_TIMESTAMP
                WHERE id_asignacion = :id_asignacion;
            """), {"id_asignacion": str(asignacion_actual["id_asignacion"])})

        nueva_asignacion = uuid4()
        await self.db.execute(text("""
            INSERT INTO asignacion_lider_comite (
                id_asignacion, id_usuario, asignado_por, fecha_inicio
            ) VALUES (
                :id_asignacion, :id_usuario, :asignado_por, CURRENT_TIMESTAMP
            );
        """), {
            "id_asignacion": str(nueva_asignacion),
            "id_usuario": str(id_usuario),
            "asignado_por": str(actor.get("id_usuario")),
        })

        pendientes = await self.db.execute(text("""
            UPDATE certificado
            SET id_asignacion_lider = :id_asignacion
            WHERE TRIM(UPPER(estado_certificado)) = :estado
              AND (id_asignacion_lider IS NULL OR id_asignacion_lider = :anterior)
            RETURNING id_certificado, codigo_verificacion;
        """), {
            "id_asignacion": str(nueva_asignacion),
            "estado": ESTADO_PENDIENTE_FIRMA,
            "anterior": str(asignacion_actual["id_asignacion"]) if asignacion_actual else None,
        })
        for certificado in pendientes.mappings().all():
            await self._registrar_historial(
                certificado["id_certificado"],
                ESTADO_PENDIENTE_FIRMA,
                ESTADO_PENDIENTE_FIRMA,
                actor,
                f"Líder de firma asignado: {lider['nombre']} ({lider['correo']}).",
            )

        await self.db.commit()
        return await self.lider_comite_actual()

    async def crear(
        self,
        data,
        usuario: dict,
        detalle_inicial: str | None = None,
        es_renovacion: bool = False,
    ) -> dict:
        solicitud_resultado = await self.db.execute(text("""
            SELECT id_solicitud, estado
            FROM solicitud
            WHERE id_solicitud = :id_solicitud
            FOR UPDATE
        """), {"id_solicitud": str(data.id_solicitud)})
        solicitud = solicitud_resultado.mappings().first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada.")
        if str(solicitud["estado"]).strip().upper() not in {"APROBADA", "APROBADO", "CERTIFICADA"}:
            raise HTTPException(
                status_code=409,
                detail="Solo se puede generar un certificado para una solicitud aprobada.",
            )
        if not es_renovacion:
            certificado_existente = await self.db.execute(text("""
                SELECT id_certificado
                FROM certificado
                WHERE id_solicitud = :id_solicitud
                LIMIT 1;
            """), {"id_solicitud": str(data.id_solicitud)})
            if certificado_existente.scalar_one_or_none():
                raise HTTPException(
                    status_code=409,
                    detail="La solicitud ya tiene un certificado. Use la operación de renovación.",
                )

        alcance_resultado = await self.db.execute(text("""
            SELECT id_alcance
            FROM alcance_solicitud
            WHERE id_alcance = :id_alcance AND id_solicitud = :id_solicitud;
        """), {
            "id_alcance": str(data.id_alcance),
            "id_solicitud": str(data.id_solicitud),
        })
        if not alcance_resultado.scalar_one_or_none():
            raise HTTPException(status_code=422, detail="El alcance no pertenece a la solicitud indicada.")

        asignacion_lider = await self.db.execute(text("""
            SELECT id_asignacion
            FROM asignacion_lider_comite
            WHERE fecha_fin IS NULL
            ORDER BY fecha_inicio DESC
            LIMIT 1
            FOR SHARE;
        """))
        asignacion = asignacion_lider.mappings().first()
        if not asignacion:
            raise HTTPException(
                status_code=409,
                detail="Asigne primero un líder activo del Comité para la firma de certificados.",
            )

        consecutivo_resultado = await self.db.execute(text("SELECT nextval('certificado_codigo_seq');"))
        consecutivo = consecutivo_resultado.scalar_one()
        hoy = date.today()
        codigo = f"CS-{hoy.year}-{consecutivo:06d}"
        codigo_hash = hashlib.sha256(codigo.encode("utf-8")).hexdigest()
        fecha_vencimiento = data.fecha_vencimiento
        if fecha_vencimiento <= hoy:
            raise HTTPException(status_code=422, detail="La fecha de vencimiento debe ser futura.")

        id_certificado = uuid4()
        resultado = await self.db.execute(text("""
            INSERT INTO certificado (
                id_certificado, codigo_hash, id_comite, fecha_vencimiento,
                estado_certificado, fecha_emision, publico_certificado,
                id_solicitud, id_alcance, fecha_registro, codigo_verificacion,
                id_asignacion_lider
            ) VALUES (
                :id_certificado, :codigo_hash, :id_comite, :fecha_vencimiento,
                :estado, NULL, FALSE,
                :id_solicitud, :id_alcance, CURRENT_TIMESTAMP, :codigo,
                :id_asignacion_lider
            )
            RETURNING id_certificado;
        """), {
            "id_certificado": str(id_certificado),
            "codigo_hash": codigo_hash,
            "id_comite": None,
            "fecha_vencimiento": fecha_vencimiento,
            "estado": ESTADO_PENDIENTE_FIRMA,
            "id_solicitud": str(data.id_solicitud),
            "id_alcance": str(data.id_alcance),
            "codigo": codigo,
            "id_asignacion_lider": str(asignacion["id_asignacion"]),
        })
        await self._registrar_historial(
            id_certificado, None, ESTADO_PENDIENTE_FIRMA, usuario,
            detalle_inicial or "Certificado generado; pendiente de firma digital.",
        )
        await self.db.commit()
        return await self._obtener(resultado.scalar_one())

    async def renovar(self, id_certificado: UUID, fecha_vencimiento: date, usuario: dict) -> dict:
        from modules.certificados.certificados_schema import CertificadoCrear

        anterior = await self._obtener(id_certificado, usuario)
        if str(anterior["estado_certificado"]).strip().upper() not in {ESTADO_VIGENTE, "VENCIDO"}:
            raise HTTPException(status_code=409, detail="Solo se puede renovar un certificado vigente o vencido.")
        if (
            anterior["fecha_vencimiento"]
            and fecha_vencimiento <= anterior["fecha_vencimiento"]
        ):
            raise HTTPException(
                status_code=422,
                detail="La fecha de vencimiento de la renovación debe ampliar el ciclo actual.",
            )
        return await self.crear(
            CertificadoCrear(
                id_solicitud=anterior["id_solicitud"],
                id_alcance=anterior["id_alcance"],
                fecha_vencimiento=fecha_vencimiento,
            ),
            usuario,
            f"Renovación del certificado {anterior['codigo_verificacion']}; pendiente de firma digital.",
            es_renovacion=True,
        )

    async def firmar_con_lider_asignado(self, id_certificado: UUID, usuario: dict) -> dict:
        await self.db.execute(text("SELECT pg_advisory_xact_lock(76139521, 11);"))
        resultado = await self.db.execute(text("""
            SELECT c.estado_certificado, c.id_asignacion_lider,
                   a.id_usuario AS id_lider, u.nombre AS nombre_lider,
                   u.correo AS correo_lider
            FROM certificado c
            JOIN asignacion_lider_comite a
              ON a.id_asignacion = c.id_asignacion_lider
             AND a.fecha_fin IS NULL
            JOIN usuario u ON u.id_usuario = a.id_usuario
                        JOIN rol r ON r.id_rol = u.rol_id
            WHERE c.id_certificado = :id_certificado
                            AND u.estado = 'Activo'
              AND LOWER(TRANSLATE(r.nombre, 'ÁÉÍÓÚáéíóú', 'AEIOUaeiou'))
                  IN ('comite', 'comite de certificacion')
            FOR UPDATE OF c, a;
        """), {"id_certificado": str(id_certificado)})
        asignacion = resultado.mappings().first()
        if not asignacion:
            raise HTTPException(
                status_code=409,
                detail="El certificado no tiene una asignación de líder activa.",
            )
        if str(asignacion["estado_certificado"]).strip().upper() != ESTADO_PENDIENTE_FIRMA:
            raise HTTPException(status_code=409, detail="El certificado ya no está pendiente de firma.")
        if str(asignacion["id_lider"]) != str(usuario.get("id_usuario")):
            raise HTTPException(
                status_code=403,
                detail="Solo el líder del Comité asignado a este certificado puede firmarlo.",
            )

        certificado = await self._obtener(id_certificado)
        datos_pdf = {
            **certificado,
            "estado_certificado": ESTADO_VIGENTE,
            "fecha_emision": date.today(),
            "nombre_firmante": asignacion["nombre_lider"],
        }
        pdf_borrador = generar_pdf_certificado(datos_pdf, modo="firma")
        try:
            pdf_firmado, huella_pdf, huella_certificado = await asyncio.to_thread(
                firmar_pdf_pades,
                pdf_borrador,
                asignacion["id_lider"],
                asignacion["correo_lider"],
            )
        except FirmaPadesError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        directorio = Path(settings.CERTIFICADOS_STORAGE_DIR).expanduser().resolve()
        directorio.mkdir(parents=True, exist_ok=True)
        archivo_final = directorio / f"{id_certificado}.pdf"
        descriptor, archivo_temporal = tempfile.mkstemp(
            prefix=f"{id_certificado}-", suffix=".pdf.tmp", dir=directorio
        )
        try:
            with os.fdopen(descriptor, "wb") as archivo:
                archivo.write(pdf_firmado)
                archivo.flush()
                os.fsync(archivo.fileno())
            os.replace(archivo_temporal, archivo_final)
            await self.db.execute(text("""
                UPDATE certificado
                SET estado_certificado = :estado,
                    fecha_emision = CURRENT_DATE,
                    id_firmante = :id_firmante,
                    huella_firmante = :huella_firmante,
                    huella_pdf = :huella_pdf,
                    url_certificado = :url_certificado,
                    publico_certificado = FALSE
                WHERE id_certificado = :id_certificado;
            """), {
                "estado": ESTADO_VIGENTE,
                "id_firmante": str(asignacion["id_lider"]),
                "huella_firmante": huella_certificado,
                "huella_pdf": huella_pdf,
                "url_certificado": f"/certificados/{id_certificado}/pdf",
                "id_certificado": str(id_certificado),
            })
            await self._registrar_historial(
                id_certificado,
                ESTADO_PENDIENTE_FIRMA,
                ESTADO_VIGENTE,
                usuario,
                f"Firma digital PAdES aplicada. Huella SHA-256: {huella_pdf}.",
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            archivo_final.unlink(missing_ok=True)
            raise
        finally:
            Path(archivo_temporal).unlink(missing_ok=True)

        return await self._obtener(id_certificado)

    def _leer_pdf_firmado(self, id_certificado: UUID | str, huella_esperada: str | None) -> bytes:
        archivo = Path(settings.CERTIFICADOS_STORAGE_DIR).expanduser().resolve() / f"{id_certificado}.pdf"
        try:
            contenido = archivo.read_bytes()
        except OSError as exc:
            raise HTTPException(status_code=404, detail="No se encontró el PDF firmado.") from exc
        if not huella_esperada or not hmac.compare_digest(
            hashlib.sha256(contenido).hexdigest(), huella_esperada
        ):
            raise HTTPException(status_code=409, detail="La huella del PDF no coincide; se bloqueó la descarga.")
        return contenido

    async def pdf_firmado(self, id_certificado: UUID, usuario: dict) -> bytes:
        certificado = await self._obtener(id_certificado, usuario)
        if (
            not certificado_esta_vigente(certificado)
            or not certificado.get("id_firmante")
            or not certificado.get("huella_firmante")
        ):
            raise HTTPException(status_code=409, detail="El certificado aún no tiene una firma digital válida.")
        return self._leer_pdf_firmado(id_certificado, certificado.get("huella_pdf"))

    async def pdf_publico_firmado(self, codigo: str) -> bytes:
        resultado = await self.db.execute(text("""
            SELECT c.id_certificado, c.huella_pdf
            FROM certificado c
            WHERE c.codigo_verificacion = :codigo
              AND c.publico_certificado IS TRUE
              AND c.id_firmante IS NOT NULL
              AND c.huella_firmante IS NOT NULL
              AND c.codigo_hash IS NOT NULL
                              AND c.huella_pdf IS NOT NULL
              AND TRIM(UPPER(c.estado_certificado)) = 'VIGENTE'
              AND c.fecha_vencimiento >= CURRENT_DATE;
        """), {"codigo": codigo})
        fila = resultado.mappings().first()
        if not fila:
            raise HTTPException(status_code=404, detail="Certificado público no encontrado.")
        return self._leer_pdf_firmado(fila["id_certificado"], fila["huella_pdf"])

    async def _registrar_historial(
        self,
        id_certificado: UUID | str,
        estado_anterior: str | None,
        estado_nuevo: str,
        usuario: dict,
        motivo: str,
    ) -> None:
        await self.db.execute(text("""
            INSERT INTO historial_certificado (
                id_historial, id_certificado, estado_anterior, estado_nuevo,
                motivo, id_usuario, fecha
            ) VALUES (
                :id_historial, :id_certificado, :estado_anterior, :estado_nuevo,
                :motivo, :id_usuario, CURRENT_TIMESTAMP
            );
        """), {
            "id_historial": str(uuid4()),
            "id_certificado": str(id_certificado),
            "estado_anterior": estado_anterior,
            "estado_nuevo": estado_nuevo,
            "motivo": motivo,
            "id_usuario": str(usuario.get("id_usuario")),
        })

    async def cambiar_estado(
        self,
        id_certificado: UUID,
        estado_nuevo: str,
        motivo: str,
        usuario: dict,
    ) -> dict:
        resultado = await self.db.execute(text("""
                         SELECT estado_certificado, fecha_vencimiento, url_certificado,
                             id_firmante, huella_firmante, codigo_hash, huella_pdf
            FROM certificado
            WHERE id_certificado = :id_certificado
            FOR UPDATE;
        """), {"id_certificado": str(id_certificado)})
        certificado = resultado.mappings().first()
        if not certificado:
            raise HTTPException(status_code=404, detail="Certificado no encontrado.")
        estado_anterior = str(certificado["estado_certificado"])
        if estado_nuevo == ESTADO_VIGENTE and (
            not certificado["fecha_vencimiento"]
            or certificado["fecha_vencimiento"] < date.today()
        ):
            raise HTTPException(
                status_code=409,
                detail="No se puede reactivar un certificado vencido; debe renovarse.",
            )
        validar_transicion(estado_anterior, estado_nuevo)
        await self.db.execute(text("""
            UPDATE certificado
            SET estado_certificado = :estado,
                fecha_revocacion = CASE
                    WHEN :estado = 'CANCELADO' THEN CURRENT_TIMESTAMP
                    WHEN :estado = 'VIGENTE' THEN NULL
                    ELSE fecha_revocacion
                END,
                publico_certificado = CASE
                    WHEN :estado <> 'VIGENTE' THEN FALSE
                    ELSE publico_certificado
                END
            WHERE id_certificado = :id_certificado;
        """), {"estado": estado_nuevo, "id_certificado": str(id_certificado)})
        await self._registrar_historial(id_certificado, estado_anterior, estado_nuevo, usuario, motivo)
        await self.db.commit()
        return await self._obtener(id_certificado)

    async def registrar_motivo_cancelacion(
        self,
        id_certificado: UUID,
        motivo: str,
        usuario: dict,
    ) -> dict:
        certificado = await self._obtener(id_certificado)
        estado = str(certificado["estado_certificado"])
        await self._registrar_historial(
            id_certificado,
            estado,
            estado,
            usuario,
            f"Motivo de cancelación registrado: {motivo}",
        )
        await self.db.commit()
        return {"registrado": True, "id_certificado": str(id_certificado)}

    async def registrar_motivo_suspension(
        self,
        id_certificado: UUID,
        motivo: str,
        usuario: dict,
    ) -> dict:
        certificado = await self._obtener(id_certificado)
        estado = str(certificado["estado_certificado"])
        if not certificado_esta_vigente(certificado):
            raise HTTPException(
                status_code=409,
                detail="Solo se puede registrar el motivo de suspensión de un certificado vigente.",
            )
        await self._registrar_historial(
            id_certificado,
            estado,
            estado,
            usuario,
            f"Motivo de suspensión registrado: {motivo}",
        )
        await self.db.commit()
        return {"registrado": True, "id_certificado": str(id_certificado)}

    async def cambiar_publicacion(self, id_certificado: UUID, publicar: bool, usuario: dict) -> dict:
        resultado = await self.db.execute(text("""
            SELECT estado_certificado, fecha_vencimiento, url_certificado
            FROM certificado
            WHERE id_certificado = :id_certificado
            FOR UPDATE;
        """), {"id_certificado": str(id_certificado)})
        certificado = resultado.mappings().first()
        if not certificado:
            raise HTTPException(status_code=404, detail="Certificado no encontrado.")
        if publicar and not certificado_esta_vigente(certificado):
            raise HTTPException(status_code=409, detail="Solo se puede publicar un certificado vigente.")
        if publicar and not certificado.get("url_certificado"):
            raise HTTPException(
                status_code=409,
                detail="No se puede publicar sin el archivo oficial firmado registrado.",
            )
        if publicar and (
            not certificado.get("id_firmante")
            or not certificado.get("huella_firmante")
            or not certificado.get("codigo_hash")
            or not certificado.get("huella_pdf")
        ):
            raise HTTPException(
                status_code=409,
                detail="No se puede publicar un certificado sin firma digital PAdES registrada.",
            )
        await self.db.execute(text("""
            UPDATE certificado
            SET publico_certificado = :publicar
            WHERE id_certificado = :id_certificado;
        """), {"publicar": publicar, "id_certificado": str(id_certificado)})
        estado = str(certificado["estado_certificado"])
        accion = "publicado" if publicar else "retirado del portal público"
        await self._registrar_historial(
            id_certificado, estado, estado, usuario, f"Certificado {accion}."
        )
        await self.db.commit()
        return await self._obtener(id_certificado)

    async def historial(self, id_certificado: UUID, usuario: dict) -> list[dict]:
        await self._obtener(id_certificado, usuario)
        if es_usuario_publico(usuario):
            resultado = await self.db.execute(text("""
                SELECT h.estado_nuevo, h.fecha
                FROM historial_certificado h
                WHERE h.id_certificado = :id_certificado
                ORDER BY h.fecha DESC;
            """), {"id_certificado": str(id_certificado)})
            return [dict(fila) for fila in resultado.mappings().all()]
        resultado = await self.db.execute(text("""
            SELECT h.estado_anterior, h.estado_nuevo, h.motivo, h.fecha,
                   u.nombre AS usuario
            FROM historial_certificado h
            LEFT JOIN usuario u ON u.id_usuario = h.id_usuario
            WHERE h.id_certificado = :id_certificado
            ORDER BY h.fecha DESC;
        """), {"id_certificado": str(id_certificado)})
        return [dict(fila) for fila in resultado.mappings().all()]

    async def publico(self, codigo: str) -> dict:
        resultado = await self.db.execute(text("""
            SELECT
                c.codigo_verificacion, c.estado_certificado, c.fecha_emision,
                c.fecha_vencimiento, c.huella_pdf,
                c.huella_firmante AS huella_certificado,
                firmante.nombre AS firmante, e.nombre AS empresa,
                e.nit, n.codigo AS norma_codigo, n.nombre AS norma,
                n.version AS norma_version, a.descripcion AS alcance
            FROM certificado c
            JOIN solicitud s ON s.id_solicitud = c.id_solicitud
            JOIN empresa e ON e.id_empresa = s.id_empresa
            LEFT JOIN norma n ON n.id_norma = s.id_norma
            LEFT JOIN alcance_solicitud a ON a.id_alcance = c.id_alcance
            LEFT JOIN usuario firmante ON firmante.id_usuario = c.id_firmante
            WHERE c.codigo_verificacion = :codigo
                            AND c.publico_certificado IS TRUE
                            AND c.id_firmante IS NOT NULL
                              AND c.huella_firmante IS NOT NULL
                              AND c.codigo_hash IS NOT NULL
                              AND c.huella_pdf IS NOT NULL
              AND TRIM(UPPER(c.estado_certificado)) = 'VIGENTE'
                            AND c.fecha_vencimiento >= CURRENT_DATE;
        """), {"codigo": codigo})
        certificado = resultado.mappings().first()
        if not certificado:
            raise HTTPException(status_code=404, detail="Certificado público no encontrado.")
        return dict(certificado)

    async def actualizar_alcance(self, id_certificado: UUID, id_alcance: UUID, usuario: dict) -> dict:
        certificado = await self._obtener(id_certificado)
        if not certificado_esta_vigente(certificado):
            raise HTTPException(status_code=409, detail="Solo se puede cambiar el alcance de un certificado vigente.")
        if str(certificado["id_alcance"]) == str(id_alcance):
            raise HTTPException(status_code=409, detail="El alcance seleccionado ya está asociado al certificado.")
        resultado = await self.db.execute(text("""
            SELECT id_alcance
            FROM alcance_solicitud
            WHERE id_alcance = :id_alcance AND id_solicitud = :id_solicitud;
        """), {"id_alcance": str(id_alcance), "id_solicitud": str(certificado["id_solicitud"])})
        if not resultado.scalar_one_or_none():
            raise HTTPException(status_code=422, detail="El alcance no pertenece a la solicitud del certificado.")
        await self.db.execute(text("""
            UPDATE certificado
            SET id_alcance = :id_alcance,
                estado_certificado = :estado_pendiente,
                fecha_emision = NULL,
                url_certificado = NULL,
                publico_certificado = FALSE,
                id_firmante = NULL,
                huella_firmante = NULL,
                huella_pdf = NULL
            WHERE id_certificado = :id_certificado;
        """), {
            "id_alcance": str(id_alcance),
            "estado_pendiente": ESTADO_PENDIENTE_FIRMA,
            "id_certificado": str(id_certificado),
        })
        estado = str(certificado["estado_certificado"])
        await self._registrar_historial(
            id_certificado, estado, ESTADO_PENDIENTE_FIRMA, usuario,
            f"Alcance actualizado a {id_alcance}.",
        )
        await self.db.commit()
        return await self._obtener(id_certificado)

    async def metricas(self) -> dict:
        resultado = await self.db.execute(text("""
            SELECT
                COUNT(*) AS total,
                COUNT(*) FILTER (
                    WHERE TRIM(UPPER(estado_certificado)) = 'VIGENTE'
                      AND fecha_vencimiento >= CURRENT_DATE
                ) AS vigentes,
                COUNT(*) FILTER (WHERE TRIM(UPPER(estado_certificado)) = 'SUSPENDIDO') AS suspendidos,
                COUNT(*) FILTER (WHERE TRIM(UPPER(estado_certificado)) = 'CANCELADO') AS cancelados,
                COUNT(*) FILTER (
                    WHERE publico_certificado IS TRUE
                                            AND id_firmante IS NOT NULL
                                              AND huella_firmante IS NOT NULL
                                              AND codigo_hash IS NOT NULL
                                              AND huella_pdf IS NOT NULL
                      AND TRIM(UPPER(estado_certificado)) = 'VIGENTE'
                      AND fecha_vencimiento >= CURRENT_DATE
                ) AS publicados,
                COUNT(*) FILTER (
                    WHERE fecha_vencimiento BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days'
                      AND TRIM(UPPER(estado_certificado)) = 'VIGENTE'
                ) AS proximos_a_vencer
            FROM certificado;
        """))
        return dict(resultado.mappings().one())

    async def metricas_publicas(self) -> dict:
        resultado = await self.db.execute(text("""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (
                       WHERE fecha_vencimiento <= CURRENT_DATE + INTERVAL '30 days'
                   ) AS proximos_a_vencer
            FROM certificado
            WHERE publico_certificado IS TRUE
                            AND id_firmante IS NOT NULL
                              AND huella_firmante IS NOT NULL
                              AND codigo_hash IS NOT NULL
                              AND huella_pdf IS NOT NULL
              AND TRIM(UPPER(estado_certificado)) = 'VIGENTE'
              AND fecha_vencimiento >= CURRENT_DATE;
        """))
        metricas = resultado.mappings().one()
        total = metricas["total"]
        return {
            "total": total,
            "vigentes": total,
            "publicados": total,
            "proximos_a_vencer": metricas["proximos_a_vencer"],
        }

    async def _correo_empresa(self, id_certificado: UUID) -> str | None:
        resultado = await self.db.execute(text("""
            SELECT e.correo
            FROM certificado c
            JOIN solicitud s ON s.id_solicitud = c.id_solicitud
            JOIN empresa e ON e.id_empresa = s.id_empresa
            WHERE c.id_certificado = :id_certificado;
        """), {"id_certificado": str(id_certificado)})
        fila = resultado.mappings().first()
        return fila["correo"] if fila else None

    async def alertas_vencimiento(self, dias: int, usuario: dict) -> list[dict]:
        params: dict = {"dias": dias}
        filtro_empresa = ""
        if es_usuario_empresa(usuario):
            empresas = await self._empresas_del_usuario(usuario)
            if not empresas:
                return []
            filtro_empresa = " AND s.id_empresa IN (" + ", ".join(
                f":empresa_{i}" for i in range(len(empresas))
            ) + ")"
            params.update({f"empresa_{i}": empresa for i, empresa in enumerate(empresas)})
        resultado = await self.db.execute(text("""
            SELECT c.id_certificado, c.codigo_verificacion, c.fecha_vencimiento,
                   e.nombre AS empresa, e.nit
            FROM certificado c
            JOIN solicitud s ON s.id_solicitud = c.id_solicitud
            JOIN empresa e ON e.id_empresa = s.id_empresa
            WHERE TRIM(UPPER(c.estado_certificado)) = 'VIGENTE'
              AND c.fecha_vencimiento BETWEEN CURRENT_DATE
                  AND CURRENT_DATE + (:dias * INTERVAL '1 day')
        """ + filtro_empresa + """
            ORDER BY c.fecha_vencimiento;
        """), params)
        return [dict(fila) for fila in resultado.mappings().all()]

    async def empresas_oficiales(self) -> list[dict]:
        resultado = await self.db.execute(text("""
            SELECT DISTINCT ON (e.id_empresa)
                   e.nombre AS empresa, e.nit, e.ciudad,
                   n.codigo AS norma_codigo, c.fecha_emision,
                   c.fecha_vencimiento, c.codigo_verificacion
            FROM certificado c
            JOIN solicitud s ON s.id_solicitud = c.id_solicitud
            JOIN empresa e ON e.id_empresa = s.id_empresa
            LEFT JOIN norma n ON n.id_norma = s.id_norma
            WHERE TRIM(UPPER(c.estado_certificado)) = 'VIGENTE'
                            AND c.fecha_vencimiento >= CURRENT_DATE
            ORDER BY e.id_empresa, c.fecha_emision DESC NULLS LAST;
        """))
        return [dict(fila) for fila in resultado.mappings().all()]

    async def reenviar(self, id_certificado: UUID, usuario: dict) -> dict:
        from pathlib import Path
        from tempfile import NamedTemporaryFile

        from fastapi_mail import FastMail, MessageSchema, MessageType

        from core.config import settings
        from core.mail import conf
        certificado = await self._obtener(id_certificado, usuario)
        correo = await self._correo_empresa(id_certificado)
        if not certificado_esta_vigente(certificado):
            raise HTTPException(status_code=409, detail="Solo se puede reenviar un certificado vigente.")
        if not correo:
            raise HTTPException(status_code=422, detail="La empresa no tiene correo registrado.")
        if not settings.MAIL_SERVER or not settings.MAIL_FROM:
            raise HTTPException(status_code=503, detail="El servicio de correo no está configurado.")

        archivo = None
        try:
            with NamedTemporaryFile(suffix=".pdf", delete=False) as temporal:
                temporal.write(await self.pdf_firmado(id_certificado, usuario))
                archivo = Path(temporal.name)
            mensaje = MessageSchema(
                subject=f"Certificado firmado {certificado['codigo_verificacion']} - CertiSENA",
                recipients=[correo],
                body=(
                    f"Se adjunta el certificado de {certificado['empresa']}, firmado digitalmente "
                    f"por {certificado.get('nombre_firmante') or 'el líder asignado del Comité'}. "
                    f"Código de verificación: {certificado['codigo_verificacion']}."
                ),
                subtype=MessageType.plain,
                attachments=[{
                    "file": str(archivo),
                    "headers": {"Content-Disposition": f'attachment; filename="{certificado["codigo_verificacion"]}.pdf"'},
                    "mime_type": "application",
                    "mime_subtype": "pdf",
                }],
            )
            await FastMail(conf).send_message(mensaje)
        finally:
            if archivo:
                archivo.unlink(missing_ok=True)
        return {"enviado": True}

    async def notificar_vencimiento(self, id_certificado: UUID, dias: int, usuario: dict) -> dict:
        from fastapi_mail import FastMail, MessageSchema, MessageType

        from core.config import settings
        from core.mail import conf

        certificado = await self._obtener(id_certificado, usuario)
        correo = await self._correo_empresa(id_certificado)
        vencimiento = certificado["fecha_vencimiento"]
        if (
            str(certificado["estado_certificado"]).strip().upper() != ESTADO_VIGENTE
            or not vencimiento
            or vencimiento < date.today()
            or vencimiento > date.today() + timedelta(days=dias)
        ):
            raise HTTPException(status_code=409, detail="El certificado no vence dentro del periodo indicado.")
        if not correo:
            raise HTTPException(status_code=422, detail="La empresa no tiene correo registrado.")
        if not settings.MAIL_SERVER or not settings.MAIL_FROM:
            raise HTTPException(status_code=503, detail="El servicio de correo no está configurado.")

        mensaje = MessageSchema(
            subject=f"Próximo vencimiento de certificado {certificado['codigo_verificacion']}",
            recipients=[correo],
            body=(
                f"El certificado {certificado['codigo_verificacion']} de {certificado['empresa']} "
                f"vence el {vencimiento}. Comuníquese con CertiSENA para iniciar su renovación."
            ),
            subtype=MessageType.plain,
        )
        await FastMail(conf).send_message(mensaje)
        return {"enviado": True}

    async def registros_exportacion(self) -> list[dict]:
        resultado = await self.db.execute(text("""
            SELECT c.codigo_verificacion, c.fecha_emision, c.fecha_vencimiento,
                   c.estado_certificado, c.publico_certificado, s.numero_radicado,
                   e.nombre AS empresa, e.nit, n.codigo AS norma_codigo,
                   a.descripcion AS alcance
            FROM certificado c
            JOIN solicitud s ON s.id_solicitud = c.id_solicitud
            JOIN empresa e ON e.id_empresa = s.id_empresa
            LEFT JOIN norma n ON n.id_norma = s.id_norma
            LEFT JOIN alcance_solicitud a ON a.id_alcance = c.id_alcance
            ORDER BY e.nombre, c.fecha_emision DESC NULLS LAST;
        """))
        return [dict(fila) for fila in resultado.mappings().all()]