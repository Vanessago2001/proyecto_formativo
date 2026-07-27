import pyotp

class EnableMFAService:
    def __init__(self, app_name: str = "MiProyecto"):
        self.app_name = app_name

    def initiate_setup(self, user: dict) -> dict:
        """
        Paso 1: Genera el secreto TOTP y la URI para el QR.
        """
        if user.get("mfa_enabled"):
            raise ValueError("El usuario ya tiene la autenticación MFA activada.")

        # Generar clave secreta temporal
        secret_key = pyotp.random_base32()
        user["pending_mfa_secret"] = secret_key

        # Generar URI compatible con apps como Google Authenticator o Authy
        totp = pyotp.TOTP(secret_key)
        qr_uri = totp.provisioning_uri(name=user.get("email"), issuer_name=self.app_name)

        return {
            "status": "pending",
            "secret_key": secret_key,
            "qr_uri": qr_uri,
            "updated_user": user
        }

    def confirm_setup(self, user: dict, totp_code: str) -> dict:
        """
        Paso 2: Valida el código TOTP enviado por el usuario y activa el MFA.
        """
        pending_secret = user.get("pending_mfa_secret")
        if not pending_secret:
            raise ValueError("No se ha iniciado un proceso de activación de MFA.")

        totp = pyotp.TOTP(pending_secret)
        if not totp.verify(totp_code):
            raise ValueError("Código TOTP incorrecto o expirado.")

        # Confirmación exitosa: guardar secreto definitivo
        user["mfa_secret"] = pending_secret
        user["mfa_enabled"] = True
        user["pending_mfa_secret"] = None  # Limpieza de variable temporal

        return {
            "status": "success",
            "message": "Autenticación en dos pasos (MFA) activada correctamente.",
            "updated_user": user
        }