from fastapi import APIRouter

router = APIRouter(
    prefix="/security-policy",
    tags=["Políticas de Seguridad"]
)


@router.get("")
async def obtener_politicas():

    return {
        "intentos_antes_de_codigo": 3,
        "intentos_antes_de_reset": 5,
        "ventana_minutos": 5,
        "codigo_por_correo": True,
        "vigencia_codigo_minutos": 5,
        "reset_por_correo": True,
        "vigencia_enlace_reset_minutos": 30,
        "bloqueo_tras_reset_minutos": 15,
        "algoritmo_jwt": "HS256"
    }