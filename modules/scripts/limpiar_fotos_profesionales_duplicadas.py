"""Limpia las fotos profesionales duplicadas que dejo un error anterior.

Hasta la correccion de `AuditorService.adjuntar_documento`, al reponer una foto
profesional rechazada se insertaba una fila nueva en lugar de sustituir la
rechazada. Algunas postulaciones quedaron con dos filas del tipo
`Foto Profesional` (y con dos archivos en disco), y el administrador las veia
las dos en "banco de auditores -> ver solicitud".

La regla de limpieza es la misma que aplica ahora el codigo: en cada
postulacion se conserva la foto mas reciente y se retiran las demas.

NO modifica nada salvo que se le pase `--aplicar`. Sin esa opcion solo informa.

    python -m modules.scripts.limpiar_fotos_profesionales_duplicadas
    python -m modules.scripts.limpiar_fotos_profesionales_duplicadas --aplicar
"""

import argparse
import asyncio
from pathlib import Path

from sqlalchemy import text

from core.database import AsyncSessionLocal

CONSULTA_DUPLICADAS = text("""
    SELECT
        d.id_documento,
        d.id_postulacion,
        d.url_archivo,
        d.tipo_documento,
        d.estado_revision,
        d.fecha_subida
    FROM documento_auditor d
    INNER JOIN (
        SELECT id_postulacion
        FROM documento_auditor
        WHERE tipo_documento = 'Foto Profesional'
        GROUP BY id_postulacion
        HAVING COUNT(*) > 1
    ) duplicadas
        ON duplicadas.id_postulacion = d.id_postulacion
    WHERE d.tipo_documento = 'Foto Profesional'
    ORDER BY d.id_postulacion, d.fecha_subida DESC
""")


async def limpiar(aplicar: bool) -> int:
    async with AsyncSessionLocal() as session:
        filas = [dict(fila) for fila in (await session.execute(CONSULTA_DUPLICADAS)).mappings().all()]

    por_postulacion: dict = {}
    for fila in filas:
        por_postulacion.setdefault(fila["id_postulacion"], []).append(fila)

    # El listado ya viene ordenado por fecha descendente: la primera es la vigente.
    vigentes = [filas[0] for filas in por_postulacion.values()]
    sobrantes = [
        fila
        for filas in por_postulacion.values()
        for fila in filas[1:]
    ]

    print(f"Postulaciones con mas de una foto profesional: {len(por_postulacion)}")
    print(f"Filas que se conservan: {len(vigentes)}")
    print(f"Filas que se retirarian: {len(sobrantes)}")

    for fila in sobrantes:
        print(
            f"  {fila['id_postulacion']}  {fila['id_documento']}  "
            f"{fila['estado_revision']:<9}  {fila['fecha_subida']}  {fila['url_archivo']}"
        )

    if not sobrantes:
        print("No hay nada que limpiar.")
        return 0

    if not aplicar:
        print("\nSin cambios: ejecuta con --aplicar para borrar estas filas.")
        return 0

    urls_conservadas = {fila["url_archivo"] for fila in a_soltar if fila["url_archivo"]}

    async with AsyncSessionLocal() as session:
        for fila in sobrantes:
            await session.execute(
                text("DELETE FROM documento_auditor WHERE id_documento = :id_documento"),
                {"id_documento": fila["id_documento"]},
            )
        await session.commit()

    # Solo se borra un archivo si ninguna fila que queda lo sigue apuntando.
    for fila in sobrantes:
        url = fila["url_archivo"]
        if not url or url in urls_conservadas:
            continue
        if not url.startswith("/uploads/"):
            continue
        ruta = Path(url.lstrip("/"))
        if ruta.exists():
            try:
                ruta.unlink()
                print(f"  archivo retirado: {ruta}")
            except OSError as error:
                print(f"  no se pudo borrar {ruta}: {error}")

    print(f"\nLimpieza aplicada: {len(sobrantes)} filas retiradas.")
    return len(sobrantes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--aplicar",
        action="store_true",
        help="Borra de verdad. Sin esta opcion el script solo informa.",
    )
    argumentos = parser.parse_args()
    asyncio.run(limpiar(argumentos.aplicar))


if __name__ == "__main__":
    main()
