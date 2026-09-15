"""
Doble de base de datos en memoria para los tests del módulo M5.

Reproduce lo justo del comportamiento de PostgreSQL que usan las consultas de
M5 sobre las tablas reales:

  · Bloque 1: `solicitud`, `historial_estado` y `user_empresa` (RETURNING,
    borrado lógico con deleted_at, filtros del listado y la secuencia del
    radicado).
  · Bloque 2: `norma`, `alcance_solicitud` y `proceso_solicitud`.
  · Bloque 3: `sede_empresa` y `solicitud_sede`.
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
    """AsyncSession simulada con las tablas que tocan los bloques 1 a 3."""

    def __init__(self):
        self.solicitudes: dict[str, dict] = {}
        self.historial: list[dict] = []
        self.vinculos: list[dict] = []          # user_empresa
        self.normas: dict[str, dict] = {}
        self.alcances: dict[str, dict] = {}     # alcance_solicitud
        self.procesos: dict[str, dict] = {}     # proceso_solicitud
        self.sedes_empresa: dict[str, dict] = {}
        self.solicitud_sedes: dict[str, dict] = {}
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

    def sembrar_norma(self, **campos) -> dict:
        fila = {
            "id_norma": uuid.uuid4(),
            "codigo": "ISO-9001",
            "nombre": "Sistemas de gestion de la calidad",
            "version": "2015",
        }
        fila.update(campos)
        self.normas[str(fila["id_norma"])] = fila
        return fila

    def sembrar_sede(self, **campos) -> dict:
        """Inserta una sede de empresa (tabla sede_empresa)."""
        fila = {
            "id_sede": uuid.uuid4(),
            "id_empresa": uuid.uuid4(),
            "nombre_sede": "Sede de prueba",
            "direccion": "Calle 1 # 2-3",
            "ciudad": "Manizales",
            "departamento": "Caldas",
            "pais": "Colombia",
            "es_principal": False,
            "estado": "Activa",
            "fecha_registro": _ahora(),
        }
        fila.update(campos)
        self.sedes_empresa[str(fila["id_sede"])] = fila
        return fila

    def incluir_sede(self, id_solicitud, id_sede, estado: str = "Incluida") -> dict:
        """Vincula una sede a una solicitud (tabla solicitud_sede)."""
        fila = {
            "id_solicitud_sede": uuid.uuid4(),
            "id_solicitud": uuid.UUID(str(id_solicitud)),
            "id_sede": uuid.UUID(str(id_sede)),
            "estado": estado,
            "fecha_registro": _ahora(),
        }
        self.solicitud_sedes[str(fila["id_solicitud_sede"])] = fila
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

        # Las tablas de los bloques 2 y 3 se atienden primero: sus nombres
        # contienen "solicitud" y el despacho del Bloque 1 las capturaría.
        if "solicitud_sede" in sql:
            return self._solicitud_sede(sql, parametros)

        if "sede_empresa" in sql:
            return self._sede_empresa(sql, parametros)

        if "alcance_solicitud" in sql:
            return self._detalle(self.alcances, "id_alcance", sql, parametros)

        if "proceso_solicitud" in sql:
            return self._detalle(self.procesos, "id_proceso", sql, parametros)

        if "FROM norma WHERE id_norma" in sql:
            fila = self.normas.get(str(parametros["id_norma"]))
            return ResultadoFalso([fila] if fila else [])

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

    # -- implementación: Bloque 1 --------------------------------------------

    @staticmethod
    def _aplicar_set(fila: dict, sql: str, parametros: dict) -> None:
        """
        Aplica el SET de un UPDATE sobre la fila.

        Se leen las columnas realmente asignadas para traducir los nombres de
        parámetro (por ejemplo :motivo -> motivo_cancelacion).
        """
        cuerpo_set = sql.split(" SET ", 1)[1].split(" WHERE ", 1)[0]
        for columna, valor in re.findall(r"(\w+)\s*=\s*([:\w()]+)", cuerpo_set):
            if valor.startswith(":"):
                fila[columna] = parametros[valor[1:]]
            elif valor.upper() in ("NOW()", "CURRENT_TIMESTAMP"):
                fila[columna] = _ahora()
            elif valor.upper() == "CURRENT_DATE":
                fila[columna] = date.today()

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
        self._aplicar_set(fila, sql, parametros)
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

    # -- implementación: Bloque 2 --------------------------------------------

    def _detalle(
        self,
        tabla: dict,
        clave: str,
        sql: str,
        parametros: dict,
    ) -> ResultadoFalso:
        """alcance_solicitud y proceso_solicitud: misma forma, distinta clave."""
        if sql.startswith("INSERT"):
            fila = {
                clave: uuid.uuid4(),
                "id_solicitud": uuid.UUID(str(parametros["id_solicitud"])),
                "descripcion": parametros.get("descripcion"),
                "estado": parametros.get("estado", "Activo"),
                "fecha_registro": _ahora(),
            }
            if "nombre" in parametros:
                fila["nombre"] = parametros["nombre"]
            tabla[str(fila[clave])] = fila
            return ResultadoFalso([fila])

        if sql.startswith("UPDATE"):
            fila = tabla[str(parametros[clave])]
            self._aplicar_set(fila, sql, parametros)
            return ResultadoFalso([fila])

        filas = [
            f
            for f in tabla.values()
            if str(f["id_solicitud"]) == str(parametros["id_solicitud"])
        ]
        if f"{clave} = :{clave}" in sql:
            filas = [f for f in filas if str(f[clave]) == str(parametros[clave])]
        if f"{clave} <> :{clave}" in sql:
            filas = [f for f in filas if str(f[clave]) != str(parametros[clave])]
        if "LOWER(nombre)" in sql:
            filas = [
                f
                for f in filas
                if f["nombre"].lower() == parametros["nombre"].lower()
                and f["estado"] == parametros["activo"]
            ]

        filas.sort(key=lambda f: f["fecha_registro"])
        return ResultadoFalso(filas, escalar=filas[0][clave] if filas else None)

    # -- implementación: Bloque 3 --------------------------------------------

    def _sede_empresa(self, sql: str, parametros: dict) -> ResultadoFalso:
        if sql.startswith("INSERT"):
            fila = self.sembrar_sede(
                id_empresa=uuid.UUID(str(parametros["id_empresa"])),
                nombre_sede=parametros["nombre_sede"],
                direccion=parametros["direccion"],
                ciudad=parametros["ciudad"],
                departamento=parametros["departamento"],
                pais=parametros["pais"],
                es_principal=parametros["es_principal"],
            )
            return ResultadoFalso([fila])

        fila = self.sedes_empresa.get(str(parametros["id_sede"]))
        if fila and sql.startswith("UPDATE"):
            self._aplicar_set(fila, sql, parametros)

        return ResultadoFalso([fila] if fila else [])

    def _solicitud_sede(self, sql: str, parametros: dict) -> ResultadoFalso:
        if sql.startswith("INSERT"):
            fila = self.incluir_sede(
                parametros["id_solicitud"], parametros["id_sede"], parametros["estado"]
            )
            return ResultadoFalso([fila])

        if sql.startswith("UPDATE"):
            fila = self.solicitud_sedes[str(parametros["id_solicitud_sede"])]
            self._aplicar_set(fila, sql, parametros)
            return ResultadoFalso([fila])

        vinculos = list(self.solicitud_sedes.values())

        if "NOT EXISTS" in sql:
            # Sedes activas de la empresa que aún no están en la solicitud.
            ocupadas = {
                str(v["id_sede"])
                for v in vinculos
                if str(v["id_solicitud"]) == str(parametros["id_solicitud"])
                and v["estado"] != parametros["excluida"]
            }
            filas = [
                s
                for s in self.sedes_empresa.values()
                if str(s["id_empresa"]) == str(parametros["id_empresa"])
                and s["estado"] == parametros["activa"]
                and str(s["id_sede"]) not in ocupadas
            ]
            filas.sort(key=lambda s: (not s["es_principal"], s["nombre_sede"]))
            return ResultadoFalso(filas)

        if "JOIN solicitud s" in sql:
            # ¿La sede está en otra solicitud ya presentada?
            cuenta = 0
            for v in vinculos:
                otra = self.solicitudes.get(str(v["id_solicitud"]))
                if (
                    str(v["id_sede"]) == str(parametros["id_sede"])
                    and str(v["id_solicitud"]) != str(parametros["id_solicitud"])
                    and v["estado"] != parametros["excluida"]
                    and otra is not None
                    and otra["deleted_at"] is None
                    and otra["estado"] not in (parametros["borrador"], parametros["cancelada"])
                ):
                    cuenta += 1
            return ResultadoFalso(escalar=cuenta)

        vinculos = [
            v for v in vinculos if str(v["id_solicitud"]) == str(parametros["id_solicitud"])
        ]
        if "id_sede = :id_sede" in sql:
            vinculos = [v for v in vinculos if str(v["id_sede"]) == str(parametros["id_sede"])]
        if "estado <> :excluida" in sql:
            vinculos = [v for v in vinculos if v["estado"] != parametros["excluida"]]

        if "COUNT(*)" in sql:
            return ResultadoFalso(escalar=len(vinculos))

        if "JOIN sede_empresa" in sql:
            filas = []
            for v in vinculos:
                sede = self.sedes_empresa[str(v["id_sede"])]
                filas.append(
                    {
                        "id_solicitud_sede": v["id_solicitud_sede"],
                        "id_solicitud": v["id_solicitud"],
                        "estado_en_solicitud": v["estado"],
                        "fecha_inclusion": v["fecha_registro"],
                        "estado_sede": sede["estado"],
                        **{
                            campo: sede[campo]
                            for campo in (
                                "id_sede", "nombre_sede", "direccion", "ciudad",
                                "departamento", "pais", "es_principal",
                            )
                        },
                    }
                )
            filas.sort(key=lambda f: (not f["es_principal"], f["nombre_sede"]))
            return ResultadoFalso(filas)

        return ResultadoFalso([dict(v) for v in vinculos])
