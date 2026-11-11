"""
PQRS · servicio (peticiones, quejas, reclamos, sugerencias y felicitaciones).

Fuente de verdad: hoja "pqr" de documentacion/permisos.xlsx, transcrita en
`pqrs_reglas.PERMISOS_PQR` (una prueba la compara con el Excel).

CÓMO SE APLICA CADA CELDA
=========================
El rol Super administrador ya no se usa: el Administrador (ADM) tiene todo lo
que la hoja concede a SUPERADM. COM (Comité), APR (Aprendiz) y AUD (Auditor)
no tienen acceso a ninguna operación (403): las PQRS las gestionan solo el
Administrador y los auxiliares a los que él les delega el permiso. Lo que la
hoja concede a AUD queda sin efecto por decisión del equipo (06/11/2026).

"Cond." del ADMINISTRADOR (PQR-005 a 008, 011 a 013)
    Puede siempre, pero sujeto a las reglas de estado del flujo
    (pqrs_reglas.TRANSICIONES): no responde, cierra, asigna ni adjunta sobre
    una PQRS cerrada; no responde sin pasar por «En trámite», etc. Puede
    reabrir sin límite de plazo ni de veces.

"Cond." del AUXILIAR (todas sus celdas)
    La condición es que el Administrador le haya otorgado ese permiso
    concreto (modules/permisos_auxiliar: `auxiliar_tiene_permiso(session,
    id_usuario, "PQR-0xx")`). Con el permiso, el auxiliar alcanza a TODAS las
    PQRS (no solo a las que tiene asignadas) y queda sujeto a las mismas
    reglas de estado que el Administrador; sin el permiso, no puede (403).
    Los códigos se registran como delegables al importar este módulo.
    · PQR-001: registra en nombre de un ciudadano (canal presencial,
      telefónico o por correo; por defecto «Presencial»).
    · PQR-005: puede asignar a administradores y a auxiliares que tengan
      PQR-008 (Registrar respuesta). El Administrador asigna a esos mismos;
      nunca a auditores.

"Propias" de EMPRESA (PQR-003, 004, 010)
    Las radicadas por su usuario o a nombre de una empresa a la que está
    vinculado (`user_empresa` activo). Ve solo el historial visible al
    peticionario (las notas internas de asignación no se muestran).

"Propias" del PÚBLICO (sin sesión)
    Consulta con número de radicado + correo con el que radicó; ambos deben
    coincidir. Si no existe o el correo no coincide, el mismo mensaje
    genérico (sin enumeración). Las rutas públicas tienen límite de
    peticiones por IP y un campo trampa contra robots.

"Cond." de EMPRESA / PÚBLICO
    · PQR-011 Adjuntar evidencia: solo mientras la PQRS no esté cerrada. Si
      estaba en «Información solicitada», el envío (archivos y/o comentario)
      se toma como la respuesta del peticionario y vuelve a «En trámite».
    · PQR-013 Reabrir: solo una PQRS cerrada, dentro de los 15 días
      calendario siguientes al cierre y una sola vez.
    · PQR-014 (solo EMPRESA): tiempos de atención de sus propias PQRS.

"Sistema"
    PQR-002: el radicado PQRS-AAAA-000001 sale de la secuencia
    `pqrs_caso_radicado_seq` (nunca repite) y la columna es UNIQUE.
    PQR-009: al responder se envía el correo automáticamente; también al
    radicar y al solicitar información. Un fallo de correo no deshace la
    operación: queda en el log y en el historial.

FLUJO
    Radicada → Asignada → En trámite → Información solicitada → (respuesta
    del peticionario) En trámite → Respondida → Cerrada → Reabierta → En
    trámite. Desde «Información solicitada» se puede cerrar con comentario
    (desistimiento). Desde «Respondida» se puede devolver a «En trámite».
    Al reabrir se calcula un nuevo plazo desde el día de la reapertura.

PLAZOS
    Configurables por tipo en `pqrs_plazo_tipo` (por defecto 15 días hábiles
    y alerta a 3 días). Días hábiles = lunes a viernes sin festivos
    nacionales de Colombia. Mientras está en «Información solicitada» el
    semáforo muestra «en espera» (el plazo no se suspende en la fecha límite;
    ver preguntas pendientes en la entrega).
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.datetime_utils import SYSTEM_TIMEZONE, system_now, system_now_utc
from core.logger import logger
from modules.permisos_auxiliar import permisos_auxiliar_service as permisos_aux
from modules.pqrs import pqrs_notificaciones as notificaciones
from modules.pqrs import pqrs_reglas as reglas
from modules.pqrs.pqrs_reglas import (
    ASIGNADA,
    CERRADA,
    COND,
    EN_TRAMITE,
    INFO_SOLICITADA,
    PERMISOS_PQR,
    RADICADA,
    REABIERTA,
    RESPONDIDA,
    ROL_ADMIN,
    ROL_AUXILIAR,
    ROL_EMPRESA,
    ROL_PUBLICO,
    ROL_SIN_ACCESO,
    ReglaPqrsError,
)
from modules.pqrs.pqrs_repositorio import PqrsRepositorio

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent.parent
CARPETA_ADJUNTOS = RAIZ_PROYECTO / "storage" / "pqrs"

MENSAJE_NO_ENCONTRADA = "No encontramos una PQRS con ese radicado y correo."

# El auxiliar necesita que el Administrador le delegue cada código "Cond.".
CODIGOS_DELEGABLES_AUXILIAR = tuple(
    codigo for codigo, (_, valores) in PERMISOS_PQR.items()
    if valores[reglas.COLUMNAS_MATRIZ.index("AUX")] == COND
)
for _codigo in CODIGOS_DELEGABLES_AUXILIAR:
    permisos_aux.registrar_permiso_delegable(_codigo, PERMISOS_PQR[_codigo][0], "PQRS")


def _id(valor) -> str | None:
    return None if valor is None else str(valor)


def _error(error: ReglaPqrsError) -> HTTPException:
    return HTTPException(status_code=error.codigo, detail=str(error))


class PqrsService:
    def __init__(self, db: AsyncSession | None, repo=None) -> None:
        self.db = db
        self.repo = repo or PqrsRepositorio(db)
        self._permisos_cache: dict[tuple[str, str], bool] = {}

    # ------------------------------------------------------------------
    # Reloj (las pruebas lo sustituyen)
    # ------------------------------------------------------------------

    def ahora(self) -> datetime:
        return system_now_utc()

    def hoy(self) -> date:
        return self.ahora().astimezone(SYSTEM_TIMEZONE).date()

    # ------------------------------------------------------------------
    # Permisos
    # ------------------------------------------------------------------

    async def auxiliar_puede(self, id_usuario, codigo: str) -> bool:
        clave = (str(id_usuario), codigo)
        if clave not in self._permisos_cache:
            try:
                self._permisos_cache[clave] = bool(
                    await permisos_aux.auxiliar_tiene_permiso(self.db, id_usuario, codigo)
                )
            except Exception as error:
                logger.error("PQRS: no se pudo consultar el permiso %s del auxiliar: %s", codigo, error)
                self._permisos_cache[clave] = False
        return self._permisos_cache[clave]

    async def exigir(self, codigo: str, usuario: dict | None) -> str:
        """Comprueba la celda de la matriz para el rol (y la delegación del
        auxiliar). Devuelve el rol del módulo."""
        rol = reglas.rol_pqrs(usuario)
        descripcion = PERMISOS_PQR[codigo][0]
        if rol == ROL_SIN_ACCESO or not reglas.tiene_permiso(codigo, rol):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Tu rol no tiene permiso para «{descripcion}» ({codigo}).",
            )
        if rol == ROL_AUXILIAR and not await self.auxiliar_puede(usuario["id_usuario"], codigo):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"El Coordinador no te ha otorgado el permiso «{descripcion}» ({codigo}).",
            )
        return rol

    async def _anotar_uso(self, rol: str, usuario: dict | None, codigo: str, pqrs: dict) -> None:
        """Deja constancia de que un auxiliar actuó con un permiso delegado."""
        if rol != ROL_AUXILIAR:
            return
        registrar = getattr(permisos_aux, "registrar_uso", None)
        if registrar is None:
            return
        try:
            await registrar(self.db, usuario["id_usuario"], codigo, f"PQRS {pqrs.get('radicado')}")
        except Exception as error:
            logger.warning("PQRS: no se pudo anotar el uso del permiso %s: %s", codigo, error)

    async def _alcance(self, rol: str, usuario: dict) -> dict:
        if rol in (ROL_ADMIN, ROL_AUXILIAR):
            return {"tipo": "todas"}
        if rol == ROL_EMPRESA:
            return {"tipo": "empresa", "id_usuario": usuario["id_usuario"]}
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin acceso a PQRS.")

    async def _puede_ver(self, pqrs: dict, rol: str, usuario: dict) -> bool:
        if rol in (ROL_ADMIN, ROL_AUXILIAR):
            return True
        uid = str(usuario["id_usuario"])
        if rol == ROL_EMPRESA:
            if _id(pqrs.get("id_usuario_peticionario")) == uid:
                return True
            empresa = _id(pqrs.get("id_empresa"))
            return bool(empresa) and empresa in await self.repo.empresas_de_usuario(uid)
        return False

    async def _obtener_visible(self, id_pqrs, codigo: str, usuario: dict) -> tuple[dict, str]:
        rol = await self.exigir(codigo, usuario)
        pqrs = await self.repo.obtener(id_pqrs)
        # Lo que no se puede ver responde igual que lo que no existe.
        if not pqrs or not await self._puede_ver(pqrs, rol, usuario):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="PQRS no encontrada.")
        return pqrs, rol

    async def _obtener_publica(self, radicado: str, correo: str) -> dict:
        pqrs = await self.repo.obtener_por_radicado(radicado.strip().upper())
        correo_dado = (correo or "").strip().lower().encode("utf-8")
        correo_real = str((pqrs or {}).get("correo") or "").strip().lower().encode("utf-8")
        # compare_digest siempre, exista o no, para no dar pistas por el tiempo.
        coincide = hmac.compare_digest(correo_dado, correo_real)
        if not pqrs or not coincide:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=MENSAJE_NO_ENCONTRADA)
        return pqrs

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    @staticmethod
    def _actor(usuario: dict | None) -> str:
        if usuario is None:
            return "Peticionario (portal público)"
        return str(usuario.get("nombre") or usuario.get("correo") or "Usuario")

    async def _plazos(self) -> dict[str, dict]:
        try:
            filas = await self.repo.plazos()
        except Exception as error:  # la tabla de plazos nunca debe tumbar una consulta
            logger.error("PQRS: no se pudieron leer los plazos: %s", error)
            filas = []
        plazos = {f["tipo"]: f for f in filas}
        for tipo in reglas.TIPOS:
            plazos.setdefault(tipo, {
                "tipo": tipo,
                "dias_habiles": reglas.PLAZO_DIAS_HABILES_POR_DEFECTO,
                "dias_alerta": reglas.DIAS_ALERTA_POR_DEFECTO,
            })
        return plazos

    def _enriquecer(self, pqrs: dict, plazos: dict[str, dict]) -> dict:
        hoy = self.hoy()
        alerta = int(plazos.get(pqrs.get("tipo"), {}).get("dias_alerta", reglas.DIAS_ALERTA_POR_DEFECTO))
        radicada = reglas._a_fecha(pqrs.get("fecha_radicacion"))
        if isinstance(pqrs.get("fecha_radicacion"), datetime) and pqrs["fecha_radicacion"].tzinfo:
            radicada = pqrs["fecha_radicacion"].astimezone(SYSTEM_TIMEZONE).date()
        fin = reglas._a_fecha(pqrs.get("fecha_respuesta")) if pqrs.get("estado") in (RESPONDIDA, CERRADA) else hoy
        fin = fin or reglas._a_fecha(pqrs.get("fecha_cierre")) or hoy
        limite = reglas._a_fecha(pqrs.get("fecha_limite"))
        datos = dict(pqrs)
        datos["semaforo"] = reglas.semaforo(pqrs, hoy, alerta)
        datos["dias_habiles_transcurridos"] = reglas.dias_habiles_entre(radicada, fin) if radicada else 0
        datos["dias_habiles_restantes"] = (
            (reglas.dias_habiles_entre(hoy, limite) if limite >= hoy else -reglas.dias_habiles_entre(limite, hoy))
            if limite and pqrs.get("estado") in reglas.ESTADOS_ABIERTOS else None
        )
        return datos

    async def _historial(self, pqrs: dict, accion: str, usuario: dict | None, *,
                         anterior: str | None, nuevo: str | None, comentario: str | None = None,
                         visible: bool = True, es_peticionario: bool = False) -> None:
        await self.repo.registrar_historial({
            "id_pqrs": pqrs["id_pqrs"],
            "accion": accion,
            "estado_anterior": anterior,
            "estado_nuevo": nuevo,
            "comentario": comentario,
            "id_usuario": (usuario or {}).get("id_usuario"),
            "actor": self._actor(usuario),
            "visible_peticionario": visible,
            "es_peticionario": es_peticionario,
        })

    async def _cambiar(self, pqrs: dict, nuevo_estado: str | None, campos: dict) -> None:
        cambios = dict(campos)
        if nuevo_estado:
            cambios["estado"] = nuevo_estado
        if not await self.repo.actualizar(pqrs["id_pqrs"], pqrs["estado"], cambios):
            await self.repo.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La PQRS cambió mientras la editabas. Vuelve a cargarla e intenta de nuevo.",
            )

    async def _registrar_notificacion(self, pqrs: dict, enviado: bool, motivo: str) -> None:
        """PQR-009: deja en el historial si el correo salió o no."""
        try:
            await self._historial(
                pqrs, "notificar", None, anterior=None, nuevo=None,
                comentario=(f"Correo de {motivo} enviado a {pqrs.get('correo')}." if enviado
                            else f"No se pudo enviar el correo de {motivo}; revisa el registro del servidor."),
                visible=False,
            )
            await self.repo.commit()
        except Exception as error:
            logger.error("PQRS: no se pudo registrar la notificación: %s", error)
            await self.repo.rollback()

    # ------------------------------------------------------------------
    # PQR-001 / PQR-002: radicar
    # ------------------------------------------------------------------

    async def radicar(self, datos: dict, usuario: dict | None) -> dict:
        if datos.get("sitio_web"):
            # Campo trampa lleno: es un robot. Mismo mensaje que un error de datos.
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No se pudo radicar la PQRS.")

        rol = await self.exigir("PQR-001", usuario) if usuario is not None else ROL_PUBLICO
        id_empresa = datos.get("id_empresa")
        id_auditoria = datos.get("id_auditoria")
        empresa_nombre = datos.get("empresa_nombre")
        nit = datos.get("nit")

        if rol == ROL_PUBLICO:
            canal, id_empresa, id_auditoria = "Web", None, None
        elif rol == ROL_EMPRESA:
            canal = "Web"
            empresas = await self.repo.empresas_de_usuario(usuario["id_usuario"])
            if id_empresa is None and len(empresas) == 1:
                id_empresa = next(iter(empresas))
            if id_empresa is not None and str(id_empresa) not in empresas:
                raise HTTPException(status_code=403, detail="Solo puedes radicar a nombre de tus empresas.")
        else:  # administrador o auxiliar con PQR-001: atención asistida
            canal = datos.get("canal") or "Presencial"

        if id_auditoria is not None:
            vinculo = await self.repo.empresa_de_auditoria(id_auditoria)
            if not vinculo:
                raise HTTPException(status_code=422, detail="La auditoría indicada no existe.")
            if rol == ROL_EMPRESA and _id(vinculo.get("id_empresa")) not in await self.repo.empresas_de_usuario(usuario["id_usuario"]):
                raise HTTPException(status_code=403, detail="La auditoría indicada no es de tus empresas.")
            if id_empresa is None and vinculo.get("id_empresa"):
                id_empresa = vinculo["id_empresa"]

        if id_empresa is not None:
            empresa = await self.repo.empresa(id_empresa)
            if not empresa:
                raise HTTPException(status_code=422, detail="La empresa indicada no existe.")
            empresa_nombre = empresa_nombre or empresa.get("nombre")
            nit = nit or empresa.get("nit")

        plazos = await self._plazos()
        dias = int(plazos[datos["tipo"]]["dias_habiles"])
        ahora = self.ahora()
        anio = ahora.astimezone(SYSTEM_TIMEZONE).year
        radicado = reglas.generar_radicado(anio, await self.repo.siguiente_consecutivo())

        registro = {
            "radicado": radicado,
            "tipo": datos["tipo"],
            "estado": RADICADA,
            "canal": canal,
            "asunto": datos["asunto"],
            "descripcion": datos["descripcion"],
            "nombre_peticionario": datos["nombre_peticionario"],
            "tipo_documento": datos["tipo_documento"],
            "numero_documento": datos["numero_documento"],
            "correo": str(datos["correo"]).strip().lower(),
            "telefono": datos.get("telefono"),
            "empresa_nombre": empresa_nombre,
            "nit": nit,
            "id_empresa": id_empresa,
            "id_auditoria": id_auditoria,
            "acepta_tratamiento_datos": True,
            "id_usuario_peticionario": usuario["id_usuario"] if rol == ROL_EMPRESA else None,
            "id_usuario_radica": (usuario or {}).get("id_usuario"),
            "plazo_dias_habiles": dias,
            "fecha_radicacion": ahora,
            "fecha_limite": reglas.sumar_dias_habiles(self.hoy(), dias),
        }
        try:
            id_pqrs = await self.repo.insertar(registro)
            pqrs = {**registro, "id_pqrs": id_pqrs}
            comentario = f"Radicada por el canal {canal}."
            if rol in (ROL_ADMIN, ROL_AUXILIAR):
                comentario = f"Radicada en nombre del peticionario por el canal {canal}."
            await self._historial(pqrs, "radicar", usuario, anterior=None, nuevo=RADICADA,
                                  comentario=comentario, es_peticionario=rol in (ROL_PUBLICO, ROL_EMPRESA))
            await self._anotar_uso(rol, usuario, "PQR-001", pqrs)
            await self.repo.commit()
        except HTTPException:
            raise
        except Exception:
            await self.repo.rollback()
            raise

        enviado = await notificaciones.notificar_radicacion(pqrs)
        await self._registrar_notificacion(pqrs, enviado, "radicación")
        if rol == ROL_PUBLICO:
            return self._vista_publica_basica(pqrs)
        return await self.detalle(id_pqrs, usuario)

    @staticmethod
    def _vista_publica_basica(pqrs: dict) -> dict:
        return {
            "id_pqrs": _id(pqrs["id_pqrs"]),
            "radicado": pqrs["radicado"],
            "tipo": pqrs["tipo"],
            "estado": pqrs["estado"],
            "fecha_limite": pqrs["fecha_limite"],
            "mensaje": (
                f"Tu PQRS quedó radicada con el número {pqrs['radicado']}. Guárdalo: con él y tu correo "
                "puedes consultar su estado."
            ),
        }

    # ------------------------------------------------------------------
    # PQR-003 / 004 / 010: consultar, estado, historial
    # ------------------------------------------------------------------

    @staticmethod
    def _filtros(filtros: dict | None) -> dict:
        filtros = dict(filtros or {})
        try:
            if filtros.get("estado"):
                filtros["estado"] = reglas.normalizar_estado(filtros["estado"])
            if filtros.get("tipo"):
                filtros["tipo"] = reglas.normalizar_tipo(filtros["tipo"])
        except ReglaPqrsError as error:
            raise _error(error)
        if filtros.get("desde") and filtros.get("hasta") and filtros["desde"] > filtros["hasta"]:
            raise HTTPException(status_code=422, detail="La fecha inicial no puede ser posterior a la final.")
        return filtros

    async def listar(self, usuario: dict, filtros: dict | None = None, codigo: str = "PQR-003") -> list[dict]:
        rol = await self.exigir(codigo, usuario)
        filtros = self._filtros(filtros)
        alcance = await self._alcance(rol, usuario)
        filas = await self.repo.listar(alcance, filtros)
        plazos = await self._plazos()
        filas = [self._enriquecer(f, plazos) for f in filas]
        if filtros.get("semaforo"):
            filas = [f for f in filas if f["semaforo"] == filtros["semaforo"]]
        if rol == ROL_EMPRESA:
            filas = [self._vista_peticionario(f) for f in filas]
        return filas

    @staticmethod
    def _vista_peticionario(pqrs: dict) -> dict:
        """Lo que ve el peticionario: sin datos internos de gestión."""
        ocultos = {"id_responsable", "responsable", "id_usuario_radica"}
        return {k: v for k, v in pqrs.items() if k not in ocultos}

    async def detalle(self, id_pqrs, usuario: dict) -> dict:
        pqrs, rol = await self._obtener_visible(id_pqrs, "PQR-003", usuario)
        plazos = await self._plazos()
        datos = self._enriquecer(pqrs, plazos)
        peticionario = rol == ROL_EMPRESA
        if peticionario:
            datos = self._vista_peticionario(datos)
        puede_historial = True
        try:
            await self.exigir("PQR-010", usuario)
        except HTTPException:
            puede_historial = False
        datos["historial"] = (
            self._historial_para(await self.repo.historial(pqrs["id_pqrs"], solo_visibles=peticionario), peticionario)
            if puede_historial else []
        )
        datos["adjuntos"] = await self.repo.adjuntos(pqrs["id_pqrs"])
        datos["acciones"] = await self.acciones_disponibles(pqrs, rol, usuario)
        return datos

    @staticmethod
    def _historial_para(filas: list[dict], peticionario: bool) -> list[dict]:
        if not peticionario:
            return filas
        return [
            {
                "accion": f["accion"],
                "estado_anterior": f["estado_anterior"],
                "estado_nuevo": f["estado_nuevo"],
                "comentario": f["comentario"],
                "actor": "Peticionario" if f.get("es_peticionario") else "CertiSENA",
                "fecha": f["fecha"],
            }
            for f in filas
        ]

    async def estado(self, id_pqrs, usuario: dict) -> dict:
        pqrs, _ = await self._obtener_visible(id_pqrs, "PQR-004", usuario)
        datos = self._enriquecer(pqrs, await self._plazos())
        return {k: datos.get(k) for k in (
            "id_pqrs", "radicado", "tipo", "estado", "fecha_radicacion", "fecha_limite",
            "semaforo", "dias_habiles_restantes")}

    async def historial(self, id_pqrs, usuario: dict) -> list[dict]:
        pqrs, rol = await self._obtener_visible(id_pqrs, "PQR-010", usuario)
        peticionario = rol == ROL_EMPRESA
        return self._historial_para(await self.repo.historial(pqrs["id_pqrs"], solo_visibles=peticionario), peticionario)

    async def acciones_disponibles(self, pqrs: dict, rol: str, usuario: dict | None) -> list[str]:
        """Qué botones mostrar: permiso de la matriz + estado actual."""
        estado = pqrs.get("estado")
        acciones: list[str] = []

        async def permitido(codigo: str) -> bool:
            if not reglas.tiene_permiso(codigo, rol):
                return False
            if rol == ROL_AUXILIAR:
                return await self.auxiliar_puede(usuario["id_usuario"], codigo)
            return True

        if rol in (ROL_ADMIN, ROL_AUXILIAR):
            if estado != CERRADA and await permitido("PQR-005"):
                acciones.append("asignar")
            if reglas.TRANSICIONES.get(estado, frozenset()) & reglas.ESTADOS_CAMBIO_MANUAL and await permitido("PQR-006"):
                acciones.append("cambiar_estado")
            if INFO_SOLICITADA in reglas.TRANSICIONES.get(estado, frozenset()) and await permitido("PQR-007"):
                acciones.append("solicitar_informacion")
            if RESPONDIDA in reglas.TRANSICIONES.get(estado, frozenset()) and await permitido("PQR-008"):
                acciones.append("responder")
            if CERRADA in reglas.TRANSICIONES.get(estado, frozenset()) and await permitido("PQR-012"):
                acciones.append("cerrar")
            if estado == CERRADA and await permitido("PQR-013"):
                acciones.append("reabrir")
            if estado != CERRADA and await permitido("PQR-011"):
                acciones.append("adjuntar")
        elif rol in (ROL_EMPRESA, ROL_PUBLICO):
            if estado != CERRADA:
                acciones.append("adjuntar")
            try:
                reglas.validar_reapertura(pqrs, rol, self.ahora())
                acciones.append("reabrir")
            except ReglaPqrsError:
                pass
        return acciones

    # ------------------------------------------------------------------
    # PQR-005: asignar responsable
    # ------------------------------------------------------------------

    async def responsables_disponibles(self, usuario: dict) -> list[dict]:
        rol = await self.exigir("PQR-005", usuario)
        disponibles = []
        for candidato in await self.repo.usuarios_internos_activos():
            if await self._puede_ser_responsable(candidato, rol):
                disponibles.append({
                    "id_usuario": _id(candidato["id_usuario"]),
                    "nombre": candidato.get("nombre") or candidato.get("correo"),
                    "correo": candidato.get("correo"),
                    "rol": candidato.get("role_name"),
                })
        return disponibles

    async def _puede_ser_responsable(self, candidato: dict, rol_asigna: str) -> bool:
        if str(candidato.get("estado") or "").strip().lower() != "activo":
            return False
        rol_candidato = reglas.rol_pqrs(candidato)
        if rol_candidato == ROL_ADMIN:
            return True
        if rol_candidato == ROL_AUXILIAR:
            # Solo auxiliares que puedan responder (PQR-008 delegado).
            return await self.auxiliar_puede(candidato["id_usuario"], "PQR-008")
        # Auditores y demás roles no gestionan PQRS: no se les asigna.
        return False

    async def asignar(self, id_pqrs, id_responsable, comentario: str | None, usuario: dict) -> dict:
        pqrs, rol = await self._obtener_visible(id_pqrs, "PQR-005", usuario)
        if pqrs["estado"] == CERRADA:
            raise HTTPException(status_code=409, detail="No se puede asignar una PQRS cerrada.")
        candidato = await self.repo.usuario(id_responsable)
        if not candidato or not await self._puede_ser_responsable(candidato, rol):
            raise HTTPException(
                status_code=422,
                detail="El responsable debe ser un coordinador o un auxiliar activo con permiso para responder PQRS.",
            )
        if _id(pqrs.get("id_responsable")) == _id(id_responsable):
            raise HTTPException(status_code=409, detail="Esa persona ya es la responsable de la PQRS.")

        nuevo = ASIGNADA if pqrs["estado"] == RADICADA else None
        await self._cambiar(pqrs, nuevo, {"id_responsable": id_responsable})
        nombre = candidato.get("nombre") or candidato.get("correo")
        texto = f"Responsable: {nombre}." + (f" {comentario}" if comentario else "")
        accion = "reasignar" if pqrs.get("id_responsable") else "asignar"
        await self._historial(pqrs, accion, usuario, anterior=pqrs["estado"], nuevo=nuevo or pqrs["estado"],
                              comentario=texto, visible=False)
        await self._anotar_uso(rol, usuario, "PQR-005", pqrs)
        await self.repo.commit()
        return await self.detalle(id_pqrs, usuario)

    # ------------------------------------------------------------------
    # PQR-006: cambiar estado
    # ------------------------------------------------------------------

    async def cambiar_estado(self, id_pqrs, estado: str, comentario: str | None, usuario: dict) -> dict:
        pqrs, rol = await self._obtener_visible(id_pqrs, "PQR-006", usuario)
        try:
            nuevo = reglas.normalizar_estado(estado)
        except ReglaPqrsError as error:
            raise _error(error)
        if nuevo not in reglas.ESTADOS_CAMBIO_MANUAL:
            acciones = {
                ASIGNADA: "Asignar responsable", INFO_SOLICITADA: "Solicitar información",
                RESPONDIDA: "Registrar respuesta", CERRADA: "Cerrar PQRS", REABIERTA: "Reabrir PQRS",
            }
            raise HTTPException(
                status_code=422,
                detail=f"Para pasar a «{nuevo}» usa la acción «{acciones.get(nuevo, 'correspondiente')}».",
            )
        try:
            reglas.validar_transicion(pqrs["estado"], nuevo)
        except ReglaPqrsError as error:
            raise _error(error)
        await self._cambiar(pqrs, nuevo, {})
        await self._historial(pqrs, "cambiar_estado", usuario, anterior=pqrs["estado"], nuevo=nuevo,
                              comentario=comentario)
        await self._anotar_uso(rol, usuario, "PQR-006", pqrs)
        await self.repo.commit()
        return await self.detalle(id_pqrs, usuario)

    # ------------------------------------------------------------------
    # PQR-007: solicitar información
    # ------------------------------------------------------------------

    async def solicitar_informacion(self, id_pqrs, comentario: str, usuario: dict) -> dict:
        pqrs, rol = await self._obtener_visible(id_pqrs, "PQR-007", usuario)
        try:
            reglas.validar_transicion(pqrs["estado"], INFO_SOLICITADA)
        except ReglaPqrsError as error:
            raise _error(error)
        await self._cambiar(pqrs, INFO_SOLICITADA, {})
        await self._historial(pqrs, "solicitar_informacion", usuario, anterior=pqrs["estado"],
                              nuevo=INFO_SOLICITADA, comentario=comentario)
        await self._anotar_uso(rol, usuario, "PQR-007", pqrs)
        await self.repo.commit()
        enviado = await notificaciones.notificar_solicitud_informacion(pqrs, comentario)
        await self._registrar_notificacion(pqrs, enviado, "solicitud de información")
        return await self.detalle(id_pqrs, usuario)

    # ------------------------------------------------------------------
    # PQR-008 / PQR-009: responder y notificar
    # ------------------------------------------------------------------

    async def responder(self, id_pqrs, respuesta: str, usuario: dict) -> dict:
        pqrs, rol = await self._obtener_visible(id_pqrs, "PQR-008", usuario)
        try:
            reglas.validar_transicion(pqrs["estado"], RESPONDIDA)
        except ReglaPqrsError as error:
            raise _error(error)
        ahora = self.ahora()
        await self._cambiar(pqrs, RESPONDIDA, {"respuesta": respuesta, "fecha_respuesta": ahora})
        await self._historial(pqrs, "responder", usuario, anterior=pqrs["estado"], nuevo=RESPONDIDA,
                              comentario=respuesta)
        await self._anotar_uso(rol, usuario, "PQR-008", pqrs)
        await self.repo.commit()
        enviado = await notificaciones.notificar_respuesta({**pqrs, "respuesta": respuesta})
        await self._registrar_notificacion(pqrs, enviado, "respuesta")
        return await self.detalle(id_pqrs, usuario)

    # ------------------------------------------------------------------
    # PQR-012: cerrar
    # ------------------------------------------------------------------

    async def cerrar(self, id_pqrs, comentario: str | None, usuario: dict) -> dict:
        pqrs, rol = await self._obtener_visible(id_pqrs, "PQR-012", usuario)
        try:
            reglas.validar_transicion(pqrs["estado"], CERRADA)
        except ReglaPqrsError as error:
            raise _error(error)
        if pqrs["estado"] == INFO_SOLICITADA and not (comentario and len(comentario.strip()) >= 10):
            raise HTTPException(
                status_code=422,
                detail="Para cerrar sin respuesta (desistimiento) explica el motivo en el comentario.",
            )
        await self._cambiar(pqrs, CERRADA, {"fecha_cierre": self.ahora()})
        await self._historial(pqrs, "cerrar", usuario, anterior=pqrs["estado"], nuevo=CERRADA,
                              comentario=comentario)
        await self._anotar_uso(rol, usuario, "PQR-012", pqrs)
        await self.repo.commit()
        return await self.detalle(id_pqrs, usuario)

    # ------------------------------------------------------------------
    # PQR-013: reabrir
    # ------------------------------------------------------------------

    async def _reabrir(self, pqrs: dict, rol: str, motivo: str, usuario: dict | None) -> None:
        try:
            reglas.validar_reapertura(pqrs, rol, self.ahora())
        except ReglaPqrsError as error:
            raise _error(error)
        dias = int(pqrs.get("plazo_dias_habiles") or reglas.PLAZO_DIAS_HABILES_POR_DEFECTO)
        await self._cambiar(pqrs, REABIERTA, {
            "veces_reabierta": int(pqrs.get("veces_reabierta") or 0) + 1,
            "fecha_cierre": None,
            "fecha_respuesta": None,
            "fecha_limite": reglas.sumar_dias_habiles(self.hoy(), dias),
        })
        await self._historial(pqrs, "reabrir", usuario, anterior=CERRADA, nuevo=REABIERTA, comentario=motivo,
                              es_peticionario=rol in (ROL_EMPRESA, ROL_PUBLICO))
        await self._anotar_uso(rol, usuario, "PQR-013", pqrs)
        await self.repo.commit()

    async def reabrir(self, id_pqrs, motivo: str, usuario: dict) -> dict:
        pqrs, rol = await self._obtener_visible(id_pqrs, "PQR-013", usuario)
        await self._reabrir(pqrs, rol, motivo, usuario)
        return await self.detalle(id_pqrs, usuario)

    async def reabrir_publica(self, radicado: str, correo: str, motivo: str) -> dict:
        pqrs = await self._obtener_publica(radicado, correo)
        await self._reabrir(pqrs, ROL_PUBLICO, motivo, None)
        return await self.consultar_publica(radicado, correo)

    # ------------------------------------------------------------------
    # PQR-011: adjuntar evidencia
    # ------------------------------------------------------------------

    async def _leer_archivos(self, archivos: list[UploadFile]) -> list[tuple[str, str, str, bytes]]:
        if len(archivos) > reglas.MAX_ADJUNTOS_POR_ENVIO:
            raise HTTPException(status_code=422, detail=f"Máximo {reglas.MAX_ADJUNTOS_POR_ENVIO} archivos por envío.")
        leidos = []
        for archivo in archivos:
            # Se lee un byte más del límite para detectar archivos grandes sin cargarlos enteros.
            contenido = await archivo.read(reglas.TAMANO_MAXIMO_ADJUNTO + 1)
            try:
                nombre, extension, mime = reglas.validar_adjunto(archivo.filename, contenido)
            except ReglaPqrsError as error:
                raise _error(error)
            leidos.append((nombre, extension, mime, contenido))
        return leidos

    async def _adjuntar(self, pqrs: dict, rol: str, archivos: list[UploadFile], comentario: str | None,
                        usuario: dict | None) -> dict:
        if pqrs["estado"] == CERRADA:
            raise HTTPException(status_code=409, detail="La PQRS está cerrada y ya no admite adjuntos.")
        peticionario = rol in (ROL_EMPRESA, ROL_PUBLICO)
        comentario = (comentario or "").strip() or None
        leidos = await self._leer_archivos(archivos)
        if not leidos and not (peticionario and comentario):
            raise HTTPException(status_code=400, detail="No se recibió ningún archivo.")

        carpeta = CARPETA_ADJUNTOS / str(pqrs["id_pqrs"])
        escritos: list[Path] = []
        guardados = []
        try:
            for nombre, extension, mime, contenido in leidos:
                carpeta.mkdir(parents=True, exist_ok=True)
                destino = carpeta / f"{uuid4()}{extension}"
                destino.write_bytes(contenido)
                escritos.append(destino)
                guardados.append(await self.repo.insertar_adjunto({
                    "id_pqrs": pqrs["id_pqrs"],
                    "nombre_archivo": nombre,
                    "ruta_archivo": str(destino.relative_to(RAIZ_PROYECTO)).replace("\\", "/"),
                    "tipo_mime": mime,
                    "tamano_bytes": len(contenido),
                    "hash_sha256": hashlib.sha256(contenido).hexdigest(),
                    "origen": "peticionario" if peticionario else "gestion",
                    "id_usuario": (usuario or {}).get("id_usuario"),
                }))

            nuevo = EN_TRAMITE if peticionario and pqrs["estado"] == INFO_SOLICITADA else None
            if nuevo:
                await self._cambiar(pqrs, nuevo, {})
            nombres = ", ".join(n for n, *_ in leidos)
            texto = " · ".join(t for t in (comentario, f"Adjuntos: {nombres}" if nombres else None) if t)
            await self._historial(
                pqrs, "aportar_informacion" if nuevo else "adjuntar", usuario,
                anterior=pqrs["estado"] if nuevo else None, nuevo=nuevo, comentario=texto,
                es_peticionario=peticionario,
            )
            await self._anotar_uso(rol, usuario, "PQR-011", pqrs)
            await self.repo.commit()
        except BaseException:
            for archivo in escritos:
                archivo.unlink(missing_ok=True)
            await self.repo.rollback()
            raise
        return {"agregados": len(guardados), "adjuntos": guardados, "estado": nuevo or pqrs["estado"]}

    async def adjuntar(self, id_pqrs, archivos: list[UploadFile], comentario: str | None, usuario: dict) -> dict:
        pqrs, rol = await self._obtener_visible(id_pqrs, "PQR-011", usuario)
        return await self._adjuntar(pqrs, rol, archivos, comentario, usuario)

    async def adjuntar_publica(self, radicado: str, correo: str, archivos: list[UploadFile],
                               comentario: str | None) -> dict:
        pqrs = await self._obtener_publica(radicado, correo)
        return await self._adjuntar(pqrs, ROL_PUBLICO, archivos, comentario, None)

    def _ruta_segura(self, adjunto: dict) -> Path:
        ruta = (RAIZ_PROYECTO / adjunto["ruta_archivo"]).resolve()
        if CARPETA_ADJUNTOS.resolve() not in ruta.parents or not ruta.is_file():
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")
        return ruta

    async def archivo_adjunto(self, id_pqrs, id_adjunto, usuario: dict) -> tuple[Path, str, str]:
        pqrs, _ = await self._obtener_visible(id_pqrs, "PQR-003", usuario)
        adjunto = await self.repo.adjunto(pqrs["id_pqrs"], id_adjunto)
        if not adjunto:
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")
        return self._ruta_segura(adjunto), adjunto["nombre_archivo"], adjunto["tipo_mime"]

    async def archivo_adjunto_publico(self, radicado: str, correo: str, id_adjunto) -> tuple[Path, str, str]:
        pqrs = await self._obtener_publica(radicado, correo)
        adjunto = await self.repo.adjunto(pqrs["id_pqrs"], id_adjunto)
        if not adjunto:
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")
        return self._ruta_segura(adjunto), adjunto["nombre_archivo"], adjunto["tipo_mime"]

    # ------------------------------------------------------------------
    # Consulta pública (PUB "Propias")
    # ------------------------------------------------------------------

    async def consultar_publica(self, radicado: str, correo: str) -> dict:
        pqrs = await self._obtener_publica(radicado, correo)
        datos = self._enriquecer(pqrs, await self._plazos())
        historial = self._historial_para(await self.repo.historial(pqrs["id_pqrs"], solo_visibles=True), True)
        solicitud = None
        if pqrs["estado"] == INFO_SOLICITADA:
            pedidos = [h for h in historial if h["accion"] == "solicitar_informacion"]
            solicitud = pedidos[-1]["comentario"] if pedidos else None
        campos = ("radicado", "tipo", "estado", "canal", "asunto", "descripcion", "nombre_peticionario",
                  "fecha_radicacion", "fecha_limite", "fecha_respuesta", "fecha_cierre", "semaforo",
                  "dias_habiles_restantes")
        vista = {k: datos.get(k) for k in campos}
        vista["respuesta"] = pqrs.get("respuesta") if pqrs["estado"] in (RESPONDIDA, CERRADA) else None
        vista["informacion_solicitada"] = solicitud
        vista["historial"] = historial
        vista["adjuntos"] = [
            {k: a.get(k) for k in ("id_adjunto", "nombre_archivo", "tamano_bytes", "origen", "fecha_subida")}
            for a in await self.repo.adjuntos(pqrs["id_pqrs"])
        ]
        vista["acciones"] = await self.acciones_disponibles(pqrs, ROL_PUBLICO, None)
        return vista

    # ------------------------------------------------------------------
    # PQR-014: tiempos de atención
    # ------------------------------------------------------------------

    async def tiempos(self, usuario: dict, filtros: dict | None = None) -> dict:
        filas = await self.listar(usuario, filtros, codigo="PQR-014")
        conteo = {clave: 0 for clave in reglas_semaforos()}
        for fila in filas:
            conteo[fila["semaforo"]] = conteo.get(fila["semaforo"], 0) + 1
        respondidas = [f for f in filas if f.get("estado") in (RESPONDIDA, CERRADA) and f.get("fecha_respuesta")]
        promedio = (
            round(sum(f["dias_habiles_transcurridos"] for f in respondidas) / len(respondidas), 1)
            if respondidas else None
        )
        por_tipo = {}
        for fila in filas:
            grupo = por_tipo.setdefault(fila["tipo"], {"tipo": fila["tipo"], "total": 0, "abiertas": 0, "vencidas": 0})
            grupo["total"] += 1
            grupo["abiertas"] += fila["estado"] in reglas.ESTADOS_ABIERTOS
            grupo["vencidas"] += fila["semaforo"] == "vencida"
        abiertas = sorted(
            (f for f in filas if f["estado"] in reglas.ESTADOS_ABIERTOS),
            key=lambda f: (str(f.get("fecha_limite") or ""), f["radicado"]),
        )
        campos = ("id_pqrs", "radicado", "tipo", "estado", "asunto", "fecha_radicacion", "fecha_limite",
                  "semaforo", "dias_habiles_transcurridos", "dias_habiles_restantes", "responsable")
        return {
            "resumen": {
                "total": len(filas),
                "abiertas": sum(f["estado"] in reglas.ESTADOS_ABIERTOS for f in filas),
                **conteo,
                "promedio_dias_habiles_respuesta": promedio,
            },
            "por_tipo": sorted(por_tipo.values(), key=lambda g: g["tipo"]),
            "abiertas": [{k: f.get(k) for k in campos if k in f} for f in abiertas],
        }

    # ------------------------------------------------------------------
    # PQR-015: reporte
    # ------------------------------------------------------------------

    async def reporte(self, usuario: dict, filtros: dict | None = None) -> list[dict]:
        return await self.listar(usuario, filtros, codigo="PQR-015")

    # ------------------------------------------------------------------
    # Catálogos y plazos
    # ------------------------------------------------------------------

    async def catalogos(self) -> dict:
        plazos = await self._plazos()
        return {
            "tipos": list(reglas.TIPOS),
            "estados": list(reglas.ESTADOS),
            "canales": list(reglas.CANALES),
            "tipos_documento": list(reglas.TIPOS_DOCUMENTO),
            "plazos": [plazos[t] for t in reglas.TIPOS],
            "adjuntos": {
                "extensiones": sorted(reglas.EXTENSIONES_ADJUNTO),
                "tamano_maximo_mb": reglas.TAMANO_MAXIMO_ADJUNTO // (1024 * 1024),
                "maximo_por_envio": reglas.MAX_ADJUNTOS_POR_ENVIO,
            },
            "dias_para_reabrir": reglas.DIAS_PARA_REABRIR,
        }

    async def actualizar_plazo(self, tipo: str, dias: int, alerta: int, usuario: dict) -> dict:
        if reglas.rol_pqrs(usuario) != ROL_ADMIN:
            raise HTTPException(status_code=403, detail="Solo el Coordinador configura los plazos de PQRS.")
        try:
            tipo = reglas.normalizar_tipo(tipo)
        except ReglaPqrsError as error:
            raise _error(error)
        if alerta >= dias:
            raise HTTPException(status_code=422, detail="Los días de alerta deben ser menores que el plazo.")
        fila = await self.repo.actualizar_plazo(tipo, dias, alerta, usuario.get("id_usuario"))
        await self.repo.commit()
        return fila

    async def permisos_de_sesion(self, usuario: dict) -> dict:
        """Qué vistas/acciones de gestión puede usar la sesión (para la UI)."""
        rol = reglas.rol_pqrs(usuario)
        resultado = {}
        for codigo in PERMISOS_PQR:
            if not reglas.tiene_permiso(codigo, rol):
                resultado[codigo] = False
            elif rol == ROL_AUXILIAR and codigo in CODIGOS_DELEGABLES_AUXILIAR:
                resultado[codigo] = await self.auxiliar_puede(usuario["id_usuario"], codigo)
            else:
                resultado[codigo] = True
        return {"rol": rol, "permisos": resultado, "formatos_reporte": None}


def reglas_semaforos() -> tuple[str, ...]:
    return ("vencida", "proxima", "en_termino", "en_espera", "atendida_a_tiempo", "atendida_tarde")
