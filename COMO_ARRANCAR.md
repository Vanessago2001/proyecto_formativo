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
- Nunca suba los archivos `.p12` ni esas líneas del `.env` al repositorio.
  En producción el .p12 lo emite una entidad certificadora real.
