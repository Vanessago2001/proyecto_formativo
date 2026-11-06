"""
Usuarios · gestion de acceso de cuentas Empresa y Auditor.

Cuando una empresa o un auditor pierde el acceso a su correo, contacta al
administrador, que puede:

  * USR-CORREO  cambiar el correo de la cuenta.
  * USR-CLAVE   restablecer la contrasena: el administrador nunca la ve ni la
                escribe. Se reutiliza el flujo de /reset-password: se genera
                un enlace de un solo uso y se envia al correo de la cuenta.

Quien puede hacerlo: el Administrador siempre; el Auxiliar solo si el
administrador le delego el permiso (modules/permisos_auxiliar); nadie mas.
Solo sobre cuentas de rol Empresa o Auditor (nunca sobre un administrador).

Cada accion exige un motivo y queda en `historial_gestion_cuenta`
(user_bootstrap.py), sin guardar nunca la contrasena ni el enlace.
"""

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.logger import logger
from core.security import _normalize_role_name
from modules.auth.mail_service import MailService
from modules.users.user_bootstrap import ensure_users_schema

PERMISO_CORREO = "USR-CORREO"
PERMISO_CLAVE = "USR-CLAVE"

ROLES_OBJETIVO = {"empresa", "auditor"}

# Fecha muy antigua para marcar la contrasena como vencida: el login ya
# obliga a cambiarla cuando vence (DIAS_EXPIRACION_POR_ROL en auth_service).
FECHA_PASSWORD_VENCIDA = "2000-01-01 00:00:00"


def _registrar_permisos_delegables() -> None:
    try:
        from modules.permisos_auxiliar.permisos_auxiliar_service import (
            registrar_permiso_delegable,
        )
    except ImportError:  # el modulo de permisos aun no esta disponible
        logger.warning("permisos_auxiliar no disponible: USR-CORREO/USR-CLAVE sin registrar.")
        return
    registrar_permiso_delegable(
        PERMISO_CORREO,
        "Cambiar correo de cuenta empresa/auditor",
        "Usuarios",
    )
    registrar_permiso_delegable(
        PERMISO_CLAVE,
        "Restablecer contraseña de cuenta empresa/auditor",
        "Usuarios",
    )


_registrar_permisos_delegables()


async def _auxiliar_tiene_permiso(db: AsyncSession, id_usuario, codigo: str) -> bool:
    try:
        from modules.permisos_auxiliar.permisos_auxiliar_service import (
            auxiliar_tiene_permiso,
        )
    except ImportError:
        return False
    return bool(await auxiliar_tiene_permiso(db, id_usuario, codigo))


def _enmascarar(correo: str | None) -> str:
    correo = correo or ""
    if "@" not in correo:
        return "***"
    usuario, dominio = correo.split("@", 1)
    return (usuario[:2] + "***@" + dominio) if usuario else "***@" + dominio


class GestionCuentaService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # permisos
    # ------------------------------------------------------------------

    async def _exigir_actor(self, actor: dict, codigo: str) -> None:
        rol = _normalize_role_name(actor.get("role_name"))
        if rol == "admin":
            return
        if rol == "auxiliar":
            id_actor = actor.get("id_usuario") or actor.get("id")
            if id_actor and await _auxiliar_tiene_permiso(self.db, id_actor, codigo):
                return
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="El administrador no le ha otorgado este permiso.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo un administrador puede gestionar el acceso de otras cuentas.",
        )

    async def _cuenta_objetivo(self, id_usuario: UUID) -> dict:
        resultado = await self.db.execute(
            text("""
                SELECT u.id_usuario, u.nombre, u.correo, r.nombre AS rol
                FROM usuario u
                LEFT JOIN rol r ON r.id_rol = u.rol_id
                WHERE u.id_usuario = :id_usuario
                LIMIT 1
            """),
            {"id_usuario": str(id_usuario)},
        )
        cuenta = resultado.mappings().first()
        if not cuenta:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="El usuario no existe.")
        if _normalize_role_name(cuenta.get("rol")) not in ROLES_OBJETIVO:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo se puede gestionar el acceso de cuentas con rol Empresa o Auditor.",
            )
        return dict(cuenta)

    # ------------------------------------------------------------------
    # historial
    # ------------------------------------------------------------------

    async def _registrar(
        self,
        actor: dict,
        id_objetivo,
        accion: str,
        motivo: str,
        valor_anterior: str | None = None,
        valor_nuevo: str | None = None,
    ):
        await ensure_users_schema(self.db)
        resultado = await self.db.execute(
            text("""
                INSERT INTO historial_gestion_cuenta (
                    id_usuario_objetivo, id_usuario_actor, rol_actor, accion,
                    valor_anterior, valor_nuevo, motivo
                )
                VALUES (
                    :id_objetivo, :id_actor, :rol_actor, :accion,
                    :valor_anterior, :valor_nuevo, :motivo
                )
                RETURNING id_historial
            """),
            {
                "id_objetivo": str(id_objetivo),
                "id_actor": str(actor.get("id_usuario") or actor.get("id") or "") or None,
                "rol_actor": actor.get("role_name"),
                "accion": accion,
                "valor_anterior": valor_anterior,
                "valor_nuevo": valor_nuevo,
                "motivo": motivo,
            },
        )
        fila = resultado.mappings().first()
        return fila.get("id_historial") if fila else None

    async def _anotar_envio(self, id_historial, resultado_envio: str) -> None:
        if not id_historial:
            return
        try:
            await self.db.execute(
                text("""
                    UPDATE historial_gestion_cuenta
                    SET resultado_envio = :resultado
                    WHERE id_historial = :id_historial
                """),
                {"resultado": resultado_envio[:500], "id_historial": str(id_historial)},
            )
            await self.db.commit()
        except Exception as exc:  # no debe romper la operacion ya confirmada
            await self.db.rollback()
            logger.error("No se pudo anotar el resultado del envio: %s", exc)

    # ------------------------------------------------------------------
    # USR-CORREO
    # ------------------------------------------------------------------

    async def cambiar_correo(self, actor: dict, id_usuario: UUID, correo_nuevo: str, motivo: str) -> dict:
        await self._exigir_actor(actor, PERMISO_CORREO)
        cuenta = await self._cuenta_objetivo(id_usuario)

        correo_nuevo = correo_nuevo.strip()
        correo_anterior = cuenta.get("correo") or ""
        if correo_nuevo.lower() == correo_anterior.strip().lower():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El correo nuevo es igual al actual.",
            )

        # El login compara LOWER(correo) = LOWER(:correo): la unicidad se
        # valida igual, sin distinguir mayusculas.
        duplicado = await self.db.execute(
            text("""
                SELECT 1 FROM usuario
                WHERE LOWER(correo) = LOWER(:correo)
                  AND id_usuario <> :id_usuario
                LIMIT 1
            """),
            {"correo": correo_nuevo, "id_usuario": str(id_usuario)},
        )
        if duplicado.first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El correo ya está en uso por otra cuenta.",
            )

        # Correos propios de las empresas vinculadas: NO se cambian; se informan.
        empresas = await self.db.execute(
            text("""
                SELECT e.id_empresa, e.nombre, e.correo
                FROM user_empresa ue
                JOIN empresa e ON e.id_empresa = ue.id_empresa
                WHERE ue.id_usuario = :id_usuario
            """),
            {"id_usuario": str(id_usuario)},
        )
        empresas_vinculadas = [
            {"id_empresa": str(f["id_empresa"]), "nombre": f["nombre"], "correo": f["correo"]}
            for f in empresas.mappings().all()
        ]

        await self.db.execute(
            text("""
                UPDATE usuario
                SET correo = :correo,
                    token_version = COALESCE(token_version, 1) + 1
                WHERE id_usuario = :id_usuario
            """),
            {"correo": correo_nuevo, "id_usuario": str(id_usuario)},
        )
        id_historial = await self._registrar(
            actor, id_usuario, "CAMBIO_CORREO", motivo,
            valor_anterior=correo_anterior, valor_nuevo=correo_nuevo,
        )
        await self.db.commit()

        # Aviso al correo ANTERIOR (y confirmacion al nuevo). Si falla, la
        # operacion ya quedo hecha: solo se registra el error.
        envios = []
        avisos = [
            (correo_anterior, "Su correo de acceso fue cambiado - CertiSENA ISO",
             "Su correo de acceso fue cambiado",
             f"El administrador de CertiSENA cambió el correo de acceso de su cuenta "
             f"a {_enmascarar(correo_nuevo)}. Si usted no lo solicitó, comuníquese de inmediato con el SENA."),
            (correo_nuevo, "Correo de acceso actualizado - CertiSENA ISO",
             "Correo de acceso actualizado",
             "Este correo quedó registrado como su correo de acceso a CertiSENA ISO."),
        ]
        for destino, asunto, titulo, mensaje in avisos:
            if not destino:
                continue
            try:
                await MailService.enviar_aviso_cuenta(destino, asunto, titulo, mensaje)
                envios.append(f"Aviso enviado a {_enmascarar(destino)}")
            except Exception as exc:
                logger.error("No se pudo enviar el aviso de cambio de correo a %s: %s", _enmascarar(destino), exc)
                envios.append(f"Falló el aviso a {_enmascarar(destino)}: {type(exc).__name__}")
        await self._anotar_envio(id_historial, "; ".join(envios))

        distintas = [e for e in empresas_vinculadas if (e["correo"] or "").lower() != correo_nuevo.lower()]
        mensaje = "Correo de la cuenta actualizado."
        if distintas:
            mensaje += (
                " El correo propio de la empresa vinculada no se cambió automáticamente; "
                "si también debe cambiar, actualícelo en el módulo Empresas."
            )
        return {
            "mensaje": mensaje,
            "id_usuario": str(id_usuario),
            "correo": correo_nuevo,
            "empresas_con_correo_propio": distintas,
            "avisos": envios,
        }

    # ------------------------------------------------------------------
    # USR-CLAVE
    # ------------------------------------------------------------------

    async def restablecer_password(self, actor: dict, id_usuario: UUID, motivo: str) -> dict:
        await self._exigir_actor(actor, PERMISO_CLAVE)
        cuenta = await self._cuenta_objetivo(id_usuario)

        # Import diferido: auth_service importa muchos modulos.
        from modules.auth.auth_service import AuthService

        enlace = await AuthService(self.db)._crear_enlace_reset(id_usuario)

        # La contrasena actual queda vencida: si la persona intenta entrar con
        # ella, el login le exige cambiarla (mismo mecanismo de expiracion).
        await self.db.execute(
            text("""
                UPDATE usuario
                SET fecha_cambio_password = CAST(:vencida AS TIMESTAMP),
                    token_version = COALESCE(token_version, 1) + 1
                WHERE id_usuario = :id_usuario
            """),
            {"vencida": FECHA_PASSWORD_VENCIDA, "id_usuario": str(id_usuario)},
        )
        id_historial = await self._registrar(
            actor, id_usuario, "RESTABLECER_PASSWORD", motivo,
            valor_nuevo="Enlace de restablecimiento enviado",
        )
        await self.db.commit()

        destino = cuenta.get("correo") or ""
        try:
            await MailService.enviar_enlace_reset(destinatario=destino, enlace=enlace)
            envio = f"Enlace enviado a {_enmascarar(destino)}"
            enviado = True
        except Exception as exc:
            logger.error("No se pudo enviar el enlace de restablecimiento a %s: %s", _enmascarar(destino), exc)
            envio = f"Falló el envío a {_enmascarar(destino)}: {type(exc).__name__}"
            enviado = False
        await self._anotar_envio(id_historial, envio)

        return {
            "mensaje": (
                f"Se envió un enlace para crear una nueva contraseña a {_enmascarar(destino)}. "
                "La contraseña anterior quedó vencida."
                if enviado
                else "La contraseña quedó vencida, pero no se pudo enviar el correo con el enlace. "
                "Intente de nuevo más tarde."
            ),
            "enviado": enviado,
            "id_usuario": str(id_usuario),
        }

    async def historial(self, actor: dict, id_usuario: UUID) -> list[dict]:
        try:
            await self._exigir_actor(actor, PERMISO_CORREO)
        except HTTPException:
            await self._exigir_actor(actor, PERMISO_CLAVE)
        await ensure_users_schema(self.db)
        resultado = await self.db.execute(
            text("""
                SELECT h.id_historial, h.accion, h.valor_anterior, h.valor_nuevo,
                       h.motivo, h.resultado_envio, h.fecha, a.nombre AS actor_nombre
                FROM historial_gestion_cuenta h
                LEFT JOIN usuario a ON a.id_usuario = h.id_usuario_actor
                WHERE h.id_usuario_objetivo = :id_usuario
                ORDER BY h.fecha DESC
            """),
            {"id_usuario": str(id_usuario)},
        )
        return [dict(f) for f in resultado.mappings().all()]
