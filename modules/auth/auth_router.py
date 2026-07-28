from fastapi import APIRouter, Depends, Request, status, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.auth.auth_service import AuthService
from modules.auth.mail_service import MailService
from modules.auth.auth_schema import LoginRequest, CodigoRequest
from modules.auth.dependencies import require_admin_access


router = APIRouter(
    prefix="/auth",
    tags=["Autenticación"]
)


# ============================================================
# LOGIN
# ============================================================

@router.post("/login", status_code=status.HTTP_200_OK)
async def sign_in(
    payload: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    client_ip = request.headers.get("x-forwarded-for") or (
        request.client.host if request.client else "unknown"
    )

    service = AuthService(db)

    token = await service.login(
        payload.correo,
        payload.password,
        client_ip=client_ip
    )

    return {
"access_token": token,
"token_type": "bearer"
}


# ============================================================
# SOLO PARA PRUEBAS
# ============================================================

@router.get("/diagnostico-db")
async def diagnostico_db(
    db: AsyncSession = Depends(get_db),
):
    query = text("""
    SELECT
    correo,
    codigo_verificacion,
    codigo_expira,
    codigo_verificado
    FROM usuario
    WHERE correo = 'admin@empresa.com';
    """)

    result = await db.execute(query)

    return {
"usuarios": [
    dict(row)
    for row in result.mappings().all()
]
}


# ============================================================
# DIAGNÓSTICO MFA
# ============================================================

@router.get("/prueba-mfa")
async def diagnostico_mfa(
    db: AsyncSession = Depends(get_db),
):
    query = text("""
    SELECT
    correo,
    mfa_activado,
    mfa_expira,
    mfa_verificado,
    mfa_codigo
    FROM usuario
    WHERE correo = 'admin@empresa.com';
    """)

    result = await db.execute(query)

    return {
"usuarios": [
    dict(row)
    for row in result.mappings().all()
]
}


# ============================================================
# PRUEBA DE CORREO
# ============================================================

@router.get("/test-mail")
async def test_mail():

    await MailService.enviar_codigo(
        destinatario="marlontaborda12@gmail.com",
        codigo="123456"
    )

    return {
"mensaje": "Correo enviado correctamente"
}


# ============================================================
# VERIFICAR CÓDIGO MFA
# ============================================================

@router.post("/verificar-codigo")
async def verificar_codigo(
    datos: CodigoRequest,
    db: AsyncSession = Depends(get_db)
):
    service = AuthService(db)

    return await service.verificar_codigo(
datos.correo,
datos.codigo
)


# ============================================================
# HISTORIAL DE ACCESOS
# ============================================================

@router.get("/historial-accesos")
async def historial_accesos(
    pagina: int = Query(
        1,
        ge=1,
    ),
    limite: int = Query(
        50,
        ge=1,
        le=200,
    ),
    current_user=Depends(require_admin_access),
    db: AsyncSession = Depends(get_db),
):

    service = AuthService(db)

    logs = await service.obtener_historial_accesos(
        pagina=pagina,
        limite=limite,
    )

    return {
"pagina": pagina,
"limite": limite,
"total": len(logs),
"registros": logs,
}