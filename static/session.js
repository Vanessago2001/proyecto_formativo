/* ==========================================================
   Cierre de sesión por inactividad - CertiSENA
   ==========================================================

   Política: 30 minutos sin interacción. Faltando un minuto aparece
   un aviso con cuenta atrás y un botón para seguir activo.

   Cómo está resuelto y por qué:

   - Se guarda la hora de la última actividad y se compara contra la
     fecha límite en revisiones periódicas, en lugar de fiar los 30
     minutos a un único setTimeout. Los temporizadores largos se
     congelan con la pestaña en segundo plano o el equipo suspendido,
     y al despertar el plazo se acorta sin que nadie lo cuente; con
     Date.now() el tiempo real siempre es el correcto.
   - En pantallas sin sesión (acceso, registro, recuperar contraseña)
     no cierra nada: solo muestra el aviso del cierre pendiente.
   - Se entera de lo que hacen las demás pestañas por el evento
     "storage", de modo que cerrar la sesión en una cierra todas.
   - Nada del archivo es global. Desde otra pantalla se puede ajustar
     la política antes de cargar este script:
       window.CERTISENA_SESION = { inactividadMs: 20000, avisoMs: 5000 };

   Los eventos de actividad se escuchan en fase de captura para que
   ningún stopPropagation de la pantalla impida renovar el plazo.
   ========================================================== */
(function () {
  "use strict";

  var CONFIG = Object.assign({
    inactividadMs: 30 * 60 * 1000,   // plazo de cierre
    avisoMs: 60 * 1000,              // cuándo aparece la cuenta atrás
    revisionMs: 15 * 1000,           // cada cuánto se comprueba el plazo
    actividadMinMs: 15 * 1000        // cuánto dura renovar antes de ese rato
  }, window.CERTISENA_SESION || {});

  var CLAVE_TOKEN = "access_token";
  var CLAVE_AVISO = "aviso_cierre_sesion";
  var RUTA_ACCESO = "/login";

  /* Lo que deja el inicio de sesión en el navegador. La contraseña
     expirada guarda el correo del usuario, que no debe quedar
     disponible para quien use el equipo después. */
  var CLAVES_SESION = [CLAVE_TOKEN, "token_type", "token", "accessToken", "correo_expirado"];

  /* Mover el ratón no cuenta como actividad: una sesión podría
     mantenerse abierta indefinidamente sin nadie delante de la
     pantalla. */
  var EVENTOS_ACTIVIDAD = ["mousedown", "keydown", "scroll", "touchstart", "input"];

  function etiquetaDuracion(ms) {
    var minutos = ms / 60000;
    if (minutos >= 1) return Math.round(minutos) + (minutos < 2 ? " minuto" : " minutos");
    return Math.round(ms / 1000) + " segundos";
  }

  var MENSAJES = {
    inactividad: "La sesión se cerró automáticamente por " +
      etiquetaDuracion(CONFIG.inactividadMs) + " sin actividad.",
    otraPestana: "La sesión se cerró en otra pestaña de este navegador."
  };

  var ultimaActividad = Date.now();
  var vigilando = false;
  var cerrando = false;
  var reloj = null;
  var caja = null;
  var tictac = null;
  var escondite = null;

  // ==========================================================
  // Lectura del estado
  // ==========================================================

  function haySesion() {
    try { return !!localStorage.getItem(CLAVE_TOKEN); } catch (_) { return false; }
  }

  function enPantallaDeAcceso() {
    return window.location.pathname.replace(/\/+$/, "") === RUTA_ACCESO;
  }

  function vencimiento() {
    return ultimaActividad + CONFIG.inactividadMs;
  }

  // ==========================================================
  // Aviso en pantalla
  // ==========================================================

  var ESTILOS_CAJA =
    "box-sizing:border-box;position:fixed;z-index:99999;right:20px;bottom:20px;" +
    "max-width:340px;padding:14px 16px;border-radius:12px;" +
    "font-family:'Montserrat','Segoe UI',system-ui,sans-serif;font-size:13px;line-height:1.45;" +
    "box-shadow:0 12px 32px rgba(15,35,22,.18);";

  function nuevaCaja(fondo, tinta, borde) {
    var div = document.createElement("div");
    div.setAttribute("role", "status");
    div.setAttribute("aria-live", "polite");
    div.style.cssText = ESTILOS_CAJA + "background:" + fondo + ";color:" + tinta +
      ";border:1px solid " + borde + ";";
    return div;
  }

  function quitarCaja() {
    if (tictac) { clearInterval(tictac); tictac = null; }
    if (escondite) { clearTimeout(escondite); escondite = null; }
    if (caja && caja.parentNode) caja.parentNode.removeChild(caja);
    caja = null;
  }

  function avisoDeInactividadVisible() {
    return caja && caja.dataset.motivo === "inactividad";
  }

  function mostrarMensaje(mensaje) {
    quitarCaja();
    caja = nuevaCaja("#e4f1dc", "#256d00", "#cfe3c5");
    var texto = document.createElement("div");
    texto.textContent = mensaje;
    caja.appendChild(texto);
    document.body.appendChild(caja);
    escondite = setTimeout(quitarCaja, 8000);
  }

  function etiquetaRestante(segundos) {
    return segundos >= 60 ? Math.ceil(segundos / 60) + " min" : segundos + " s";
  }

  function mostrarAvisoDeInactividad() {
    if (avisoDeInactividadVisible()) return;
    quitarCaja();

    caja = nuevaCaja("#fff8e1", "#7a5c00", "#f0d68a");
    caja.dataset.motivo = "inactividad";

    var titulo = document.createElement("strong");
    titulo.textContent = "Tu sesión va a cerrarse";

    var detalle = document.createElement("div");
    detalle.style.marginTop = "4px";

    var boton = document.createElement("button");
    boton.type = "button";
    boton.textContent = "Seguir activo";
    boton.style.cssText = "margin-top:12px;padding:8px 14px;border:0;border-radius:8px;" +
      "background:#3baa01;color:#fff;font:inherit;font-weight:700;cursor:pointer;";
    // No se enfoca al aparecer: quitaría el cursor del formulario abierto.
    boton.addEventListener("click", function () {
      ultimaActividad = Date.now();
      quitarCaja();
    });

    caja.appendChild(titulo);
    caja.appendChild(detalle);
    caja.appendChild(boton);
    document.body.appendChild(caja);

    function refrescar() {
      var segundos = Math.max(0, Math.ceil((vencimiento() - Date.now()) / 1000));
      detalle.textContent = "Quedan " + etiquetaRestante(segundos) +
        " por inactividad. Guarda lo que estés escribiendo.";
      if (segundos <= 0) revisar();
    }

    refrescar();
    tictac = setInterval(refrescar, 1000);
  }

  // ==========================================================
  // Control del plazo
  // ==========================================================

  function registrarActividad() {
    var ahora = Date.now();
    if (ahora - ultimaActividad < CONFIG.actividadMinMs) return;
    ultimaActividad = ahora;
    if (avisoDeInactividadVisible()) quitarCaja();
  }

  function cerrar(motivo) {
    if (cerrando) return;
    cerrando = true;

    clearInterval(reloj);
    reloj = null;
    quitarCaja();

    for (var i = 0; i < CLAVES_SESION.length; i++) {
      try { localStorage.removeItem(CLAVES_SESION[i]); } catch (_) { /* sin almacenamiento */ }
    }

    var mensaje = MENSAJES[motivo] || MENSAJES.inactividad;
    try { sessionStorage.setItem(CLAVE_AVISO, mensaje); } catch (_) { /* sin almacenamiento */ }

    if (enPantallaDeAcceso()) {
      // Ya se está en la pantalla de acceso: se muestra el aviso sin recargar.
      cerrando = false;
      mostrarAvisoPendiente();
      return;
    }

    // replace, y no href: con "atrás" no se vuelve a una pantalla muerta.
    window.location.replace(RUTA_ACCESO);
  }

  function revisar() {
    if (cerrando) return;

    if (!haySesion()) {
      // Pantalla pública o sesión ya cerrada: no hay nada que vigilar.
      if (vigilando) {
        vigilando = false;
        quitarCaja();
      }
      return;
    }

    // Recién apareció el token, por un inicio de sesión en esta pantalla.
    if (!vigilando) {
      vigilando = true;
      ultimaActividad = Date.now();
    }

    var restante = vencimiento() - Date.now();
    if (restante <= 0) {
      cerrar("inactividad");
      return;
    }
    if (restante <= CONFIG.avisoMs) {
      mostrarAvisoDeInactividad();
      return;
    }
    if (avisoDeInactividadVisible()) quitarCaja();
  }

  function alCambiarEnOtraPestana(evento) {
    if (cerrando) return;

    // Un localStorage.clear() desde otra pantalla llega con key null.
    if (evento.key === null) {
      if (!haySesion()) cerrar("otraPestana");
      return;
    }
    if (evento.key !== CLAVE_TOKEN) return;

    if (evento.newValue) {
      vigilando = false;        // sesión nueva: el plazo vuelve a empezar
      revisar();
    } else {
      cerrar("otraPestana");
    }
  }

  function mostrarAvisoPendiente() {
    var mensaje = null;
    try {
      mensaje = sessionStorage.getItem(CLAVE_AVISO);
      sessionStorage.removeItem(CLAVE_AVISO);
    } catch (_) { return; }
    if (mensaje) mostrarMensaje(mensaje);
  }

  // ==========================================================
  // Arranque
  // ==========================================================

  EVENTOS_ACTIVIDAD.forEach(function (nombre) {
    document.addEventListener(nombre, registrarActividad, true);
  });

  document.addEventListener("visibilitychange", function () {
    // Volver de una pestaña dormida: se comprueba el plazo real, no se renueva.
    if (!document.hidden) revisar();
  });

  window.addEventListener("storage", alCambiarEnOtraPestana);

  reloj = setInterval(revisar, CONFIG.revisionMs);

  mostrarAvisoPendiente();
  revisar();
})();
