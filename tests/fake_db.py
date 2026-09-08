"""
Doble de base de datos en memoria para los tests del módulo M5.

Reproduce lo justo del comportamiento de PostgreSQL que usan las consultas de
`SolicitudService` sobre las tablas reales `solicitud`, `historial_estado` y
`user_empresa`: RETURNING, borrado lógico con deleted_at, filtros del listado
y la secuencia del radicado.
"""

import re
import uuid
from datetime import date, datetime, timezone


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


class ResultadoFalso:
    """Imita el objeto Result de SQLAlchemy en lo que consume el servicio."""

    def __init__(self, filas: list[dict] | None = None, escalar=None):
        self._filas = filas or []
        self._escalar = escalar

    def mappings(self):
        return self

    def first(self):
        return self._filas[0] if self._filas else None

    def one(self):
        if not self._filas:
            raise AssertionError("Se esperaba una fila y no hubo ninguna.")
        return self._filas[0]

    def all(self):
        return list(self._filas)

    def scalar(self):
        return self._escalar


class SesionFalsa:
    """AsyncSession simulada con las tablas que toca el Bloque 1."""

    def __init__(self):
        self.solicitudes: dict[str, dict] = {}
        self.historial: list[dict] = []
        self.vinculos: list[dict] = []          # user_empresa
        self.commits = 0
        self._consecutivo = 0

    # -- utilidades del test -------------------------------------------------

    def vincular(self, id_usuario, id_empresa, estado: str = "Activo") -> None:
        """Asocia un usuario a una empresa (tabla user_empresa)."""
        self.vinculos.append(
            {
                "id_usuario": str(id_usuario),
                "id_empresa": str(id_empresa),
                "estado": estado,
            }
        )

    def sembrar(self, **campos) -> dict:
        """Inserta una solicitud directamente, sin pasar por el servicio."""
        fila = {
            "id_solicitud": uuid.uuid4(),
            "numero_radicado": None,
            "estado": "Borrador",
            "id_empresa": uuid.uuid4(),
            "id_norma": uuid.uuid4(),
            "alcance_certificacion": "Alcance de prueba",
            "numero_empleados": 10,
            "numero_sedes": 1,
            "persona_contacto": "Contacto de prueba",
            "observaciones": None,
            "motivo_cancelacion": None,
            "ciclo_renovacion": 1,
            "usuario_creador": uuid.uuid4(),
            "fecha": date.today(),
            "fecha_creacion": _ahora(),
            "fecha_radicacion": None,
            "fecha_cancelacion": None,
            "deleted_at": None,
            "deleted_by": None,
        }
        fila.update(campos)
        self.solicitudes[str(fila["id_solicitud"])] = fila
        return fila

    # -- interfaz que consume el servicio ------------------------------------

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass

    async def close(self):
        pass

    async def execute(self, sentencia, parametros=None):
        sql = " ".join(str(sentencia).split())
        parametros = parametros or {}

        if "nextval" in sql:
            self._consecutivo += 1
            return ResultadoFalso(escalar=self._consecutivo)

        if "FROM user_empresa" in sql:
            filas = [
                {"id_empresa": v["id_empresa"]}
                for v in self.vinculos
                if v["id_usuario"] == str(parametros["id_usuario"])
                and v["estado"] == "Activo"
            ]
            return ResultadoFalso(filas)

        if "INSERT INTO historial_estado" in sql:
            self.historial.append(dict(parametros))
            return ResultadoFalso()

        if "INSERT INTO solicitud" in sql:
            return self._insertar(sql, parametros)

        if "UPDATE solicitud" in sql:
            return self._actualizar(sql, parametros)

        if "FROM solicitud" in sql:
            return self._seleccionar(sql, parametros)

        raise AssertionError(f"Consulta no contemplada por el doble: {sql[:120]}")

    # -- implementación ------------------------------------------------------

    def _insertar(self, sql: str, parametros: dict) -> ResultadoFalso:
        if "SELECT" in sql:
            # SOL-008: duplicar copia los datos técnicos del original.
            original = self.solicitudes[str(parametros["id_solicitud"])]
            fila = self.sembrar(
                estado=parametros["estado"],
                id_empresa=original["id_empresa"],
                id_norma=original["id_norma"],
                alcance_certificacion=original["alcance_certificacion"],
                numero_empleados=original["numero_empleados"],
                numero_sedes=original["numero_sedes"],
                persona_contacto=original["persona_contacto"],
                observaciones=original["observaciones"],
                usuario_creador=uuid.UUID(parametros["usuario_creador"]),
            )
            return ResultadoFalso([fila])

        fila = self.sembrar(
            estado=parametros["estado"],
            id_empresa=uuid.UUID(parametros["id_empresa"]),
            id_norma=(
                uuid.UUID(parametros["id_norma"]) if parametros["id_norma"] else None
            ),
            alcance_certificacion=parametros["alcance_certificacion"],
            numero_empleados=parametros["numero_empleados"],
            numero_sedes=parametros["numero_sedes"],
            persona_contacto=parametros["persona_contacto"],
            observaciones=parametros["observaciones"],
            usuario_creador=uuid.UUID(parametros["usuario_creador"]),
        )
        return ResultadoFalso([fila])

    def _actualizar(self, sql: str, parametros: dict) -> ResultadoFalso:
        fila = self.solicitudes[str(parametros["id_solicitud"])]

        # Se leen las columnas realmente asignadas en el SET para traducir los
        # nombres de parámetro (por ejemplo :motivo -> motivo_cancelacion).
        cuerpo_set = sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
        for columna, valor in re.findall(r"(\w+)\s*=\s*([:\w()]+)", cuerpo_set):
            if valor.startswith(":"):
                fila[columna] = parametros[valor[1:]]
            elif valor.upper() in ("NOW()", "CURRENT_TIMESTAMP"):
                fila[columna] = _ahora()
            elif valor.upper() == "CURRENT_DATE":
                fila[columna] = date.today()

        return ResultadoFalso([fila])

    def _seleccionar(self, sql: str, parametros: dict) -> ResultadoFalso:
        filas = [f for f in self.solicitudes.values() if f["deleted_at"] is None]

        if "id_solicitud = :id_solicitud" in sql:
            filas = [
                f
                for f in filas
                if str(f["id_solicitud"]) == str(parametros["id_solicitud"])
            ]
            return ResultadoFalso(filas)

        if "id_empresa = ANY(:empresas)" in sql:
            permitidas = {str(e) for e in parametros["empresas"]}
            filas = [f for f in filas if str(f["id_empresa"]) in permitidas]

        if "estado = :estado" in sql:
            filas = [f for f in filas if f["estado"] == parametros["estado"]]

        filas.sort(key=lambda f: f["fecha_creacion"], reverse=True)

        inicio = parametros.get("desplazamiento", 0)
        return ResultadoFalso(filas[inicio : inicio + parametros.get("limite", 50)])
