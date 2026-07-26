import pyotp

# Importaciones locales desde tu carpeta aislada
from reset_password import PasswordResetService
from enable_mfa import EnableMFAService
from disable_mfa import DisableMFAService

def ejecutar_pruebas():
    print("==================================================")
    print(" INICIANDO PRUEBAS EN LA CARPETA INDEPENDIENTE")
    print("==================================================")

    # 1. Simulación de Usuarios en memoria
    admin_user = {"id": "admin_01", "role": "ADMIN"}
    normal_user = {
        "id": "usr_99",
        "email": "desarrollador@ejemplo.com",
        "role": "USER",
        "mfa_enabled": False,
        "mfa_secret": None
    }

    # Instanciar tus servicios
    reset_service = PasswordResetService()
    enable_service = EnableMFAService(app_name="ProyectoPrueba")
    disable_service = DisableMFAService()

    # ----------------------------------------------------
    # PRUEBA SEG-005: Restablecer Contraseña
    # ----------------------------------------------------
    print("\n[1/3] Probando SEG-005 (Reset Password)...")
    res_reset = reset_service.reset_password(admin_user, normal_user)
    print("  -> Éxito! Clave temporal generada:", res_reset["temporary_password"])

    # ----------------------------------------------------
    # PRUEBA SEG-006: Activar MFA
    # ----------------------------------------------------
    print("\n[2/3] Probando SEG-006 (Activar MFA)...")
    init_res = enable_service.initiate_setup(normal_user)
    secret_generado = init_res["secret_key"]
    print("  -> Paso A (Iniciar): Secreto generado =", secret_generado)

    # Generar un código válido simulando la app del celular
    codigo_valido = pyotp.TOTP(secret_generado).now()
    confirm_res = enable_service.confirm_setup(normal_user, codigo_valido)
    print("  -> Paso B (Confirmar):", confirm_res["message"])

    # ----------------------------------------------------
    # PRUEBA SEG-007: Desactivar MFA
    # ----------------------------------------------------
    print("\n[3/3] Probando SEG-007 (Desactivar MFA)...")
    # Generar un código TOTP actual
    codigo_desactivar = pyotp.TOTP(secret_generado).now()
    disable_res = disable_service.disable_mfa(normal_user, codigo_desactivar)
    print("  -> Éxito! Status:", disable_res["message"])

    print("\n==================================================")
    print(" ¡TODAS LAS FUNCIONALIDADES FUNCIONAN CORRECTAMENTE!")
    print("==================================================")

if __name__ == "__main__":
    ejecutar_pruebas()