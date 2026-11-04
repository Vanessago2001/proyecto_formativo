"""
Arranca CertiSENA.

    python iniciar.py                 arranque normal (rápido)
    python iniciar.py --preparar      fuerza la preparación de la base
    python iniciar.py --sql           además imprime cada sentencia SQL
    python iniciar.py --puerto 8080   usa otro puerto
    python iniciar.py --recargar      reinicia solo al guardar un archivo

La preparación de la base (índices, columnas y datos iniciales) tarda unos
35 segundos. Solo hace falta la primera vez y cuando cambia algún archivo
que la prepara; el resto de arranques la saltan solos. Si algo quedara a
medias, `--preparar` la repite.
"""

import argparse
import os
import sys
import webbrowser
from threading import Timer


def principal() -> None:
    lector = argparse.ArgumentParser(description="Arranca la API de CertiSENA.")
    lector.add_argument("--preparar", action="store_true",
                        help="prepara la base aunque no haya cambiado nada")
    lector.add_argument("--sin-preparar", action="store_true",
                        help="no prepara la base en ningún caso")
    lector.add_argument("--sql", action="store_true",
                        help="imprime cada sentencia SQL (para depurar)")
    lector.add_argument("--puerto", type=int, default=8000, help="puerto (por defecto 8000)")
    lector.add_argument("--host", default="127.0.0.1", help="dirección (por defecto 127.0.0.1)")
    lector.add_argument("--recargar", action="store_true",
                        help="reinicia al guardar un archivo (desarrollo)")
    lector.add_argument("--sin-navegador", action="store_true",
                        help="no abre el navegador al terminar de arrancar")
    opciones = lector.parse_args()

    if opciones.preparar and opciones.sin_preparar:
        lector.error("--preparar y --sin-preparar se contradicen.")

    if opciones.preparar:
        os.environ["PREPARAR_BASE"] = "siempre"
    elif opciones.sin_preparar:
        os.environ["PREPARAR_BASE"] = "nunca"
    os.environ["SQL_ECHO"] = "1" if opciones.sql else "0"

    try:
        import uvicorn
    except ImportError:
        print("Falta uvicorn. Active el entorno virtual:  venv\\Scripts\\activate")
        sys.exit(1)

    direccion = f"http://{opciones.host}:{opciones.puerto}"
    print(f"CertiSENA en {direccion}   ·   documentación en {direccion}/docs")
    if opciones.preparar:
        print("Preparando la base de datos: este arranque tardará cerca de medio minuto.")

    if not opciones.sin_navegador and not opciones.recargar:
        Timer(2.0, lambda: webbrowser.open(direccion)).start()

    uvicorn.run(
        "main:app",
        host=opciones.host,
        port=opciones.puerto,
        reload=opciones.recargar,
        log_level="info",
    )


if __name__ == "__main__":
    principal()
