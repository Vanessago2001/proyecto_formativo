import pyotp

class DisableMFAService:
    
    def disable_mfa(self, user: dict, totp_code: str) -> dict:
        """
        Desactiva el MFA en la cuenta tras validar un código TOTP activo.
        """
        if not user.get("mfa_enabled") or not user.get("mfa_secret"):
            raise ValueError("El usuario no tiene la autenticación MFA activa.")

        # Validar el código antes de deshabilitar
        totp = pyotp.TOTP(user["mfa_secret"])
        if not totp.verify(totp_code):
            raise ValueError("Código TOTP inválido. No se puede desactivar el MFA.")

        # Desactivación y limpieza de campos
        user["mfa_enabled"] = False
        user["mfa_secret"] = None

        return {
            "status": "success",
            "message": "Autenticación en dos pasos (MFA) desactivada correctamente.",
            "updated_user": user
        }