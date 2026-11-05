# Despliegue de CertiSENA en VPS Linux

Guía para Ubuntu Server con Nginx, systemd, Redis y PostgreSQL administrado o
externo. La aplicación escucha solo en `127.0.0.1:8000`; Nginx es el único
servicio web expuesto.

## Requisitos previos

- Dominio con un registro DNS `A` apuntando a la IP pública del VPS.
- Base PostgreSQL accesible desde el VPS. El usuario configurado necesita
  permisos de lectura/escritura y, durante el arranque automático, permisos
  para preparar el esquema.
- Acceso SSH con permisos `sudo`.

## 1. Instalar paquetes y crear el usuario

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-dev build-essential \
  libpq-dev redis-server nginx certbot python3-certbot-nginx
sudo adduser --system --group --home /opt/certisena --no-create-home certisena
sudo mkdir -p /opt/certisena/app
```

Copiar o clonar el contenido de este proyecto en `/opt/certisena/app`. No
copiar archivos `.env`, certificados personales, ni carpetas locales de
desarrollo. Instalar las dependencias en un entorno virtual:

```bash
cd /opt/certisena/app
sudo python3 -m venv .venv
sudo .venv/bin/pip install --upgrade pip
sudo .venv/bin/pip install -r requirements.txt
sudo install -d -o certisena -g certisena -m 0750 storage uploads
sudo chown -R root:certisena /opt/certisena/app
sudo chown -R certisena:certisena /opt/certisena/app/storage /opt/certisena/app/uploads
```

Los directorios `storage` y `uploads` deben persistir entre despliegues: allí
se guardan documentos cargados, actas, certificados publicados y el estado de
preparación de la base.

## 2. Configurar el entorno

```bash
sudo install -d -o root -g certisena -m 0750 /etc/certisena
sudo install -o root -g certisena -m 0640 .env.example /etc/certisena/certisena.env
sudo nano /etc/certisena/certisena.env
```

Reemplazar todos los valores de ejemplo. Generar un secreto con:

```bash
openssl rand -hex 32
```

Pegar el resultado en `SECRET_KEY`. Ajustar `APP_BASE_URL` al dominio HTTPS.
Configurar `DATABASE_URL` con el esquema `postgresql+asyncpg`; codificar los
caracteres especiales del usuario o contraseña. Si el proveedor exige TLS,
conservar su configuración SSL compatible con `asyncpg`.

Redis debe permanecer accesible solo localmente. La plantilla usa
`redis://127.0.0.1:6379/0`; no abrir el puerto 6379 en el firewall.

## 3. Preparar firma digital

La firma de certificados y actas requiere un PKCS#12 válido para cada líder
activo, su contraseña y las CA de confianza. Antes de habilitar firmas:

```bash
sudo install -d -o root -g certisena -m 0750 /etc/certisena/firma
```

1. Instalar cada archivo como `/etc/certisena/firma/<id_usuario>.p12`, con
   propietario `root:certisena` y permisos `0640`.
2. Dar lectura solo al usuario del servicio: propietario `root`, grupo
   `certisena`, permisos `0640`; el directorio debe ser `0750`.
3. En `CERTIFICADOS_FIRMA_PASSWORDS_JSON`, configurar un objeto JSON cuyas
   claves sean los UUID de usuario y cuyos valores sean las contraseñas de
   PKCS#12.
4. En `CERTIFICADOS_FIRMA_TRUST_ROOTS_JSON`, configurar una lista JSON de
   rutas a certificados raíz CA PEM/DER de confianza.

No usar certificados de prueba ni CA arbitrarias en producción. La contraseña
PKCS#12 queda en el archivo de entorno restringido; rotar sus permisos y
respaldos como material secreto.

## 4. Instalar systemd y arrancar la API

```bash
sudo install -o root -g root -m 0644 deploy/systemd/certisena.service \
  /etc/systemd/system/certisena.service
sudo systemctl daemon-reload
sudo systemctl enable --now certisena
sudo systemctl status certisena
sudo journalctl -u certisena -n 100 --no-pager
```

El servicio inicia con un worker para evitar que varios procesos preparen el
esquema a la vez. En el primer inicio `PREPARAR_BASE=auto` puede tardar varios
minutos y requiere permisos DDL en PostgreSQL. Revisar los registros antes de
continuar; no cambiar a `PREPARAR_BASE=nunca` hasta que el esquema esté
preparado y respaldado.

Comprobar el backend desde el VPS:

```bash
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:8000/
```

## 5. Configurar Nginx y HTTPS

Editar `server_name` en `deploy/nginx/certisena.conf` con el dominio real y
después instalarlo:

```bash
sudo install -o root -g root -m 0644 deploy/nginx/certisena.conf \
  /etc/nginx/sites-available/certisena
sudo ln -s /etc/nginx/sites-available/certisena /etc/nginx/sites-enabled/certisena
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d certisena.example.com
```

Reemplazar `certisena.example.com` por el dominio propio. Permitir en el
firewall solo SSH, HTTP y HTTPS:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

No abrir el puerto 8000: está enlazado a loopback. Verificar renovación con
`sudo certbot renew --dry-run`.

## 6. Comprobaciones y operación

- Abrir `https://<dominio>/` y `https://<dominio>/docs`.
- Revisar `sudo journalctl -u certisena -f` ante errores de arranque o base.
- Respaldar PostgreSQL y el contenido persistente de `storage`, `uploads` y
  `/var/lib/certisena`; probar la restauración.
- Tras actualizar el código, conservar esos datos y ejecutar:

```bash
sudo systemctl restart certisena
sudo systemctl status certisena
```

No se puede confirmar una instalación real hasta probar conectividad con la
base del proveedor, dominio, certificados y credenciales de firma del entorno
de producción.
