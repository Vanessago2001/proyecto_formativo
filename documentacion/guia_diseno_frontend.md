# Guia de diseno frontend de CertiSENA

Esta guia define como construir nuevas pantallas y componentes para que todo el frontend de CertiSENA conserve el mismo lenguaje visual. La referencia principal es el frontend actual ubicado en `static/`, especialmente `styles.css`, `dashboard.html`, `empresa.html`, `empresas.html`, `auditor.html` y `asignacion-auditores.html`.

## 1. Regla principal

Antes de crear un estilo nuevo:

1. Buscar si ya existe una clase equivalente en `static/styles.css`.
2. Reutilizar la estructura de una pantalla existente.
3. Si el componente se usara en mas de una vista, agregarlo a `styles.css`.
4. Usar estilos dentro del HTML solo para una excepcion verdaderamente local.
5. No redefinir globalmente `button`, `input`, `select`, `table` o `body` en una pantalla sin revisar el impacto sobre las demas.

La consistencia del producto tiene prioridad sobre la preferencia personal de cada implementacion.

## 2. Identidad visual

### Colores aprobados

| Uso | Color | Valor |
| --- | --- | --- |
| Verde principal SENA | Acciones, encabezado, enlaces activos | `#3BAA01` |
| Verde oscuro | Titulos y estados positivos | `#256D00` |
| Verde hover | Hover de acciones principales | `#2D8700` |
| Fondo general | Fondo de la aplicacion | `#F5F7FA` |
| Fondo suave verde | Navegacion activa, avisos informativos | `#F1F8ED` |
| Texto principal | Titulos y contenido | `#333333` o `#1F2937` |
| Texto secundario | Descripciones y ayudas | `#64748B` |
| Borde | Separadores y controles | `#E2E8F0` o `#CBD5E1` |
| Error | Mensajes y acciones destructivas | `#B42318` |
| Fondo de error | Alertas de error | `#FDECEC` |
| Exito | Confirmaciones | `#185B2E` |
| Fondo de exito | Alertas de confirmacion | `#EAF7EA` |

No introducir otra tonalidad de verde, azul o rojo si una de estas cubre el caso. Mantener buen contraste entre texto y fondo.

### Tipografia

- Usar `Montserrat` como familia principal.
- Cargar la fuente en la pagina cuando no este garantizada por el documento:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```

- Texto normal: 14 a 16 px.
- Texto de ayuda: 12 a 14 px.
- Titulos de pagina: 21 a 24 px.
- Titulos de seccion: 17 a 18 px.
- Usar peso 600 o 700 para etiquetas, acciones y titulos.

## 3. Estructura de una pantalla

Las pantallas autenticadas deben conservar esta organizacion:

```html
<body>
  <header class="login-header">
    <div class="header-content">
      <div class="header-left">
        <img src="/static/sena_blanco.png" alt="Logo SENA" class="sena-blanco">
        <div>
          <h1>CertiSENA</h1>
          <p class="subtitle">Nombre del modulo</p>
        </div>
      </div>
      <a class="profile-link" href="/profile">Mi perfil</a>
    </div>
  </header>

  <main class="app-shell">
    <section class="surface">
      <h2>Titulo de la pantalla</h2>
      <p class="page-description">Descripcion breve de la tarea.</p>
      <!-- contenido del modulo -->
    </section>
  </main>
</body>
```

Para modulos con varias secciones, usar una grilla de navegacion lateral y contenido principal, como en `dashboard.html` y `asignacion-auditores.html`:

```html
<main class="app-shell">
  <div class="admin-grid">
    <nav class="admin-nav">...</nav>
    <section class="surface">...</section>
  </div>
</main>
```

## 4. Encabezado y navegacion

- Usar `.login-header`, `.header-content`, `.header-left`, `.sena-blanco` y `.subtitle`.
- Mantener el encabezado verde de 90 px en escritorio.
- En pantallas pequenas ocultar `.header-buttons` y mostrar `.hamburger-btn`.
- Todas las imagenes deben tener `alt` descriptivo.
- El enlace activo debe ser evidente con fondo verde suave, texto verde oscuro o fondo verde principal, segun el tipo de navegacion.
- El enlace de cerrar sesion debe distinguirse visualmente y pedir confirmacion si la accion puede ser accidental.

## 5. Superficies, paneles y espaciado

Usar una superficie blanca para agrupar contenido funcional:

```css
.surface {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 24px;
}
```

Reglas de espaciado:

- Contenedor de pagina: ancho maximo entre 1100 y 1320 px.
- Margen automatico horizontal: `margin: 0 auto`.
- Padding de pagina: 20 a 28 px en escritorio; 18 px en movil.
- Separacion entre controles: 12 a 16 px.
- Separacion entre secciones: 24 px.
- Radios: 4 a 8 px para controles y paneles. Reservar 12 px para portales ya existentes que lo usan como patron.
- Las sombras deben ser suaves y discretas; no usar sombras pesadas en cada elemento.

No anidar tarjetas dentro de tarjetas salvo que una tarjeta interior represente una entidad repetida o un formulario independiente.

## 6. Formularios

Usar siempre una etiqueta visible asociada al control mediante `for` e `id`:

```html
<div class="field">
  <label for="nombre">Nombre</label>
  <input id="nombre" name="nombre" type="text" required>
</div>
```

Patron recomendado para formularios:

```css
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(220px, 1fr));
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field.full {
  grid-column: 1 / -1;
}
```

Controles:

- Ancho completo dentro de su columna.
- Padding aproximado de 10 a 14 px.
- Borde de 1 px y radio de 4 a 8 px.
- `font: inherit` para conservar Montserrat.
- Estado `:focus` visible, con borde verde y un contorno accesible.
- No usar placeholders como reemplazo de la etiqueta.
- Mostrar validacion junto al campo o en un mensaje claro; no depender solo del color.

## 7. Botones y acciones

Cada pantalla debe usar una jerarquia clara:

```html
<button class="btn-primary" type="submit">Guardar</button>
<button class="btn-secondary" type="button">Cancelar</button>
<button class="btn-danger" type="button">Eliminar</button>
```

```css
.btn-primary {
  background: #3baa01;
  color: #fff;
}

.btn-secondary {
  background: #eef3ee;
  color: #1f3d12;
}

.btn-danger {
  background: #e53935;
  color: #fff;
}
```

- La accion principal debe ser unica y visualmente dominante.
- Cancelar, limpiar o volver son acciones secundarias.
- Eliminar, bloquear o cerrar sesion son acciones de peligro.
- Desactivar el boton durante una peticion y cambiar su estado a cargando.
- Conservar `cursor: pointer` y un estado `:hover`.
- No crear botones redondeados con tamanos, colores o nombres distintos para cada modulo.

## 8. Tablas, estados y mensajes

Para tablas anchas, envolver siempre el contenido:

```html
<div class="table-wrap">
  <table>...</table>
</div>
```

```css
.table-wrap {
  overflow-x: auto;
}

table {
  width: 100%;
  border-collapse: collapse;
}

th,
td {
  padding: 10px 12px;
  text-align: left;
  border-bottom: 1px solid #e2e8f0;
}

th {
  background: #f8fafc;
  color: #475569;
}
```

Usar chips o clases de estado consistentes:

- Positivo/activo: fondo verde claro y texto verde oscuro.
- Pendiente/en proceso: fondo amarillo claro y texto marron oscuro.
- Error/inactivo/rechazado: fondo rojo claro y texto rojo oscuro.

Los mensajes deben comunicar el resultado de la accion. Preferir `.message`, `.alert`, `.success-message` o `.error-message` ya existentes antes de crear otra variante.

## 9. Responsive

Toda pantalla nueva debe probarse en escritorio y movil.

- Punto de adaptacion habitual: `720px`, `770px` u `800px`, segun la estructura.
- Una grilla de dos columnas debe pasar a una columna.
- El menu superior debe pasar al menu hamburguesa.
- Los botones agrupados deben poder envolver o ocupar el ancho disponible.
- Las tablas no deben romper la pagina: usar desplazamiento horizontal.
- El contenido no debe quedar oculto detras del encabezado ni desbordar horizontalmente.

Ejemplo:

```css
@media (max-width: 720px) {
  .app-shell {
    padding: 18px;
  }

  .admin-grid,
  .form-grid {
    grid-template-columns: 1fr;
  }
}
```

## 10. Accesibilidad y comportamiento

- Usar HTML semantico: `header`, `nav`, `main`, `section`, `form`, `table`.
- Asociar labels y controles.
- Mantener el foco visible.
- Usar `aria-label` en botones de icono o menu hamburguesa.
- No comunicar estados unicamente con color.
- Informar carga, exito y error cerca de la accion que los produjo.
- Escapar datos recibidos de la API antes de insertarlos en HTML.
- No guardar informacion sensible en el HTML ni en `localStorage` sin justificacion.

## 11. Flujo de trabajo para cada integrante

1. Identificar el tipo de pantalla: formulario, listado, dashboard, portal o consulta publica.
2. Elegir una pantalla existente como referencia directa.
3. Crear el HTML con las clases comunes antes de escribir CSS nuevo.
4. Reutilizar nombres de clases y colores aprobados.
5. Si un estilo se repite, moverlo a `static/styles.css`.
6. Probar estados normal, cargando, vacio, exito, error y permiso denegado.
7. Probar una vista de escritorio y otra de movil.
8. Revisar teclado, labels, foco y mensajes.
9. Verificar que la consola no tenga errores y que las rutas funcionen.
10. En la entrega, indicar que clases comunes se reutilizaron y que componentes nuevos se agregaron.

## 12. Lista de comprobacion antes de entregar

- [ ] La pagina enlaza `static/styles.css`.
- [ ] Usa Montserrat y la paleta definida.
- [ ] Reutiliza el encabezado y la navegacion del proyecto.
- [ ] No redefine estilos globales sin necesidad.
- [ ] Los formularios tienen labels, validacion y estados de error.
- [ ] Las tablas tienen `.table-wrap`.
- [ ] La accion principal se distingue de cancelar y eliminar.
- [ ] La vista funciona en movil.
- [ ] No hay overflow horizontal accidental.
- [ ] No hay estilos duplicados que deban ir a `styles.css`.
- [ ] Se probaron carga, vacio, exito y error.

## 13. Deuda visual actual que debe evitarse

El frontend existente contiene varias implementaciones locales del mismo concepto. En nuevas pantallas no se deben multiplicar estas diferencias:

- Radios de 4, 6, 8 y 12 px para botones o paneles equivalentes.
- Variantes de verde como `#3BAA01`, `#43A047` y `#2F7D32` para la misma accion.
- Clases diferentes para botones equivalentes: `.primary-action`, `.btn-primary`, `.btn-login` y estilos directos de `button`.
- Estilos inline para margenes y visibilidad cuando puede usarse una clase.
- Tablas con encabezado verde en una pagina y gris claro en otra sin una razon funcional.

Estas diferencias pueden corregirse gradualmente. Para funcionalidades nuevas, usar primero los patrones de esta guia y centralizar los componentes que se reutilicen.