"""
Consultas del portal público (M11).

Regla de este módulo: nada de lo que devuelven estos métodos llega a una
persona sin autenticar. Por eso las columnas de contacto de la empresa
(`correo`, `direccion`) quedan fuera de los SELECT — siguen disponibles para
los usuarios autenticados a través de `modules/empresas/`.

Reglas comunes a todos los submódulos del portal:

* El NIT se busca **completo** (nunca por coincidencia parcial). Se ignoran
  puntos, espacios y guiones, y el dígito de verificación es opcional en el
  lado que no lo tenga (ver `normalizar_nit`).
* Los códigos (radicado y código de verificación) se comparan exactos, sin
  distinguir mayúsculas y sin tener en cuenta guiones ni espacios: así el
  código copiado de un PDF se encuentra aunque el visor cambie el guion.
* Una empresa que no está 'Activa' (Inactiva o Suspendida) se muestra como tal
  y nunca como certificada, aunque tenga certificados con fecha vigente.

Las consultas leen la tabla `certificado` y la columna `solicitud.id_certificado`,
que existen en la base de datos real pero no crea ningún bootstrap de la app.
"""

import re
from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Columnas de empresa que sí se publican. `correo` y `direccion` se excluyen a
# propósito: agregarlas aquí expone datos de contacto en un endpoint sin login.
COLUMNAS_PUBLICAS_EMPRESA = "id_empresa, nombre, nit, ciudad, estado, estado AS estado_empresa"
COLUMNAS_PUBLICAS_EMPRESA_ALIAS = (
    "id_empresa, nombre AS empresa, nit, ciudad, estado AS estado_empresa"
)

# Tope de empresas por búsqueda. Con NIT exacto lo normal es una sola, pero el
# NIT sin dígito de verificación puede coincidir con varias.
MAX_EMPRESAS_POR_BUSQUEDA = 20

# Un certificado solo existe para el portal público cuando está publicado y
# firmado (PAdES) por el líder del comité. Es el mismo criterio de
# "Verificar certificado" (certificados_service.CRITERIO_PUBLICO): así un
# código que aparece en la constancia siempre se puede verificar.
CERTIFICADO_PUBLICADO_Y_FIRMADO = (
    "c.publico_certificado IS TRUE"
    " AND c.id_firmante IS NOT NULL"
    " AND c.huella_firmante IS NOT NULL"
    " AND c.codigo_hash IS NOT NULL"
    " AND c.huella_pdf IS NOT NULL"
)

# Días que faltan para el vencimiento a partir de los cuales un certificado se
# reporta "POR VENCER": es el margen típico para gestionar la renovación.
DIAS_ALERTA_VENCIMIENTO = 90

ESTADO_EMPRESA_ACTIVA = "activa"
ESTADO_CERTIFICADO_VIGENTE = "VIGENTE"
ESTADO_CERTIFICADO_PENDIENTE = "PENDIENTE_FIRMA"

MENSAJE_NIT_INVALIDO = (
    "NIT no válido. Escriba el NIT completo, solo con números (6 a 12 dígitos) "
    "y, si quiere, el dígito de verificación separado por guion. Ejemplo: 900123456-7."
)

# Tras quitar puntos y espacios: el número completo y, opcional, `-DV`.
_PATRON_NIT = re.compile(r"^\d{6,12}(-\d)?$")
# Guiones tipográficos que un visor de PDF o Word puede poner en lugar de "-".
_GUIONES = re.compile(r"[‐‑‒–—−­]")

# --- Fragmentos SQL compartidos ------------------------------------------------
# Solo dígitos del NIT guardado, con y sin el dígito de verificación (lo que va
# después del último guion).
_NIT_DIGITOS = "regexp_replace(COALESCE({col}, ''), '[^0-9]', '', 'g')"
_NIT_BASE = (
    "regexp_replace(regexp_replace(COALESCE({col}, ''), '-[^-]*$', ''), '[^0-9]', '', 'g')"
)


def condicion_nit(columna: str) -> str:
    """
    Condición SQL de NIT exacto sobre `columna`, con los parámetros
    `:nit_completo` y `:nit_base` que devuelve `normalizar_nit`.

    Coincide si:
      1. los dígitos son iguales (con o sin guion, con o sin puntos);
      2. el usuario escribió el NIT sin DV y coincide con la base guardada;
      3. el NIT guardado no tiene DV y coincide con la base escrita.
    Nunca coincide por subcadena: "1" no encuentra "900123456-7".
    """
    digitos = _NIT_DIGITOS.format(col=columna)
    base = _NIT_BASE.format(col=columna)
    return (
        f"({digitos} = :nit_completo"
        f" OR {base} = :nit_completo"
        f" OR {digitos} = :nit_base)"
    )


def condicion_codigo(columna: str, parametro: str = "codigo") -> str:
    """Igualdad de códigos ignorando mayúsculas, espacios, guiones y signos."""
    return (
        f"regexp_replace(UPPER(COALESCE({columna}, '')), '[^A-Z0-9]', '', 'g') = :{parametro}"
    )


def normalizar_nit(nit: str | None) -> dict | None:
    """
    Devuelve `{"nit_completo", "nit_base"}` o `None` si el NIT no es válido.

    `nit_completo` son todos los dígitos (incluido el DV si se escribió) y
    `nit_base` los dígitos sin el DV. Puntos, espacios y guiones tipográficos
    se ignoran: "900.123.456-7", "900123456 - 7" y "9001234567" equivalen.
    """
    limpio = _GUIONES.sub("-", nit or "")
    limpio = re.sub(r"[\s.,]", "", limpio)
    if not _PATRON_NIT.match(limpio):
        return None
    base = limpio.split("-")[0]
    return {"nit_completo": limpio.replace("-", ""), "nit_base": base}


def normalizar_codigo(codigo: str | None) -> str:
    """Código en mayúsculas y solo con letras y números ("cert 2026‐0001" → "CERT20260001")."""
    return re.sub(r"[^A-Z0-9]", "", (codigo or "").upper())


def _nit_o_422(nit: str) -> dict:
    parametros = normalizar_nit(nit)
    if parametros is None:
        raise HTTPException(
            status_code=422,
            detail=MENSAJE_NIT_INVALIDO,
        )
    return parametros


def _escapar_comodines(valor: str) -> str:
    """
    Neutraliza `%` y `_` para que se busquen como texto literal.

    Sin esto, consultar `%` hace que el `ILIKE '%' || :x || '%'` coincida con
    toda la tabla. PostgreSQL ya usa la barra invertida como carácter de
    escape por defecto en LIKE, así que no hace falta una cláusula ESCAPE.
    """
    return (valor or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def filtro_nit_publico(
    columna_nit: str,
    columna_nombre: str,
    nit: str,
    exacto: bool = False,
) -> tuple[str, dict]:
    """
    Condición de búsqueda pública por NIT y sus parámetros.

    Siempre acepta el NIT exacto (con o sin puntos, guion o dígito de
    verificación). Salvo con ``exacto=True``, también encuentra empresas cuyo
    NIT o nombre contienen el texto escrito (búsqueda parcial que decidió el
    equipo). Nunca responde 422: un texto que no es NIT solo busca coincidencias.
    """
    normalizado = (
        f"REPLACE(REPLACE(REPLACE(TRIM({columna_nit}), '.', ''), '-', ''), ' ', '')"
        " = REPLACE(REPLACE(REPLACE(TRIM(:nit), '.', ''), '-', ''), ' ', '')"
    )
    partes = [normalizado]
    params: dict = {"nit": nit}
    datos = normalizar_nit(nit)
    if datos:
        partes.append(condicion_nit(columna_nit))
        params.update(datos)
    if not exacto:
        partes.append(f"TRIM({columna_nit}) ILIKE '%' || :nit_parcial || '%'")
        partes.append(f"TRIM({columna_nombre}) ILIKE '%' || :nit_parcial || '%'")
        params["nit_parcial"] = _escapar_comodines(nit)
    return "(" + " OR ".join(partes) + ")", params


def empresa_activa(estado: str | None) -> bool:
    """Sin estado se asume 'Activa' (es el valor por defecto de la columna)."""
    return (estado or "Activa").strip().lower() == ESTADO_EMPRESA_ACTIVA


def _texto_estado_empresa(estado: str | None) -> str:
    return f"EMPRESA {(estado or 'inactiva').strip().upper()}"


def _mensaje_empresa_no_activa(estado: str | None) -> str:
    return (
        f"La empresa figura como {(estado or 'inactiva').strip().lower()} en CertiSENA: "
        "no cuenta con certificación vigente."
    )


def _a_fecha(valor):
    """
    Normaliza a `date`. Según cómo esté tipada cada columna en la base real,
    asyncpg devuelve `date` o `datetime`; mezclarlos con `date.today()` en una
    resta o comparación lanza TypeError.
    """
    return valor.date() if isinstance(valor, datetime) else valor


def _estado_vigencia(fecha_vencimiento, hoy: date) -> tuple[str, int | None]:
    """
    Traduce la fecha de vencimiento a un estado legible y a los días que faltan
    (negativos si ya venció). Sin fecha no hay plazo que calcular.
    """
    if fecha_vencimiento is None:
        return "SIN FECHA DE VENCIMIENTO", None
    dias = (fecha_vencimiento - hoy).days
    if dias < 0:
        return "VENCIDO", dias
    if dias <= DIAS_ALERTA_VENCIMIENTO:
        return "POR VENCER", dias
    return "VIGENTE", dias


def _estado_certificado(valor) -> str:
    return str(valor or "").strip().upper()


def _fila_sin_tramite(empresa: dict, estado_general: str, estado_vigencia: str, mensaje: str) -> dict:
    """Fila de `/documentos` para una empresa sin trámite que mostrar."""
    fila = {
        "id_empresa": empresa.get("id_empresa"),
        "empresa": empresa.get("empresa"),
        "nit": empresa.get("nit"),
        "ciudad": empresa.get("ciudad"),
        "estado_empresa": empresa.get("estado_empresa"),
        "empresa_activa": empresa_activa(empresa.get("estado_empresa")),
        "id_solicitud": None,
        "numero_radicado": None,
        "estado_tramite": None,
        "fecha_tramite": None,
        "alcance_certificacion": None,
        "norma_codigo": None,
        "norma_nombre": None,
        "norma_version": None,
        "norma_completa": "--",
        "codigo_verificacion": None,
        "cert_estado": None,
        "cert_emision": None,
        "cert_vence": None,
        "url_certificado": None,
        "fecha_radicacion": None,
        "vigente": False,
        "estado_general": estado_general,
        "estado_vigencia": estado_vigencia,
        "dias_restantes": None,
        "dias_desde_radicacion": None,
        "mensaje": mensaje,
    }
    return fila


class ConsultasPublicasService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def buscar_por_nit(self, nit: str, exacto: bool = False) -> list[dict]:
        if not (nit or "").strip():
            return []
        filtro, parametros = filtro_nit_publico(
            "nit", "nombre", nit.strip(), exacto=exacto
        )
        result = await self.db.execute(text(f"""
            SELECT {COLUMNAS_PUBLICAS_EMPRESA}
            FROM empresa
            WHERE {filtro}
            ORDER BY nombre ASC
            LIMIT {MAX_EMPRESAS_POR_BUSQUEDA};
        """), parametros)
        empresas = [dict(row) for row in result.mappings().all()]

        for emp in empresas:
            eid = emp.get("id_empresa")

            certs = await self.db.execute(text(f"""
                SELECT
                    c.codigo_verificacion,
                    TRIM(c.estado_certificado) AS estado,
                    c.fecha_emision,
                    c.fecha_vencimiento,
                    c.url_certificado,
                    n.codigo AS norma_codigo,
                    n.nombre AS norma_nombre,
                    n.version AS norma_version
                FROM certificado c
                JOIN solicitud s
                  ON s.id_solicitud = c.id_solicitud
                  OR s.id_certificado = c.id_certificado
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE s.id_empresa = :eid
                  AND {CERTIFICADO_PUBLICADO_Y_FIRMADO}
                  AND TRIM(UPPER(c.estado_certificado)) = 'VIGENTE'
                  AND (c.fecha_vencimiento IS NULL OR c.fecha_vencimiento >= CURRENT_DATE)
                ORDER BY c.fecha_emision DESC NULLS LAST;
            """), {"eid": eid})
            certificados = [dict(r) for r in certs.mappings().all()]

            hist = await self.db.execute(text(f"""
                SELECT
                    c.codigo_verificacion,
                    TRIM(c.estado_certificado) AS estado,
                    c.fecha_emision,
                    c.fecha_vencimiento,
                    c.url_certificado
                FROM certificado c
                JOIN solicitud s
                  ON s.id_solicitud = c.id_solicitud
                  OR s.id_certificado = c.id_certificado
                WHERE s.id_empresa = :eid
                  AND {CERTIFICADO_PUBLICADO_Y_FIRMADO}
                ORDER BY c.fecha_emision DESC NULLS LAST;
            """), {"eid": eid})
            historial_certificados = [dict(r) for r in hist.mappings().all()]
            total_certificados = len(historial_certificados)

            tot_sol = await self.db.execute(text("""
                SELECT COUNT(*) AS total FROM solicitud WHERE id_empresa = :eid;
            """), {"eid": eid})
            total_solicitudes = tot_sol.mappings().first()["total"]

            tot_sedes = await self.db.execute(text("""
                SELECT COUNT(*) AS total FROM sede_empresa WHERE id_empresa = :eid;
            """), {"eid": eid})
            total_sedes = tot_sedes.mappings().first()["total"]

            tot_docs = await self.db.execute(text("""
                SELECT COUNT(*) AS total FROM documento_empresa WHERE id_empresa = :eid;
            """), {"eid": eid})
            total_documentos = tot_docs.mappings().first()["total"]

            ult = await self.db.execute(text("""
                SELECT
                    s.numero_radicado,
                    s.estado,
                    s.fecha,
                    s.alcance_certificacion,
                    s.numero_empleados,
                    s.numero_sedes,
                    s.persona_contacto,
                    s.fecha_radicacion,
                    n.codigo AS norma_codigo,
                    n.nombre AS norma,
                    n.version AS norma_version
                FROM solicitud s
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE s.id_empresa = :eid
                ORDER BY s.fecha DESC NULLS LAST, s.fecha_creacion DESC NULLS LAST
                LIMIT 1;
            """), {"eid": eid})
            ultima = ult.mappings().first()

            sols = await self.db.execute(text("""
                SELECT
                    s.numero_radicado,
                    s.estado,
                    s.fecha,
                    s.fecha_radicacion,
                    n.nombre AS norma
                FROM solicitud s
                LEFT JOIN norma n ON n.id_norma = s.id_norma
                WHERE s.id_empresa = :eid
                ORDER BY s.fecha DESC NULLS LAST, s.fecha_creacion DESC NULLS LAST
                LIMIT 10;
            """), {"eid": eid})
            solicitudes = [dict(r) for r in sols.mappings().all()]

            activa = empresa_activa(emp.get("estado_empresa"))
            if not activa:
                # Una empresa inactiva o suspendida no ampara ningún certificado.
                certificados = []

            emp["empresa_activa"] = activa
            emp["mensaje"] = None if activa else _mensaje_empresa_no_activa(emp.get("estado_empresa"))
            emp["certificada"] = len(certificados) > 0
            emp["total_certificados"] = total_certificados
            emp["certificados_vigentes"] = len(certificados)
            emp["total_solicitudes"] = total_solicitudes
            emp["total_sedes"] = total_sedes
            emp["total_documentos"] = total_documentos
            emp["certificados"] = certificados
            emp["certificados_historial"] = historial_certificados
            emp["solicitudes"] = solicitudes
            emp["ultima_solicitud"] = dict(ultima) if ultima else None

        return empresas

    async def consulta_publica(
        self,
        codigo: str = "",
        nit: str = "",
        nit_exacto: bool = False,
    ) -> list[dict]:
        codigo = normalizar_codigo(codigo)
        nit = (nit or "").strip()
        if not codigo and not nit:
            return []

        condiciones = []
        params: dict = {}
        if codigo:
            condiciones.append(
                f"({condicion_codigo('s.numero_radicado')}"
                f" OR {condicion_codigo('c.codigo_verificacion')})"
            )
            params["codigo"] = codigo
        if nit:
            filtro, parametros_nit = filtro_nit_publico("e.nit", "e.nombre", nit, nit_exacto)
            condiciones.append(filtro)
            params.update(parametros_nit)

        where = " AND ".join(condiciones)
        result = await self.db.execute(text(f"""
            SELECT
                s.id_solicitud,
                s.numero_radicado,
                s.estado AS estado_tramite,
                s.fecha AS fecha_tramite,
                s.fecha_radicacion,
                s.alcance_certificacion,
                e.id_empresa,
                e.nombre AS empresa,
                e.nit,
                e.ciudad,
                e.estado AS estado_empresa,
                n.codigo AS norma_codigo,
                n.nombre AS norma_nombre,
                n.version AS norma_version,
                c.codigo_verificacion,
                TRIM(c.estado_certificado) AS cert_estado,
                c.fecha_emision AS cert_emision,
                c.fecha_vencimiento AS cert_vence,
                c.url_certificado
            FROM solicitud s
            JOIN empresa e ON e.id_empresa = s.id_empresa
            LEFT JOIN norma n ON n.id_norma = s.id_norma
            LEFT JOIN certificado c
              ON (c.id_solicitud = s.id_solicitud OR c.id_certificado = s.id_certificado)
             AND {CERTIFICADO_PUBLICADO_Y_FIRMADO}
            WHERE {where}
            ORDER BY s.fecha DESC NULLS LAST
            LIMIT 20;
        """), params)
        filas = [dict(r) for r in result.mappings().all()]

        hoy = date.today()
        resultados: list[dict] = []
        empresas_no_activas: set = set()
        for f in filas:
            if not empresa_activa(f.get("estado_empresa")):
                # Una sola fila por empresa inactiva, sin trámites ni códigos:
                # no debe leerse como una empresa activa normal.
                clave = f.get("id_empresa") or f.get("nit")
                if clave in empresas_no_activas:
                    continue
                empresas_no_activas.add(clave)
                resultados.append(_fila_sin_tramite(
                    f,
                    _texto_estado_empresa(f.get("estado_empresa")),
                    "SIN CERTIFICACIÓN VIGENTE",
                    _mensaje_empresa_no_activa(f.get("estado_empresa")),
                ))
                continue

            f["empresa_activa"] = True
            vence = _a_fecha(f.get("cert_vence"))
            estado_cert = _estado_certificado(f.get("cert_estado"))
            tiene_cert = bool(f.get("codigo_verificacion"))
            estado_ok = estado_cert in ("", ESTADO_CERTIFICADO_VIGENTE)
            vigente = tiene_cert and estado_ok and vence is not None and vence >= hoy
            estado_tramite = (f.get("estado_tramite") or "").strip()
            if vigente:
                estado_general = "CERTIFICADA"
                mensaje = (
                    f"Certificado vigente (código: {f.get('codigo_verificacion')}). "
                    f"Vence el {vence}."
                )
            elif tiene_cert and not estado_ok and estado_cert != ESTADO_CERTIFICADO_PENDIENTE:
                estado_general = f"CERTIFICADO {estado_cert}"
                mensaje = (
                    f"El certificado {f.get('codigo_verificacion')} está en estado "
                    f"{estado_cert.lower()}: no está vigente."
                )
            else:
                estado_general = f"EN TRAMITE - {estado_tramite}" if estado_tramite else "EN TRAMITE"
                mensaje = (
                    f"Tramite en curso (estado: {estado_tramite}). "
                    "Aun no se ha emitido certificado."
                )
            norma_partes = [f.get("norma_codigo"), f.get("norma_nombre"), f.get("norma_version")]
            f["norma_completa"] = " ".join([p for p in norma_partes if p]).strip() or "--"
            f["vigente"] = vigente
            f["estado_general"] = estado_general
            f["mensaje"] = mensaje
            if tiene_cert and not estado_ok:
                f["estado_vigencia"], f["dias_restantes"] = estado_cert.replace("_", " "), None
            elif tiene_cert:
                f["estado_vigencia"], f["dias_restantes"] = _estado_vigencia(vence, hoy)
            else:
                f["estado_vigencia"], f["dias_restantes"] = "SIN CERTIFICADO", None
            radicacion = _a_fecha(f.get("fecha_radicacion"))
            f["dias_desde_radicacion"] = (hoy - radicacion).days if radicacion else None
            resultados.append(f)

        # Solo se muestra la tarjeta de la empresa cuando se buscó únicamente
        # por NIT. Si además se escribió un radicado o código que no existe, la
        # respuesta es "no se encontró": antes salía la empresa con datos
        # incompletos ("sin norma registrada") como si el radicado fuera suyo.
        if not resultados and nit and not codigo:
            filtro_empresa, parametros_empresa = filtro_nit_publico("nit", "nombre", nit, nit_exacto)
            emp = await self.db.execute(text(f"""
                SELECT {COLUMNAS_PUBLICAS_EMPRESA_ALIAS}
                FROM empresa
                WHERE {filtro_empresa}
                ORDER BY nombre ASC
                LIMIT 5;
            """), parametros_empresa)
            for row in emp.mappings().all():
                e = dict(row)
                if empresa_activa(e.get("estado_empresa")):
                    resultados.append(_fila_sin_tramite(
                        e,
                        "REGISTRADA",
                        "SIN CERTIFICADO",
                        "Empresa registrada. Aun no tiene trámites radicados.",
                    ))
                else:
                    resultados.append(_fila_sin_tramite(
                        e,
                        _texto_estado_empresa(e.get("estado_empresa")),
                        "SIN CERTIFICACIÓN VIGENTE",
                        _mensaje_empresa_no_activa(e.get("estado_empresa")),
                    ))

        return resultados

    async def validar_autenticidad(self, codigo: str) -> dict:
        """
        Confirma que un código de verificación existe y a qué certificado
        corresponde. La coincidencia es exacta (sin distinguir mayúsculas ni
        guiones/espacios): una búsqueda parcial dejaría que cualquiera enumere
        códigos válidos probando prefijos.
        """
        codigo_limpio = normalizar_codigo(codigo)
        if not codigo_limpio:
            return {
                "autentico": False,
                "detalle": "Ingrese el código de verificación impreso en el documento.",
                "documento": None,
            }

        result = await self.db.execute(text(f"""
            SELECT
                c.codigo_verificacion,
                TRIM(c.estado_certificado) AS cert_estado,
                c.fecha_emision AS cert_emision,
                c.fecha_vencimiento AS cert_vence,
                s.numero_radicado,
                s.estado AS estado_tramite,
                s.fecha_radicacion,
                s.alcance_certificacion,
                e.nombre AS empresa,
                e.nit,
                e.ciudad,
                e.estado AS estado_empresa,
                n.codigo AS norma_codigo,
                n.nombre AS norma_nombre,
                n.version AS norma_version
            FROM certificado c
            JOIN solicitud s
              ON s.id_solicitud = c.id_solicitud
              OR s.id_certificado = c.id_certificado
            JOIN empresa e ON e.id_empresa = s.id_empresa
            LEFT JOIN norma n ON n.id_norma = s.id_norma
            WHERE {condicion_codigo("c.codigo_verificacion")}
              AND {CERTIFICADO_PUBLICADO_Y_FIRMADO}
            ORDER BY c.fecha_emision DESC NULLS LAST
            LIMIT 1;
        """), {"codigo": codigo_limpio})
        fila = result.mappings().first()

        if not fila:
            return {
                "autentico": False,
                "detalle": "Ningún certificado registrado coincide con ese código.",
                "documento": None,
            }

        hoy = date.today()
        doc = dict(fila)
        norma_partes = [doc.get("norma_codigo"), doc.get("norma_nombre"), doc.get("norma_version")]
        doc["norma_completa"] = " ".join([p for p in norma_partes if p]).strip() or "--"
        doc["estado_vigencia"], doc["dias_restantes"] = _estado_vigencia(_a_fecha(doc.get("cert_vence")), hoy)
        radicacion = _a_fecha(doc.get("fecha_radicacion"))
        doc["dias_desde_radicacion"] = (hoy - radicacion).days if radicacion else None
        doc["empresa_activa"] = empresa_activa(doc.get("estado_empresa"))

        detalle = "Código válido: corresponde a un certificado emitido por CertiSENA."
        estado_cert = _estado_certificado(doc.get("cert_estado"))
        if not doc["empresa_activa"]:
            doc["estado_vigencia"], doc["dias_restantes"] = _texto_estado_empresa(doc.get("estado_empresa")), None
            detalle += " " + _mensaje_empresa_no_activa(doc.get("estado_empresa"))
        elif estado_cert and estado_cert != ESTADO_CERTIFICADO_VIGENTE:
            doc["estado_vigencia"], doc["dias_restantes"] = estado_cert.replace("_", " "), None
            detalle += f" El certificado está en estado {estado_cert.lower().replace('_', ' ')}: no está vigente."

        return {
            "autentico": True,
            "detalle": detalle,
            "documento": doc,
        }
