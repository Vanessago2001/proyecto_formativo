from fastapi import APIRouter

router = APIRouter(
    prefix="/security-policy",
    tags=["Políticas de Seguridad"]
)


@router.get("")
async def obtener_politicas():

    return {
        "maximo_intentos": 5,
        "ventana_minutos": 5,
        "codigo_por_correo": True,
        "vigencia_codigo_minutos": 5,
        "algoritmo_jwt": "HS256"
    }