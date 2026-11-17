# Cómo arrancar CertiSENA

## En un paso

Doble clic en **`iniciar.bat`**, o desde la consola:

```
python iniciar.py
```

Abre el navegador solo y queda en <http://127.0.0.1:8000>.
La documentación de la API está en <http://127.0.0.1:8000/docs>.

## La primera vez

La base necesita una preparación inicial (índices, columnas y los datos de
arranque). Tarda cerca de medio minuto y **solo hace falta una vez**:

```
python iniciar.py --preparar
```

Después de eso los arranques son directos, porque el programa recuerda que la
base ya quedó lista.

## Cuándo vuelve a prepararla sola

No hay que acordarse de nada: la repite sola cuando

- cambia alguno de los archivos que preparan la base (`main.py` o cualquier
  `*_bootstrap.py` de un módulo),
- se apunta a otra base de datos,
- o falta alguna tabla o columna (por ejemplo, tras restaurar una copia vieja).

En el registro siempre dice cuál de los dos caminos tomó:

```
Arranque directo: la base ya estaba preparada.
Preparando la base de datos (cambió algún archivo de preparación)...
```

## Opciones

| Opción | Para qué |
|---|---|
| `--preparar` | Prepara la base aunque no haya cambiado nada |
| `--sin-preparar` | No la prepara en ningún caso |
| `--recargar` | Reinicia al guardar un archivo (mientras se programa) |
| `--sql` | Imprime cada sentencia SQL (para depurar) |
| `--puerto 8080` | Usa otro puerto |
| `--sin-navegador` | No abre el navegador |

Las mismas opciones valen con `iniciar.bat`:

```
iniciar.bat --recargar
```

## Si se prefiere uvicorn a mano

Sigue funcionando igual que antes:

```
venv\Scripts\python.exe -m uvicorn main:app --reload
```

Y se puede controlar con variables de entorno:

- `PREPARAR_BASE=auto` (por defecto) · `siempre` · `nunca`
- `SQL_ECHO=1` para ver el SQL en la consola

## Por qué el SQL ya no llena la pantalla

El motor venía con `echo=True`, así que imprimía **todas** las sentencias de
todas las peticiones. Ahora está apagado por defecto y se enciende cuando hace
falta con `--sql` o `SQL_ECHO=1`.

## Firmar certificados en su computador (firma de PRUEBA)

Para firmar certificados, el servidor necesita el certificado digital (.p12)
del líder del Comité. En desarrollo cada quien genera una firma de prueba en
su propio equipo (no se comparte ni se sube a git):

```
venv\Scripts\python.exe -m modules.scripts.configurar_firma_prueba
```

- Crea la firma del líder vigente en `C:\Users\<usuario>\.certisena_firma`
  y agrega las variables `CERTIFICADOS_FIRMA_*` a su `.env`.
- Luego reinicie el servidor. En la aplicación, el líder crea su
  "contraseña de firma" la primera vez y ya puede firmar.
- Si cambian de líder del Comité, ejecútelo de nuevo con `--forzar`.
- El líder ahora se elige POR EXPEDIENTE (el Coordinador lo escoge en el
  Comité entre quienes evaluaron ese expediente), así que cualquier miembro
  del Comité puede tener que firmar. Para crear la firma de prueba de TODOS
  los miembros activos del Comité de una vez:

  ```
  venv\Scripts\python.exe -m modules.scripts.configurar_firma_prueba --todos-comite
  ```

  Crea el `.p12` de quien aún no lo tenga (con `--forzar` los reemplaza) y
  AÑADE sus contraseñas a `CERTIFICADOS_FIRMA_PASSWORDS_JSON` y la CA nueva a
  `CERTIFICADOS_FIRMA_TRUST_ROOTS_JSON` sin borrar las que ya había. Con
  `--sin-env` solo crea los archivos. Reinicie el servidor después.
- El líder por expediente necesita el SQL
  `documentacion/sql_lider_por_expediente.sql`; mientras no se aplique se
  sigue usando el líder global de Gestión de certificados.
- Nunca suba los archivos `.p12` ni esas líneas del `.env` al repositorio.
  En producción el .p12 lo emite una entidad certificadora real.

## Archivos compartidos

La base es la misma para todo el equipo, pero cada uno corre su propio
servidor. Los archivos subidos (hojas de vida, fotos, documentos de empresas y
solicitudes, evidencias, PQRS, actas, certificados firmados) se guardan ahora
**también en la base** (tabla `archivo_almacenado`), así que un documento
subido desde un computador se ve desde todos. El disco local (`uploads/` y
`storage/`) queda como caché: si un archivo falta, se trae de la base la
primera vez que alguien lo abre.

Para activarlo:

1. **Una sola persona, una sola vez**: ejecutar en la base el SQL de
   `documentacion/sql_archivos_compartidos.sql`.
2. **Cada integrante, una vez en su computador**: subir los archivos que solo
   tiene en su disco. Primero ver qué subiría (no escribe nada):

   ```
   venv\Scripts\python.exe -m modules.scripts.subir_archivos_locales --dry-run
   ```

   y luego subirlos de verdad:

   ```
   venv\Scripts\python.exe -m modules.scripts.subir_archivos_locales
   ```

   Se puede repetir sin problema: lo que ya está igual en la base no se vuelve
   a subir.
3. **Reiniciar el servidor.**

Mientras el SQL no se haya aplicado todo sigue funcionando como antes (cada
archivo solo en el disco donde se subió) y el registro muestra una vez el aviso
`La tabla archivo_almacenado no existe`. Límite por archivo en la base: 25 MB.
