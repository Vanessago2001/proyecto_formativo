# M9 - Certificados

El módulo usa la tabla `certificado` existente. No la recrea; al iniciar agrega
de forma idempotente la secuencia correlativa, el historial, la asignación de
líder y las columnas de snapshot/firmante/huellas. Además se requieren las
tablas existentes `usuario` y `rol`.

## Operaciones

La API está disponible bajo `/certificados` y se puede consultar en `/docs`.
La gestión autenticada se sirve en `/gestion-certificados`; la búsqueda pública
sin inicio de sesión está disponible en `/verificar-certificado`.

| Operación | Ruta |
| --- | --- |
| Generar certificado desde una solicitud aprobada y un alcance asociado | `POST /certificados/` |
| Consultar listado o detalle | `GET /certificados/`, `GET /certificados/{id_certificado}` |
| Generar PDF de revisión | `GET /certificados/{id_certificado}/pdf/preview` |
| Descargar PDF firmado y verificado por huella | `GET /certificados/{id_certificado}/pdf` |
| Reenviar el PDF PAdES firmado por correo | `POST /certificados/{id_certificado}/reenviar` |
| Renovar y crear un nuevo registro | `POST /certificados/{id_certificado}/renovar` |
| Suspender, reactivar o cancelar | `POST /certificados/{id_certificado}/suspender`, `/reactivar`, `/cancelar` |
| Registrar motivo de suspensión sin ejecutarla | `POST /certificados/{id_certificado}/motivo-suspension` |
| Registrar motivo de cancelación sin ejecutar la cancelación | `POST /certificados/{id_certificado}/motivo-cancelacion` |
| Consultar historial | `GET /certificados/{id_certificado}/historial` |
| Publicar o retirar del portal | `POST /certificados/{id_certificado}/publicar`, `/retirar-portal` |
| Buscar certificado público y descargar el PDF PAdES | `GET /certificados/publico/{codigo}`, `/publico/{codigo}/pdf` |
| Métricas, exportaciones y vencimientos | `GET /certificados/metricas`, `/exportar`, `/empresas-oficiales`, `/alertas/vencimiento` |
| Notificar próximo vencimiento | `POST /certificados/notificar-vencimiento/{id_certificado}` |
| Registrar cambio de alcance (Superadministrador) | `POST /certificados/{id_certificado}/alcance` |
| Listar personas Comité activas y consultar líder actual | `GET /certificados/lider-comite/opciones`, `/lider-comite/actual` |
| Asignar líder (Superadmin/Administrador) | `PUT /certificados/lider-comite` |
| Firmar PAdES con el líder asignado | `POST /certificados/{id_certificado}/firmar` |

Las empresas solo pueden consultar certificados asociados a sus vínculos activos
en `user_empresa`. El portal público solo expone certificados publicados,
vigentes y no vencidos, siempre que exista firmante asignado, huellas y archivo
PAdES registrados. Las
acciones marcadas `REQ` responden con
`requiere_aprobacion: true`; en el CSV se informa mediante
`X-Requiere-Aprobacion: true`.

## Firma y correo

La generación crea el registro en `PENDIENTE_FIRMA` y lo asocia a la asignación
activa del líder. Solo la cuenta de esa persona puede firmarlo. El servidor
abre el PKCS#12 externo asignado a su UUID, comprueba vigencia y coincidencia de
correo, firma el PDF en formato PAdES y valida su cadena contra las raíces CA
configuradas. Tras completar el proceso, guarda firmante, fecha, hash SHA-256
del PDF y huella del certificado; el registro pasa a `VIGENTE`.

La configuración de credenciales, almacenamiento externo, CA de confianza y
limitaciones TSA está en [la guía de firma del Comité](../../guia_firma_comite.md).
Sin PKCS#12, contraseña o raíz CA para el líder, la operación falla cerrada y
no cambia el certificado a vigente. La publicación exige una firma y un archivo
PAdES ya registrados. El envío de correo requiere `MAIL_SERVER` y `MAIL_FROM`.

Las alertas y notificaciones se ejecutan por endpoint; todavía no hay un
planificador automático de tareas.