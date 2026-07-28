# Flujo escalonado de login y restablecimiento de contraseña

> Documentación de la funcionalidad integrada en la rama `feature/login-reset-password`
> y fusionada a `main`. Describe el nuevo comportamiento de autenticación, los
> endpoints agregados y la configuración necesaria.

## 1. Resumen

Se reforzó el proceso de inicio de sesión con un flujo de seguridad **por fases**
y se agregó el **restablecimiento de contraseña por correo**. El objetivo es
frenar intentos de acceso por fuerza bruta de forma progresiva, sin bloquear al
usuario legítimo de golpe.

## 2. Flujo de seguridad en el login

El control se aplica sobre intentos fallidos consecutivos (se reinicia el conteo
si pasan más de 5 minutos entre intentos):

| Fase | Condición | Acción del sistema |
|------|-----------|--------------------|
| **Fase 1** | 3 intentos fallidos (sin código verificado) | Se genera un código de 6 dígitos y se envía al correo. El usuario debe verificarlo para continuar. |
| **Fase 2** | 5 intentos fallidos (con el código ya verificado) | Se envía un **enlace de restablecimiento** de contraseña al correo y la cuenta se bloquea temporalmente 15 minutos. |

Constantes que gobiernan el flujo (`modules/auth/auth_service.py`):

```python
INTENTOS_ANTES_DE_CODIGO = 3   # Fase 1
INTENTOS_ANTES_DE_RESET  = 5   # Fase 2
TIEMPO_BLOQUEO_MINUTOS   = 15  # Bloqueo tras enviar el enlace de reset
RESET_TOKEN_MINUTOS      = 30  # Vigencia del enlace de restablecimiento
DIAS_EXPIRACION          = 0   # Expiración de contraseña (0 = sin expiración)
```

Cuando el backend requiere una acción del usuario responde con **HTTP 403** y un
`detail` estructurado que el frontend (`static/login.html`) interpreta:

```json
{ "accion": "codigo", "mensaje": "..." }   // → mostrar formulario de código
{ "accion": "reset",  "mensaje": "..." }   // → informar que se envió el enlace
```

## 3. Endpoints nuevos

Definidos en `modules/auth/auth_router.py`:

| Método | Ruta | Descripción |
|--------|------|-------------|
| `POST` | `/auth/verificar-codigo` | Valida el código de 6 dígitos enviado al correo. Tras 3 fallos genera y reenvía uno nuevo. |
| `POST` | `/auth/reset-password` | Restablece la contraseña usando el `token` del enlace. Valida la política de contraseña segura y marca el token como usado. |
| `POST` | `/auth/forgot-password` | Opción "¿Olvidó su contraseña?". Envía el enlace de restablecimiento. Responde siempre con un mensaje genérico (anti-enumeración de correos). |

Esquemas asociados (`modules/auth/auth_schema.py`): `CodigoRequest`,
`ResetPasswordRequest`, `ForgotPasswordRequest`.

## 4. Restablecimiento por token

- `POST /auth/forgot-password` o el segundo umbral del login generan un token
  seguro de un solo uso (`secrets.token_urlsafe`) guardado en la tabla
  `password_reset_tokens` (se crea automáticamente si no existe).
- El enlace enviado tiene la forma `${APP_BASE_URL}/reset-password?token=...` y
  vence a los `RESET_TOKEN_MINUTOS` (30 min).
- La página `static/reset-password.html` permite definir la nueva contraseña.
- Al restablecer se limpian bloqueos, contadores e intentos de la cuenta.

## 5. Configuración requerida

Variables de entorno (`core/config.py`):

| Variable | Uso | Valor por defecto |
|----------|-----|-------------------|
| `APP_BASE_URL` | Base para armar el enlace de restablecimiento | `http://127.0.0.1:8000` |
| `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `MAIL_PORT`, ... | Envío de correos (código y enlace) | — |

El envío de correos se realiza en `modules/auth/mail_service.py` mediante
`enviar_codigo(...)` y `enviar_enlace_reset(...)`.

## 6. Notas de la integración a `main`

- Este flujo se combinó con los cambios de los demás colaboradores en `main`,
  conservando la **expiración de contraseña** (`DIAS_EXPIRACION`) y la
  redirección a `cambiar_password.html` cuando la contraseña ha expirado.
- Para `CodigoRequest` se mantuvo la validación de **6 dígitos exactos**, que
  coincide con el código generado por el backend (`randint(100000, 999999)`).
- Se completó una resolución de conflicto que había quedado a medias en
  `modules/users/user_service.py` (quedaban marcadores `<<<<<<<` sin resolver
  que impedían compilar el archivo).
