# Documentación de requisitos no funcionales y permisos

Fecha: 2026-07-21
Proyecto: API modular con FastAPI, SQLAlchemy async y autenticación JWT

## 1. Objetivo del documento

Este documento consolida lo que se ha implementado en el proyecto y lo organiza por requisitos no funcionales, incluyendo los permisos y rol que deben regir el acceso a la API.

---

## 2. Resumen de lo realizado

Se ajustó la API para que quede alineada con la guía del proyecto y con la lógica de seguridad definida en la documentación de login. Entre los cambios más importantes están:

- Implementación de autenticación con JWT.
- Uso de hash de contraseñas con bcrypt.
- Validaciones de login con control de intentos fallidos.
- Bloqueo temporal de cuentas tras múltiples accesos incorrectos.
- Registro de trazabilidad de accesos en base de datos.
- Compatibilidad con la estructura modular por dominios.
- Preparación del proyecto para soportar rol y permisos de forma organizada.

---

## 3. Requisitos no funcionales documentados

### RNF-01: Seguridad

**Descripción**
Se implementó una capa de seguridad básica para proteger el acceso a la API y evitar accesos no autorizados.

**Acciones realizadas**
- Se usa bcrypt para almacenar contraseñas de forma segura.
- Se genera un token JWT para autenticar a los usuarios.
- Se valida el acceso mediante credenciales y token.
- Se protege la ruta de login con control de errores claros y seguros.

**Impacto en el proyecto**
- Reduce el riesgo de exposición de credenciales.
- Mejora la seguridad del flujo de autenticación.

---

### RNF-02: Autorización y permisos por rol

**Descripción**
La API está preparada para trabajar con diferentes perfiles de usuario y permisos según su rol.

**rol definidos**
- Administrador
  - Acceso total al sistema.
  - Puede gestionar usuarios, rol y tareas.
- Instructor
  - Puede gestionar tareas y usuarios de forma limitada.
- Aprendiz
  - Acceso restringido a consultas y perfil personal.

**Estado actual del proyecto**
- La estructura permite asignar un rol a cada usuario mediante el campo role_id.
- Se incorporaron validaciones de negocio en los servicios para evitar acciones indebidas.
- La lógica de permisos puede reforzarse en los routers para asegurar control total en todos los endpoints.

**Objetivo esperado**
- Garantizar que cada usuario solo acceda a las funciones permitidas por su rol.

---

### RNF-03: Trazabilidad y auditoría

**Descripción**
Se implementó un mecanismo de registro de accesos para auditar los intentos de ingreso al sistema.

**Acciones realizadas**
- Se creó la tabla logs_acceso.
- Cada intento de login queda registrado con:
  - usuario involucrado o correo intentado,
  - IP de origen,
  - resultado del intento,
  - motivo del fallo,
  - fecha y hora.

**Impacto**
- Permite identificar accesos fallidos y comportamientos sospechosos.
- Facilita la auditoría y el seguimiento de seguridad.

---

### RNF-04: Integridad de datos

**Descripción**
Se trabajó para que los datos de usuarios y rol se mantengan consistentes dentro de la base de datos.

**Acciones realizadas**
- Se valida que el rol asignado a un usuario exista.
- Se evita duplicar usuarios con el mismo correo o nombre de usuario.
- Se mantienen valores coherentes para el estado de la cuenta y los intentos fallidos.

**Impacto**
- Evita errores de negocio y corrupción de datos en los procesos de registro y autenticación.

---

### RNF-05: Mantenibilidad y arquitectura modular

**Descripción**
El proyecto se organizó por módulos para que sea más claro, escalable y fácil de mantener.

**Módulos incluidos**
- auth: autenticación y login.
- users: gestión de usuarios.
- rol: gestión de rol.
- tareas: gestión de tareas.
- core: configuración, base de datos, seguridad y logs.

**Impacto**
- Facilita futuras modificaciones.
- Permite crecer el sistema sin mezclar responsabilidades.

---

### RNF-06: Disponibilidad y recuperación básica

**Descripción**
Se incluyó una inicialización básica del sistema para preparar datos y tablas al arrancar la API.

**Acciones realizadas**
- Se creó un proceso de seed inicial para rol y usuario administrador.
- Se habilitó la carga de datos iniciales al iniciar la aplicación.

**Impacto**
- El sistema puede arrancar de forma más organizada y con datos base listos para pruebas.

---

## 4. Matriz de permisos sugerida

| Rol | Permisos previstos |
|---|---|
| Administrador | Crear, editar y eliminar usuarios, rol y tareas; ver reportes y logs; gestionar estados de cuentas |
| Instructor | Gestionar tareas; administrar usuarios de forma limitada; consultar información general |
| Aprendiz | Iniciar sesión; consultar su propio perfil; actualizar sus datos básicos sin modificar rol ni estados |

---

## 5. Conclusión

La implementación realizada deja el proyecto más seguro, más organizado y más alineado con los requisitos funcionales y no funcionales del sistema. La base para permisos, trazabilidad y autenticación quedó establecida de forma clara para continuar con futuras mejoras.
