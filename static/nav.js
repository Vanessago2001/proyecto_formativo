/* ==========================================================
   Navegación común de CertiSENA

   Solo toca la barra superior y los menús; no cambia la lógica
   de ninguna pantalla.

   1. "Panel" lleva al panel que corresponde al rol:
        Empresa -> /empresa   Comité -> /comite   Auditor -> /auditor
        los demás -> /dashboard
      Si ese panel es la pantalla actual, el enlace se oculta.
   2. En la pantalla de perfil no se muestra el enlace al perfil
      de la barra superior.
   3. En el resto, ese enlace se muestra como un icono.
   4. El menú lateral es el mismo en todas las pantallas del rol
      (administración, auditor y comité): un acordeón por grupos.
   5. La consulta pública de certificados (/verificar-certificado)
      lleva la misma cabecera que las demás consultas públicas.
   ========================================================== */
(function () {
  "use strict";

  var ICONO_PERFIL =
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"' +
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"' +
    ' focusable="false" style="vertical-align:middle">' +
    '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>' +
    '<circle cx="12" cy="7" r="4"></circle></svg>';

  // El botón "Cerrar sesión" de la cabecera común funciona en todas las
  // pantallas, sin depender de que cada vista tenga su propio manejador.
  document.addEventListener("click", function (evento) {
    var boton = evento.target.closest(".js-salir");
    if (!boton) return;
    evento.preventDefault();
    localStorage.clear();
    window.location.href = "/login";
  });

  function rolDelUsuario() {
    try {
      var token = localStorage.getItem("access_token");
      if (!token) return "";
      var parte = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      var datos = JSON.parse(decodeURIComponent(atob(parte).split("").map(function (c) {
        return "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2);
      }).join("")));
      return String(datos.role_name || datos.rol || "")
        .normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    } catch (_) {
      return "";
    }
  }

  // Nombre del rol tal como está en la sesión (para mostrarlo).
  function nombreRolSesion() {
    try {
      var token = localStorage.getItem("access_token");
      if (!token) return "";
      var parte = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      var datos = JSON.parse(decodeURIComponent(atob(parte).split("").map(function (c) {
        return "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2);
      }).join("")));
      var nombre = String(datos.role_name || datos.rol || "").trim();
      // Nombre vigente del rol mientras la base termina el cambio de nombre.
      return /^administrador$/i.test(nombre) ? "Coordinador" : nombre;
    } catch (_) {
      return "";
    }
  }

  function panelDelRol(rol) {
    if (/empresa/.test(rol)) return "/empresa";
    if (/comite/.test(rol)) return "/comite";
    if (/auditor/.test(rol) && !/administrar/.test(rol)) return "/auditor";
    return "/dashboard";
  }

  function rutaActual() {
    return window.location.pathname.replace(/\/$/, "") || "/";
  }

  function enLaMismaPagina(ruta) {
    return rutaActual() === (ruta.replace(/\/$/, "") || "/");
  }

  function ajustarEnlacesAlPanel(panel) {
    if (panel === "/dashboard") return;
    document.querySelectorAll('a[href="/dashboard"]').forEach(function (enlace) {
      if (enLaMismaPagina(panel)) {        // el panel es esta misma pantalla
        enlace.style.display = "none";
        return;
      }
      enlace.setAttribute("href", panel);
      if (/dashboard/i.test(enlace.textContent)) {
        enlace.textContent = enlace.textContent.replace(/dashboard/i, "panel");
      }
    });
  }

  function ajustarEnlacesDePerfil() {
    var enPerfil = enLaMismaPagina("/profile");
    document.querySelectorAll('a[href="/profile"]').forEach(function (enlace) {
      // El menú lateral común no cambia de una pantalla a otra.
      if (enlace.closest(".menu-acordeon")) return;
      if (enPerfil) {                      // ya estamos en el perfil: sobra el enlace
        enlace.style.display = "none";
        return;
      }
      // Fuera de la barra superior (menus laterales) se conserva el texto.
      if (!enlace.closest("header")) return;
      if (enlace.querySelector("svg")) return;

      var avatar = enlace.querySelector(".avatar") || enlace.classList.contains("profile-icon");
      if (avatar) {
        // El avatar ya es el icono: se oculta solo la palabra que lo acompana.
        enlace.querySelectorAll(".profile-label").forEach(function (etiqueta) {
          etiqueta.style.display = "none";
        });
        return;
      }

      var texto = (enlace.textContent || "").trim();
      if (!texto) return;
      var encabezado = enlace.closest("header");
      // Si la cabecera ya muestra el avatar, este enlace de texto sobra.
      if (encabezado && encabezado.querySelector(".profile-icon, .avatar")) {
        enlace.style.display = "none";
        return;
      }
      enlace.setAttribute("title", texto);
      enlace.setAttribute("aria-label", texto);
      enlace.innerHTML = ICONO_PERFIL;
    });
  }

  function ajustarCabeceraAuditor() {
    var encabezado = document.querySelector("header.login-header");
    if (!encabezado) return;

    var subtitulo = encabezado.querySelector(".subtitle");
    if (subtitulo) subtitulo.textContent = "Portal de auditoría";

    var contenido = encabezado.querySelector(".header-content");
    if (!contenido) return;

    var acciones = encabezado.querySelector(".comite-header-user");
    if (!acciones) {
      acciones = document.createElement("div");
      acciones.className = "comite-header-user";
      contenido.appendChild(acciones);
    }

    var panel = encabezado.querySelector(".comite-back-button") ||
      encabezado.querySelector('a[href="/dashboard"], a[href="/auditor"]');
    if (!panel) panel = document.createElement("a");
    panel.className = "comite-back-button";
    panel.href = "/auditor";
    panel.textContent = "Panel";
    panel.style.display = "";

    var perfil = encabezado.querySelector(".profile-link") ||
      encabezado.querySelector('a[href="/profile"], a[href="/perfil-auditor"]');
    if (!perfil) perfil = document.createElement("a");
    perfil.className = "profile-link";
    perfil.href = "/perfil-auditor";
    perfil.textContent = "Mi perfil";
    perfil.style.display = "";

    var salir = acciones.querySelector(".comite-logout, #logoutButton") ||
      encabezado.querySelector(".comite-logout, #logoutButton");
    if (!salir) {
      salir = document.createElement("button");
      salir.type = "button";
      salir.className = "comite-logout js-salir";
    }
    salir.textContent = "Cerrar sesión";

    acciones.replaceChildren(panel, perfil, salir);
  }


  /* ----------------------------------------------------------
     Acceso del auditor (17/11/2026).

     "Si el auditor está en revisión o no está aprobado como auditor,
     no se le debe permitir ver el resto de acciones o módulos a los
     que los auditores tienen acceso, solo a su proceso mientras se
     le aprueba."

     GET /auditores/mi-acceso dice si el registro está aprobado
     (misma regla que la asignación: postulación Aprobado y
     estado_auditor 'Activo'). La respuesta se guarda un momento en
     sessionStorage para no consultarla en cada pantalla; mientras no
     se sabe, el menú muestra solo el proceso de registro. El backend
     responde 403 en los módulos restringidos (require_auditor_aprobado):
     esto solo ordena la interfaz.
     ---------------------------------------------------------- */
  var CLAVE_ACCESO_AUDITOR = "certisena.accesoAuditor";
  var VIGENCIA_ACCESO_MS = 20000;          // refresco breve: al aprobarlo se nota enseguida
  var AVISO_REGISTRO_EN_REVISION =
    "Tu registro está en revisión: cuando seas aprobado verás el resto de módulos";
  // Pantallas que un auditor sin registro aprobado no puede abrir.
  var RUTAS_SOLO_AUDITOR_APROBADO = [
    "/conflictos-auditor",
    "/empresas-restringidas",
    "/consultar-auditorias-programadas",
    "/programaciones-futuras-auditor",
    "/consultar-agenda-auditor",
    "/disponibilidad-auditor",
    // El catálogo de competencias sí lo usa el auditor no aprobado: puede
    // registrar sus certificaciones vigentes durante el registro (17/11/2026).
    "/reportes",
    "/pqrs-gestion"
  ];
  var accesoAuditor = { conocido: false, aprobado: false };
  var oyentesAcceso = [];

  function usuarioDeLaSesion() {
    try {
      var token = localStorage.getItem("access_token");
      if (!token) return "";
      var datos = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
      return String(datos.user_id || datos.sub || "");
    } catch (_) {
      return "";
    }
  }

  function leerAccesoGuardado() {
    try {
      var guardado = JSON.parse(sessionStorage.getItem(CLAVE_ACCESO_AUDITOR) || "null");
      if (guardado && guardado.usuario && guardado.usuario === usuarioDeLaSesion()) return guardado;
    } catch (_) {}
    return null;
  }

  function guardarAcceso(datos) {
    try {
      sessionStorage.setItem(CLAVE_ACCESO_AUDITOR, JSON.stringify({
        usuario: usuarioDeLaSesion(),
        aprobado: datos.aprobado === true,
        estado_postulacion: datos.estado_postulacion || null,
        estado_auditor: datos.estado_auditor || null,
        t: Date.now()
      }));
    } catch (_) {}
  }

  function fijarAcceso(aprobado) {
    accesoAuditor.conocido = true;
    accesoAuditor.aprobado = aprobado === true;
    oyentesAcceso.forEach(function (oyente) {
      try { oyente(accesoAuditor.aprobado); } catch (_) {}
    });
  }

  function esRutaSoloAprobado() {
    var ruta = rutaActual();
    return RUTAS_SOLO_AUDITOR_APROBADO.some(function (r) { return ruta === r || ruta.indexOf(r + "/") === 0; });
  }

  // Si un auditor no aprobado abre una pantalla restringida (escribiendo
  // la dirección), se le lleva a "Consultar estado del registro".
  function llevarAlEstadoDelRegistro() {
    window.location.replace("/consultar-estado");
  }

  function mostrarPagina() {
    document.documentElement.style.removeProperty("visibility");
  }

  function iniciarAccesoAuditor() {
    var restringida = esRutaSoloAprobado();
    var guardado = leerAccesoGuardado();
    if (guardado) {
      accesoAuditor.conocido = true;
      accesoAuditor.aprobado = guardado.aprobado === true;
    }
    if (restringida && guardado && !guardado.aprobado) {
      llevarAlEstadoDelRegistro();
      return;
    }
    if (restringida && !guardado) {
      // No se sabe aún: la pantalla no se muestra hasta saberlo.
      document.documentElement.style.visibility = "hidden";
    }
    if (guardado && Date.now() - (guardado.t || 0) < VIGENCIA_ACCESO_MS) return;

    var token = null;
    try { token = localStorage.getItem("access_token"); } catch (_) {}
    if (!token || !window.fetch) { mostrarPagina(); return; }
    fetch("/auditores/mi-acceso", { headers: { Authorization: "Bearer " + token }, cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (datos) {
        if (!datos) { mostrarPagina(); return; }    // sin respuesta: el menú sigue reducido
        guardarAcceso(datos);
        if (restringida && datos.aprobado !== true) { llevarAlEstadoDelRegistro(); return; }
        mostrarPagina();
        fijarAcceso(datos.aprobado === true);
      })
      .catch(mostrarPagina);
  }


  /* ----------------------------------------------------------
     Permisos del Auxiliar (18/11/2026).

     "Los permisos del auxiliar deben ser puestos exclusivamente por
     el Coordinador." El Auxiliar no tiene permisos propios: solo ve
     los módulos, opciones y botones cuyos códigos el Coordinador le
     otorgó en "Permisos de auxiliares".

     GET /api/permisos-auxiliar/mios da sus códigos vigentes; se
     guardan un momento en sessionStorage (dentro de try/catch) para
     no consultarlos en cada pantalla. Mientras no se saben, lo que
     depende de un permiso queda oculto.

       · Menú: cada opción declara `permisos` (basta uno).
       · Pantallas: todo elemento con data-permiso-aux="SOL-047 SOL-048"
         se oculta al Auxiliar que no tiene ninguno de esos códigos
         (también los que la pantalla dibuja después).
       · window.CertiPermisos: para las pantallas que lo necesiten.

     El backend responde 403 sin el permiso: esto solo ordena la
     interfaz.
     ---------------------------------------------------------- */
  var CLAVE_PERMISOS_AUXILIAR = "certisena.permisosAuxiliar";
  var VIGENCIA_PERMISOS_MS = 30000;
  var AVISO_SIN_PERMISOS = "Aún no tienes permisos asignados. El Coordinador puede otorgártelos.";
  var permisosAuxiliar = { conocido: false, codigos: [] };
  var oyentesPermisos = [];

  function esSesionAuxiliar() {
    return tipoDeRol(rolDelUsuario()) === "auxiliar";
  }

  function leerPermisosGuardados() {
    try {
      var guardado = JSON.parse(sessionStorage.getItem(CLAVE_PERMISOS_AUXILIAR) || "null");
      if (guardado && guardado.usuario && guardado.usuario === usuarioDeLaSesion() && Array.isArray(guardado.codigos)) {
        return guardado;
      }
    } catch (_) {}
    return null;
  }

  function guardarPermisos(codigos) {
    try {
      sessionStorage.setItem(CLAVE_PERMISOS_AUXILIAR, JSON.stringify({
        usuario: usuarioDeLaSesion(),
        codigos: codigos,
        t: Date.now()
      }));
    } catch (_) {}
  }

  function tienePermisoAuxiliar(lista) {
    if (!lista || !lista.length) return true;
    if (!permisosAuxiliar.conocido) return false;
    return lista.some(function (codigo) { return permisosAuxiliar.codigos.indexOf(codigo) !== -1; });
  }

  function listaDePermisos(texto) {
    return String(texto || "").toUpperCase().split(/[\s,]+/).filter(Boolean);
  }

  // Oculta (o vuelve a mostrar) los elementos con data-permiso-aux.
  function aplicarPermisosEnPagina() {
    if (!esSesionAuxiliar() || !document.body) return;
    document.querySelectorAll("[data-permiso-aux]").forEach(function (elemento) {
      var ocultar = !tienePermisoAuxiliar(listaDePermisos(elemento.getAttribute("data-permiso-aux")));
      if (elemento.classList.contains("ma-sin-permiso") !== ocultar) elemento.classList.toggle("ma-sin-permiso", ocultar);
    });
  }

  function fijarPermisos(codigos) {
    permisosAuxiliar.conocido = true;
    permisosAuxiliar.codigos = (codigos || []).map(function (c) { return String(c).toUpperCase(); });
    aplicarPermisosEnPagina();
    oyentesPermisos.forEach(function (oyente) {
      try { oyente(permisosAuxiliar.codigos.slice()); } catch (_) {}
    });
  }

  function iniciarPermisosAuxiliar() {
    if (!document.getElementById("permisos-auxiliar-estilos")) {
      var estilo = document.createElement("style");
      estilo.id = "permisos-auxiliar-estilos";
      estilo.textContent = ".ma-sin-permiso{display:none !important}";
      (document.head || document.documentElement).appendChild(estilo);
    }
    var guardado = leerPermisosGuardados();
    if (guardado) fijarPermisos(guardado.codigos);
    if (guardado && Date.now() - (guardado.t || 0) < VIGENCIA_PERMISOS_MS) return;

    var token = null;
    try { token = localStorage.getItem("access_token"); } catch (_) {}
    if (!token || !window.fetch) { if (!guardado) fijarPermisos([]); return; }
    fetch("/api/permisos-auxiliar/mios", { headers: { Authorization: "Bearer " + token }, cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (datos) {
        if (!datos || !Array.isArray(datos.codigos)) { if (!guardado) fijarPermisos([]); return; }
        guardarPermisos(datos.codigos);
        fijarPermisos(datos.codigos);
      })
      .catch(function () { if (!guardado) fijarPermisos([]); });
  }

  // Los elementos que la pantalla dibuja después también se revisan.
  function vigilarPermisosEnPagina() {
    if (!window.MutationObserver || !document.body) return;
    var pendiente = null;
    new MutationObserver(function () {
      if (pendiente) return;
      pendiente = window.setTimeout(function () { pendiente = null; aplicarPermisosEnPagina(); }, 30);
    }).observe(document.body, { childList: true, subtree: true });
  }

  window.CertiPermisos = {
    esAuxiliar: esSesionAuxiliar,
    conocido: function () { return !esSesionAuxiliar() || permisosAuxiliar.conocido; },
    // Para los demás roles siempre true: su acceso lo decide su rol.
    tiene: function (codigo) { return !esSesionAuxiliar() || tienePermisoAuxiliar([String(codigo || "").toUpperCase()]); },
    tieneAlguno: function (lista) { return !esSesionAuxiliar() || tienePermisoAuxiliar(listaDePermisos([].concat(lista || []).join(" "))); },
    alCambiar: function (oyente) {
      oyentesPermisos.push(oyente);
      if (permisosAuxiliar.conocido) { try { oyente(permisosAuxiliar.codigos.slice()); } catch (_) {} }
    }
  };

  // Panel del Auxiliar (/dashboard): sin permisos, el aviso; con permisos,
  // los módulos que el Coordinador le habilitó.
  function ajustarPanelAuxiliar() {
    if (!esSesionAuxiliar() || !enLaMismaPagina("/dashboard") || !permisosAuxiliar.conocido) return;
    var caja = document.getElementById("regularView");
    if (!caja) return;
    var titulo = caja.querySelector("h3");
    var texto = caja.querySelector("p");
    var lista = document.getElementById("ma-modulos-auxiliar");
    if (!lista && texto) {
      lista = document.createElement("ul");
      lista.id = "ma-modulos-auxiliar";
      lista.style.cssText = "margin:14px 0 0;padding-left:18px;line-height:1.9";
      texto.parentNode.insertBefore(lista, texto.nextSibling);
    }
    if (titulo) titulo.textContent = "Panel del auxiliar";
    var modulos = modulosDelAuxiliar();
    if (lista) lista.innerHTML = "";
    if (!modulos.length) {
      if (texto) {
        texto.textContent = AVISO_SIN_PERMISOS;
        texto.setAttribute("role", "status");
      }
      if (lista) lista.hidden = true;
      return;
    }
    if (texto) texto.textContent = "El Coordinador te habilitó estos módulos:";
    if (!lista) return;
    lista.hidden = false;
    modulos.forEach(function (m) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = m.href;
      a.textContent = m.texto;
      li.appendChild(a);
      lista.appendChild(li);
    });
  }

  // Primer destino permitido de cada grupo del menú de administración.
  function modulosDelAuxiliar() {
    var modulos = [];
    MENU_ADMINISTRACION.items.forEach(function (item) {
      if (item.grupo) {
        if (item.permisos && !tienePermisoAuxiliar(item.permisos)) return;
        var primera = null;
        item.opciones.forEach(function (o) {
          if (!primera && (!o.solo || o.solo.indexOf("auxiliar") !== -1) && o.permisos && tienePermisoAuxiliar(o.permisos)) primera = o;
        });
        if (primera) modulos.push({ texto: item.grupo, href: primera.href });
      } else if (item.dinamico && item.permisos && tienePermisoAuxiliar(item.permisos)) {
        modulos.push({ texto: item.texto, href: item.href });
      }
    });
    return modulos;
  }


  /* ----------------------------------------------------------
     4. Menú lateral en acordeón, el mismo en todas las pantallas.

     Cada rol tiene un único menú con grupos. Pulsar un grupo solo
     despliega o pliega sus opciones; no navega. El grupo de la
     pantalla actual aparece abierto y solo una opción queda marcada.

     Muchas pantallas cambian de vista sin recargar (Empresas,
     Comité, Certificados, Apelaciones, Revisión de solicitudes,
     la agenda, el formulario del auditor...). Esas vistas son
     opciones del grupo: en la propia pantalla, la opción pulsa el
     botón original de la página (que queda oculto, con su lógica
     intacta); desde otra pantalla se navega con "#vista" y al
     cargar se abre esa vista.

     El menú original de la página no se borra: se oculta, porque
     sus botones y enlaces siguen siendo los que cambian de vista.

     Las opciones nunca llevan data-view, data-vista, data-seccion,
     data-filtro ni las clases de la página (comite-nav-link,
     vista-link): así el código de cada pantalla no las confunde con
     las suyas al marcar o recorrer su propio menú.

     Opción:   { texto, href, proxy?, solo? }
       proxy   selector del elemento original que abre la vista en
               esa pantalla; si en la pantalla no existe o está oculto
               (la pantalla no lo ofrece a ese rol), la opción no se ve.
       solo    roles ("admin", "auxiliar", "comite", "auditor") que
               ven la opción; sin él, todos los del menú.
       soloAprobado  (opción, grupo o dinámico del auditor) solo se ve
               cuando su registro como auditor está aprobado (ver
               "Acceso del auditor" más abajo).
       permisos  (opción, grupo o dinámico) códigos de la matriz; el
               Auxiliar la ve solo si el Coordinador le otorgó alguno
               (ver "Permisos del Auxiliar"). No afecta a otros roles.
     Grupo:    { grupo, opciones: [...] }
     Dinámico: { texto, href, dinamico: selector } — fuera de esa
               pantalla es un enlace; en ella, un grupo con los
               elementos que la página dibuje (catálogo de reportes).
     ---------------------------------------------------------- */

  var REPORTES = { texto: "Reportes", href: "/reportes", dinamico: "#listaReportes button[data-codigo]" };
  // Reportes de la hoja M12 que el Auxiliar puede recibir del Coordinador.
  var PERMISOS_REPORTES = ["REP-001", "REP-002", "REP-003", "REP-004", "REP-005", "REP-006", "REP-007", "REP-008", "REP-009", "REP-010"];
  var SALIR = { salir: true, texto: "Cerrar sesión" };

  // Módulo PQRS (static/pqrs_gestion.html): sus vistas son botones
  // button[data-view] y la página abre la vista del "#" al cargar.
  var GRUPO_PQRS = {
    grupo: "PQRS",
    opciones: [
      ["bandeja", "Bandeja de PQRS", ["PQR-003", "PQR-004", "PQR-010"]],
      ["tiempos", "Tiempos de atención", ["PQR-014"]],
      ["reportes", "Reportes", ["PQR-015"]]
    ].map(function (v) {
      return { texto: v[1], href: "/pqrs-gestion#" + v[0], proxy: 'button[data-view="' + v[0] + '"]', permisos: v[2] };
    })
  };

  var GRUPO_COMITE = function (titulo) {
    return {
      grupo: titulo,
      opciones: [
        // "Expedientes pendientes" e "Historial de decisiones" se unificaron:
        // una sola lista donde el filtro de estado decide qué se ve (el
        // Coordinador y el Auxiliar entran con "Todos los estados").
        { texto: "Expedientes", href: "/comite#expedientes", proxy: 'aside.comite-sidebar button[data-view="expedientes"]', permisos: ["COM-001", "COM-019"] },
        // Solo el líder asignado: la pantalla muestra el botón si lo es.
        { texto: "Pendientes de firma", href: "/comite#firmas", proxy: 'aside.comite-sidebar button[data-view="firmas"]', solo: ["comite"] }
      ]
    };
  };

  var GRUPO_CERTIFICADOS = {
    grupo: "Gestión de certificados",
    opciones: [
      { texto: "Certificados", href: "/gestion-certificados#catalogo", proxy: "#catalogNav", permisos: ["CER-011"] },
      { texto: "Vencimientos", href: "/gestion-certificados#vencimientos", proxy: "#alertsNav", solo: ["admin", "auxiliar"], permisos: ["CER-027"] },
      { texto: "Consulta pública", href: "/gestion-certificados#consulta", proxy: 'aside.comite-sidebar button[data-view="consulta"]', permisos: ["CER-011", "CER-024"] }
    ]
  };

  var GRUPO_APELACIONES = function (titulo) {
    function vista(clave, texto, solo) {
      return { texto: texto, href: "/apelacion#" + clave, proxy: '#vistaNav button[data-vista="' + clave + '"]', solo: solo, permisos: ["APE-004"] };
    }
    return {
      grupo: titulo,
      opciones: [
        // Todo lo de una apelación (expediente, comité, requerimientos y
        // decisión) está en su revisión, que se abre con "Revisar".
        vista("bandeja", "Bandeja del comité"),
        vista("porasignar", "Por asignar comité", ["admin", "auxiliar"])
      ]
    };
  };

  var PERMISOS_SOLICITUDES = ["SOL-006"];
  var PERMISOS_ASIGNACION = ["SOL-041", "SOL-042", "SOL-043", "SOL-044", "SOL-045", "SOL-046", "SOL-047"];

  var MENU_ADMINISTRACION = {
    titulo: "Administración",
    items: [
      // Usuarios es una sola opción: el panel (/dashboard) tiene las pestañas
      // Resumen, Gestionar usuarios y Permisos de auxiliares (esta última es
      // otra pantalla, por eso también queda marcada allí). El Auxiliar no
      // gestiona usuarios: para él la misma opción se llama "Resumen".
      { texto: "Usuarios", textoAuxiliar: "Resumen", href: "/dashboard", activoEn: /^\/permisos-auxiliar\/?$/ },
      {
        grupo: "Empresas",
        opciones: [
          { texto: "Registradas", href: "/empresas#listado", proxy: '#menu button[data-view="listado"]', permisos: ["EMP-003", "EMP-004", "EMP-005"] },
          { texto: "Registrar empresa", href: "/empresas#registrar", proxy: '#menu button[data-view="registrar"]', permisos: ["EMP-001"] }
          // "Aprobaciones" se quitó: no se usaba y se confundía con el
          // Historial de decisiones del Comité.
        ]
      },
      // "Revisión de solicitudes" y "Asignación de auditores" se unificaron
      // (18/11/2026) en una pantalla que sigue la solicitud por etapas
      // (static/solicitudes.html): cada opción pulsa su button[data-etapa].
      {
        grupo: "Solicitudes",
        // Etapas 1, 2 y "Todas": SOL-006 (consultar solicitudes); etapas 3 y 4
        // (asignación): SOL-041..SOL-047, igual que el backend.
        opciones: [
          ["radicadas", "Radicadas", PERMISOS_SOLICITUDES],
          ["revision", "En revisión", PERMISOS_SOLICITUDES],
          ["por-asignar", "Por asignar auditor", PERMISOS_ASIGNACION],
          ["con-auditores", "Con auditores", PERMISOS_ASIGNACION],
          ["todas", "Todas", PERMISOS_SOLICITUDES]
        ].map(function (e) {
          return { texto: e[1], href: "/solicitudes#" + e[0], proxy: 'button[data-etapa="' + e[0] + '"]', permisos: e[2] };
        })
      },
      {
        grupo: "Auditorías",
        opciones: [
          // La pantalla cambia de vista con la dirección (#listado o
          // #reprogramaciones). "Programaciones futuras" se quitó: repetía
          // la consulta general.
          { texto: "Programar una auditoría", href: "/consultar-agenda-auditor#schedule", proxy: '.agenda-menu a[data-seccion="schedule"]', permisos: ["AGE-021"] },
          { texto: "Consultar auditorías programadas", href: "/consultar-auditorias-programadas-admin#listado", permisos: ["AGE-026", "AGE-041"] },
          { texto: "Solicitudes de reprogramación", href: "/consultar-auditorias-programadas-admin#reprogramaciones", permisos: ["AGE-023", "AGE-030"] }
        ]
      },
      {
        grupo: "Consultar agenda de auditor",
        opciones: [
          // "Solicitudes con auditores asignados" se quitó: solo informaba y
          // eso ya está en Asignación de auditores (con "Programar visita").
          ["weekly", "Disponibilidad semanal", ["AGE-003", "AGE-010"]],
          // "Registrar fecha no disponible" se quitó (13/11/2026): las fechas
          // con auditorías programadas quedan bloqueadas por el backend y el
          // auditor declara su disponibilidad en su perfil.
          ["month", "Disponibilidad mensual y auditorías", ["AGE-010", "AGE-046"]]
          // "Historial de disponibilidad" y "Bitácora de validación" se
          // quitaron por pedido de la usuaria (13/11/2026).
        ].map(function (s) {
          return { texto: s[1], href: "/consultar-agenda-auditor#" + s[0], proxy: '.agenda-menu a[data-seccion="' + s[0] + '"]', permisos: s[2] };
        })
      },
      {
        grupo: "Banco de auditores",
        opciones: [
          { texto: "Banco de auditores", href: "/banco-auditores", activoEn: /^\/banco-auditores\/solicitud\//, permisos: ["AUD-011", "AUD-012"] },
          { texto: "Auditores registrados", href: "/auditores-registrados", permisos: ["AUD-056", "AUD-057", "AUD-058"] },
          { texto: "Conflictos de interés", href: "/conflictos-administrador", permisos: ["AUD-033", "AUD-035"] }
          // "Consultar empresas restringidas" es solo del auditor (sus propias
          // restricciones); el Coordinador las ve en Conflictos de interés.
        ]
      },
      GRUPO_CERTIFICADOS,
      GRUPO_APELACIONES("Apelaciones"),
      GRUPO_COMITE("Comité de certificación"),
      GRUPO_PQRS,
      { texto: REPORTES.texto, href: REPORTES.href, dinamico: REPORTES.dinamico, permisos: PERMISOS_REPORTES },
      { texto: "Mi perfil", href: "/profile" },
      { mfa: true },                       // en el panel abre la ventana; en las demás pantallas lleva al panel
      SALIR
    ]
  };

  var MENU_AUDITOR = {
    titulo: "Portal del auditor",
    items: [
      // Orden pedido por la usuaria (18/11/2026) para el auditor aprobado:
      // Notificaciones, Auditorías, Disponibilidad, Conflictos y restricciones,
      // Reportes, Mi registro y Catálogo de competencias. Al no aprobado solo
      // se le muestran Notificaciones, Mi registro, Catálogo y Mi perfil.
      { texto: "Notificaciones", href: "/notificaciones-auditor", insignia: "notifBadge" },
      {
        grupo: "Auditorías",
        soloAprobado: true,
        opciones: [
          // "Programaciones futuras" se eliminó: la ruta redirige a esta pantalla.
          { texto: "Consultar auditorías programadas", href: "/consultar-auditorias-programadas" }
        ]
      },
      {
        grupo: "Disponibilidad",
        soloAprobado: true,
        // El horario semanal lo configura el propio auditor en la pantalla de
        // Disponibilidad (no en el perfil), junto al calendario de sus
        // auditorías (static/mi_disponibilidad.js). 17/11/2026.
        opciones: [
          ["configurar-horario", "Mi disponibilidad semanal"],
          ["bloquear-fecha", "Bloquear fecha"],
          ["desbloquear-fecha", "Desbloquear fecha"],
          // "Disponibilidad extraordinaria" se quitó (17/11/2026): era lo mismo
          // que declarar la disponibilidad semanal con otra vigencia.
          ["historial-disponibilidad", "Historial"]
        ].map(function (s) {
          return { texto: s[1], href: "/disponibilidad-auditor#" + s[0], proxy: '.side a[data-seccion="' + s[0] + '"]' };
        })
      },
      {
        grupo: "Conflictos y restricciones",
        soloAprobado: true,
        opciones: [
          { texto: "Consultar conflictos registrados", href: "/conflictos-auditor" },
          { texto: "Consultar empresas restringidas", href: "/empresas-restringidas" }
        ]
      },
      { texto: REPORTES.texto, href: REPORTES.href, dinamico: REPORTES.dinamico, soloAprobado: true },
      {
        grupo: "Mi registro",
        opciones: [
          ["inicioRegistro", "Formulario de registro"],
          ["datos-personales", "Datos personales"],
          ["perfil", "Perfil Auditor"],
          ["competencias", "Competencias"],
          ["formacion", "Formación académica"],
          ["experiencia-laboral", "Experiencia laboral"],
          ["experiencia-auditoria", "Experiencia en auditoría"],
          ["documentos-soporte", "Documentos de soporte"],
          ["conflictos", "Conflictos de interés"],
          ["historial-academico", "Historial académico"]
        ].map(function (s) {
          return { texto: s[1], href: "/auditor#" + s[0], proxy: '.side a[data-seccion="' + s[0] + '"]' };
        }).concat([{ texto: "Consultar estado del registro", href: "/consultar-estado" }])
      },
      {
        grupo: "Catálogo de competencias",
        opciones: [
          { texto: "Competencias registradas", href: "/catalogo-competencias-auditor#vistaCompetencias", proxy: '.side a[data-vista="competencias"]' },
          { texto: "Registrar certificaciones vigentes", href: "/catalogo-competencias-auditor#vistaCertificaciones", proxy: '.side a[data-vista="certificaciones"]' }
        ]
      },
      { texto: "Mi perfil", href: "/perfil-auditor" },
      SALIR
    ]
  };

  var MENU_COMITE = {
    titulo: "Comité de certificación",
    items: [
      GRUPO_COMITE("Comité de certificación"),
      // "Gestión de certificados" se quitó del Comité (18/11/2026): el líder
      // firma sus certificados en /comite ("Pendientes de firma" y la fila
      // del expediente). /gestion-certificados lo redirige a /comite.
      GRUPO_APELACIONES("Apelaciones asignadas"),
      REPORTES,
      { texto: "Mi perfil", href: "/profile" },
      SALIR
    ]
  };

  // Menús propios de cada pantalla que quedan cubiertos por el lateral.
  var MENUS_INTERNOS = {
    "/apelacion": ["#vistaNav"]
  };

  function tipoDeRol(rol) {
    if (/auxiliar/.test(rol)) return "auxiliar";
    if (/admin|coordinador/.test(rol)) return "admin";
    if (/comite/.test(rol)) return "comite";
    if (/auditor/.test(rol)) return "auditor";
    return "";
  }

  function menuDelRol(tipo) {
    if (tipo === "admin" || tipo === "auxiliar") return MENU_ADMINISTRACION;
    if (tipo === "auditor") return MENU_AUDITOR;
    if (tipo === "comite") return MENU_COMITE;
    return null;                          // la empresa tiene su propio portal
  }

  var ESTILOS = [
    ".ma-oculto{display:none !important}",
    ".ma-host{grid-template-columns:minmax(0,1fr) !important}",
    ".ma-sin-lateral{grid-template-columns:minmax(0,1fr) !important}",
    "nav.menu-acordeon{display:block !important;padding:0 !important;margin:0;gap:0;border:0;background:transparent;font-family:inherit}",
    "nav.menu-acordeon .ma-encabezado{display:flex;flex-direction:column;gap:3px;padding:10px 12px 14px;margin-bottom:6px;" +
      "border-bottom:1px solid #e2e8f0;color:#1f2937;font-weight:700;font-size:14px;line-height:1.3}",
    "nav.menu-acordeon .ma-encabezado span{color:#64748b;font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}",
    "nav.menu-acordeon a.ma-enlace,nav.menu-acordeon button.ma-grupo-boton{all:unset;box-sizing:border-box;display:flex;" +
      "align-items:center;justify-content:space-between;gap:8px;width:100%;margin:0;padding:11px 12px;color:#334155;" +
      "background:transparent;font-family:inherit;font-size:13px;font-weight:400;line-height:1.35;text-align:left;" +
      "text-decoration:none;border-left:3px solid transparent;border-radius:0;cursor:pointer}",
    "nav.menu-acordeon a.ma-enlace:hover,nav.menu-acordeon button.ma-grupo-boton:hover,nav.menu-acordeon a.ma-enlace.ma-activo{" +
      "background:#f1f5f9;color:#256d00;border-left-color:#3baa01;font-weight:700}",
    "nav.menu-acordeon .ma-grupo-actual>button.ma-grupo-boton{color:#256d00;font-weight:700}",
    "nav.menu-acordeon a.ma-enlace:focus-visible,nav.menu-acordeon button.ma-grupo-boton:focus-visible{outline:2px solid #3baa01;outline-offset:-2px}",
    "nav.menu-acordeon .ma-flecha{flex:none;width:7px;height:7px;border-right:2px solid currentColor;border-bottom:2px solid currentColor;" +
      "transform:rotate(45deg);margin:0 4px 3px 0;transition:transform .15s ease}",
    "nav.menu-acordeon button.ma-grupo-boton[aria-expanded=\"true\"] .ma-flecha{transform:rotate(-135deg);margin-bottom:-3px}",
    "nav.menu-acordeon .ma-opciones{margin:0 0 4px;padding:0}",
    "nav.menu-acordeon .ma-opciones[hidden]{display:none}",
    "nav.menu-acordeon .ma-opciones a.ma-enlace{padding:9px 12px 9px 26px;font-size:12.5px}",
    "nav.menu-acordeon .ma-vacio{display:block;padding:9px 12px 9px 26px;font-size:12.5px;color:#64748b}",
    "nav.menu-acordeon .ma-aviso::after{content:\"\";flex:none;width:8px;height:8px;border-radius:50%;background:#dc2626;margin-left:auto}",
    "nav.menu-acordeon a.ma-enlace[hidden],nav.menu-acordeon .ma-grupo[hidden]{display:none}",
    "nav.menu-acordeon .ma-nota-registro{margin:0 8px 8px;padding:9px 10px;border-radius:6px;background:#fff7ed;" +
      "border:1px solid #fed7aa;color:#9a3412;font-size:12px;line-height:1.4}",
    "nav.menu-acordeon .ma-nota-registro[hidden]{display:none}"
  ].join("\n");

  function ponerEstilos() {
    if (document.getElementById("menu-acordeon-estilos")) return;
    var estilo = document.createElement("style");
    estilo.id = "menu-acordeon-estilos";
    estilo.textContent = ESTILOS;
    document.head.appendChild(estilo);
  }

  // Busca el elemento original de la página, nunca uno del menú común.
  function buscarOriginal(selector) {
    var lista = document.querySelectorAll(selector);
    for (var i = 0; i < lista.length; i++) {
      if (!lista[i].closest(".menu-acordeon")) return lista[i];
    }
    return null;
  }

  function estaOculto(elemento) {
    return elemento.hidden || elemento.style.display === "none" || elemento.classList.contains("ma-sin-permiso");
  }

  function estaActivo(elemento) {
    return elemento.classList.contains("active") || elemento.classList.contains("activa") ||
      elemento.getAttribute("aria-current") === "page" || elemento.getAttribute("aria-selected") === "true";
  }

  function partirHref(href) {
    var partes = href.split("#");
    return { ruta: partes[0], hash: partes[1] || "" };
  }

  // Dónde va el menú: la columna lateral que cada pantalla ya tiene.
  function anfitrionDelMenu() {
    var aside = document.querySelector("aside.comite-sidebar");
    if (aside) return { caja: aside, tipo: "aside" };
    var nav = document.querySelector("nav.admin-nav, nav.side, nav.module-menu, aside.sidebar nav");
    if (nav) return { caja: nav, tipo: "nav" };
    return null;
  }

  function crearMenuAcordeon(menu, tipo) {
    var anfitrion = anfitrionDelMenu();
    if (!anfitrion) return;
    ponerEstilos();

    var caja = anfitrion.caja;
    var raiz = document.createElement("nav");
    raiz.className = "menu-acordeon";
    raiz.setAttribute("aria-label", "Menú principal");

    if (anfitrion.tipo === "aside") {
      // La columna conserva la nota de permisos; el encabezado y la lista
      // de la página se ocultan, sin borrarlos.
      Array.prototype.forEach.call(caja.children, function (hijo) {
        if (hijo.matches(".comite-sidebar-heading, nav")) hijo.classList.add("ma-oculto");
      });
      caja.insertBefore(raiz, caja.firstChild);
    } else {
      // Los enlaces originales se guardan ocultos dentro de la misma
      // columna: el código de la página sigue encontrándolos ahí.
      var guardados = document.createElement("div");
      guardados.className = "ma-original ma-oculto";
      while (caja.firstChild) guardados.appendChild(caja.firstChild);
      caja.appendChild(raiz);
      caja.appendChild(guardados);
    }
    caja.classList.add("ma-host");

    // Recuadro "Rol: ..." al final del menú, igual en todas las pantallas.
    // Si la página ya trae el suyo (columnas con nota de permisos) se deja ese.
    var notaPropia = Array.prototype.some.call(caja.querySelectorAll(".comite-access-note"), function (n) {
      return !n.closest(".ma-oculto");
    });
    var nombreRol = nombreRolSesion();
    if (!notaPropia && nombreRol) {
      var nota = document.createElement("div");
      nota.className = "comite-access-note ma-nota-rol";
      var etiqueta = document.createElement("span");
      etiqueta.textContent = "Rol: " + nombreRol;
      nota.appendChild(etiqueta);
      raiz.parentNode.insertBefore(nota, raiz.nextSibling);
    }

    (MENUS_INTERNOS[rutaActual()] || []).forEach(function (selector) {
      document.querySelectorAll(selector).forEach(function (elemento) {
        elemento.classList.add("ma-oculto");
      });
    });

    var encabezado = document.createElement("div");
    encabezado.className = "ma-encabezado";
    var kicker = document.createElement("span");
    kicker.textContent = menu.titulo;
    var tituloModulo = document.createElement("strong");
    tituloModulo.style.fontWeight = "inherit";
    encabezado.appendChild(kicker);
    encabezado.appendChild(tituloModulo);
    raiz.appendChild(encabezado);

    // Auditor sin registro aprobado: solo su proceso, con este aviso.
    function accesoCompleto() {
      return tipo !== "auditor" || accesoAuditor.aprobado === true;
    }
    var notaRegistro = null;
    if (tipo === "auditor") {
      notaRegistro = document.createElement("div");
      notaRegistro.className = "ma-nota-registro";
      notaRegistro.setAttribute("role", "status");
      notaRegistro.textContent = AVISO_REGISTRO_EN_REVISION;
      notaRegistro.hidden = accesoCompleto() || !accesoAuditor.conocido;
      raiz.appendChild(notaRegistro);
    }
    // Auxiliar sin ningún permiso delegado: aviso en el menú.
    var notaPermisos = null;
    if (tipo === "auxiliar") {
      notaPermisos = document.createElement("div");
      notaPermisos.className = "ma-nota-registro";
      notaPermisos.setAttribute("role", "status");
      notaPermisos.textContent = AVISO_SIN_PERMISOS;
      notaPermisos.hidden = !permisosAuxiliar.conocido || permisosAuxiliar.codigos.length > 0;
      raiz.appendChild(notaPermisos);
    }
    function conPermiso(opcion, grupo) {
      if (tipo !== "auxiliar") return true;
      var item = grupo ? grupo.item : null;
      if (item && item.permisos && !tienePermisoAuxiliar(item.permisos)) return false;
      return tienePermisoAuxiliar(opcion.permisos);
    }
    var cargasPendientes = [];          // catálogo de reportes, al aprobarse
    var cargasPermiso = [];             // catálogo de reportes del Auxiliar, con permiso

    var opciones = [];        // { a, opcion, grupo }
    var grupos = [];          // { caja, boton, lista, item, dinamico, firma }
    var contador = 0;

    function permitida(opcion) {
      return !opcion.solo || opcion.solo.indexOf(tipo) !== -1;
    }

    function crearEnlace(opcion, grupo) {
      var a = document.createElement("a");
      a.className = "ma-enlace";
      a.setAttribute("href", opcion.href);
      var texto = (tipo === "auxiliar" && opcion.textoAuxiliar) || opcion.texto;
      a.appendChild(document.createTextNode(texto));
      var destino = partirHref(opcion.href);
      a.addEventListener("click", function (evento) {
        if (!enLaMismaPagina(destino.ruta)) return;             // otra pantalla: navega
        if (opcion.proxy || opcion.elemento) {
          var original = opcion.elemento || buscarOriginal(opcion.proxy);
          if (!original) return;                                // la vista se abre con el "#"
          evento.preventDefault();
          // Una vista ya abierta no se vuelve a pulsar (algunas se cierran
          // al pulsarlas dos veces); un reporte sí se vuelve a ejecutar.
          if (opcion.elemento || !estaActivo(original)) original.click();
          if (destino.hash && window.history && window.history.replaceState) {
            window.history.replaceState(null, "", window.location.pathname + window.location.search + "#" + destino.hash);
          }
          window.scrollTo(0, 0);                                // la vista nueva empieza arriba
          programar();
          return;
        }
        if (destino.hash) return;                               // salto dentro de la pantalla
        // Es esta misma pantalla: se vuelve arriba sin recargarla.
        evento.preventDefault();
        if (window.location.hash && window.history && window.history.replaceState) {
          window.history.replaceState(null, "", window.location.pathname + window.location.search);
        }
        window.scrollTo(0, 0);
        programar();
      });
      if (opcion.insignia) {
        var insignia = document.getElementById(opcion.insignia);
        if (insignia) {
          a.style.justifyContent = "flex-start";
          a.appendChild(insignia);
        }
      }
      opciones.push({ a: a, opcion: opcion, grupo: grupo });
      return a;
    }

    function abrirGrupo(grupo, abrir) {
      grupo.boton.setAttribute("aria-expanded", abrir ? "true" : "false");
      grupo.lista.hidden = !abrir;
    }

    function crearGrupo(titulo, item) {
      contador += 1;
      var contenedor = document.createElement("div");
      contenedor.className = "ma-grupo";
      var boton = document.createElement("button");
      boton.type = "button";
      boton.className = "ma-grupo-boton";
      boton.setAttribute("aria-expanded", "false");
      var idLista = "ma-grupo-" + contador;
      boton.setAttribute("aria-controls", idLista);
      boton.appendChild(document.createTextNode(titulo));
      var flecha = document.createElement("span");
      flecha.className = "ma-flecha";
      flecha.setAttribute("aria-hidden", "true");
      boton.appendChild(flecha);
      var lista = document.createElement("div");
      lista.className = "ma-opciones";
      lista.id = idLista;
      lista.hidden = true;
      contenedor.appendChild(boton);
      contenedor.appendChild(lista);
      var grupo = { caja: contenedor, boton: boton, lista: lista, item: item, titulo: titulo };
      boton.addEventListener("click", function () {
        var abrir = boton.getAttribute("aria-expanded") !== "true";
        // Acordeón: al abrir un grupo se pliegan los demás.
        if (abrir) grupos.forEach(function (otro) { if (otro !== grupo) abrirGrupo(otro, false); });
        abrirGrupo(grupo, abrir);
      });
      grupos.push(grupo);
      return grupo;
    }

    // Opciones de un grupo dinámico (catálogo de reportes): se rehacen
    // solo cuando la página cambia la lista.
    function rehacerDinamico(grupo) {
      var elementos = Array.prototype.filter.call(document.querySelectorAll(grupo.item.dinamico), function (el) {
        return !el.closest(".menu-acordeon");
      });
      // Si la página vuelve a dibujar la lista, los botones son otros
      // aunque tengan el mismo texto: también entonces se rehace.
      var mismos = grupo.elementos && grupo.elementos.length === elementos.length &&
        elementos.every(function (el, i) { return grupo.elementos[i] === el; });
      var firma = elementos.length ? "" : (document.querySelector("#listaReportes") || {}).textContent || "";
      if (mismos && firma === grupo.firma) return;
      grupo.elementos = elementos;
      grupo.firma = firma;
      opciones = opciones.filter(function (o) { return o.grupo !== grupo; });
      grupo.lista.innerHTML = "";
      if (!elementos.length) {
        var vacio = document.createElement("span");
        vacio.className = "ma-vacio";
        var cargando = document.querySelector("#listaReportes .comite-loading, #listaReportes p");
        vacio.textContent = cargando ? cargando.textContent.trim() : "Cargando...";
        grupo.lista.appendChild(vacio);
        return;
      }
      elementos.forEach(function (el) {
        grupo.lista.appendChild(crearEnlace({ texto: el.textContent.trim(), href: grupo.item.href, elemento: el }, grupo));
      });
    }

    // Catálogo de reportes del rol para el grupo "Reportes" en las demás pantallas.
    function cargarCatalogoReportes(grupo, item) {
      var token = null;
      try { token = localStorage.getItem("access_token"); } catch (_) {}
      var respaldo = function () {
        grupo.lista.innerHTML = "";
        grupo.lista.appendChild(crearEnlace({ texto: "Ver reportes", href: item.href }, grupo));
      };
      if (!token || !window.fetch) { respaldo(); return; }
      var cargando = document.createElement("span");
      cargando.className = "ma-vacio";
      cargando.textContent = "Cargando...";
      grupo.lista.appendChild(cargando);
      fetch("/api/reportes", { headers: { Authorization: "Bearer " + token } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (catalogo) {
          if (!Array.isArray(catalogo) || !catalogo.length) { respaldo(); return; }
          grupo.lista.innerHTML = "";
          catalogo.forEach(function (reporte) {
            grupo.lista.appendChild(crearEnlace({
              texto: reporte.titulo,
              href: item.href + "#" + encodeURIComponent(reporte.codigo)
            }, grupo));
          });
        })
        .catch(respaldo);
    }

    menu.items.forEach(function (item) {
      if (item.salir) {
        var salir = document.createElement("a");
        salir.className = "ma-enlace js-salir";
        salir.setAttribute("href", "/login");
        salir.textContent = item.texto;
        raiz.appendChild(salir);
        return;
      }
      if (item.mfa) {
        // La activación en dos pasos vive en el panel (sus ventanas y su
        // lógica están ahí): se mueve el mismo enlace, con su comportamiento.
        var mfa = document.getElementById("mfaLink");
        if (mfa && !mfa.closest(".menu-acordeon")) {
          mfa.className = "ma-enlace";
          raiz.appendChild(mfa);
        } else if (!mfa) {
          // En las demás pantallas la opción también se ve: lleva al panel,
          // que abre la configuración de la autenticación en dos pasos.
          var irMfa = document.createElement("a");
          irMfa.className = "ma-enlace";
          irMfa.href = "/dashboard#mfa";
          irMfa.textContent = "Autenticación en dos pasos";
          raiz.appendChild(irMfa);
        }
        return;
      }
      if (item.dinamico) {
        if (enLaMismaPagina(item.href)) {
          var dinamico = crearGrupo(item.texto, item);
          dinamico.dinamico = true;
          raiz.appendChild(dinamico.caja);
          rehacerDinamico(dinamico);
        } else {
          // Fuera de su pantalla también es un grupo con los mismos reportes:
          // antes el submenú solo aparecía al entrar a Reportes.
          var externo = crearGrupo(item.texto, item);
          raiz.appendChild(externo.caja);
          if (tipo === "auxiliar" && item.permisos) {
            // El catálogo se pide cuando se sabe que tiene algún reporte.
            cargasPermiso.push({ grupo: externo, item: item });
          } else if (item.soloAprobado && !accesoCompleto()) {
            cargasPendientes.push(function () { cargarCatalogoReportes(externo, item); });
          } else {
            cargarCatalogoReportes(externo, item);
          }
        }
        return;
      }
      if (item.grupo) {
        var grupo = crearGrupo(item.grupo, item);
        item.opciones.filter(permitida).forEach(function (opcion) {
          grupo.lista.appendChild(crearEnlace(opcion, grupo));
        });
        raiz.appendChild(grupo.caja);
        return;
      }
      if (permitida(item)) raiz.appendChild(crearEnlace(item, null));
    });

    var primeraVez = true;

    // Visibilidad, opción marcada y grupo abierto según el estado real
    // de la pantalla. Solo cambia atributos cuando hace falta.
    function actualizar() {
      grupos.forEach(function (grupo) { if (grupo.dinamico) rehacerDinamico(grupo); });

      var hash = window.location.hash.replace(/^#/, "");
      var mejor = null;
      var mejorPuntos = 0;
      var grupoDeLaPantalla = null;

      opciones.forEach(function (o) {
        var destino = partirHref(o.opcion.href);
        var aqui = enLaMismaPagina(destino.ruta) ||
          (o.opcion.activoEn && o.opcion.activoEn.test(rutaActual()));
        var visible = true;
        var puntos = 0;
        var original = null;
        if (aqui && (o.opcion.proxy || o.opcion.elemento)) {
          original = o.opcion.elemento || buscarOriginal(o.opcion.proxy);
          visible = Boolean(original) && !estaOculto(original);
          // El menú interno que contiene esa vista lo cubre el lateral
          // (Apelaciones, PQRS...): se oculta para que no haya dos menús.
          var navInterno = original && original.closest("nav");
          if (navInterno && !navInterno.querySelector(".menu-acordeon") && !navInterno.classList.contains("ma-oculto")) {
            navInterno.classList.add("ma-oculto");
          }
          // La vista abierta la decide la pantalla, no la dirección.
          if (visible && estaActivo(original)) puntos = 3;
          var aviso = Boolean(original) && original.classList.contains("correction-warning");
          if (o.a.classList.contains("ma-aviso") !== aviso) o.a.classList.toggle("ma-aviso", aviso);
        } else if (aqui) {
          if (destino.hash) puntos = destino.hash === hash ? 2 : 0;
          else puntos = 1;
        }
        if (!accesoCompleto() && (o.opcion.soloAprobado || (o.grupo && o.grupo.item.soloAprobado))) visible = false;
        if (!conPermiso(o.opcion, o.grupo)) visible = false;
        if (o.a.hidden === visible) o.a.hidden = !visible;
        if (visible && aqui && o.grupo && !grupoDeLaPantalla) grupoDeLaPantalla = o.grupo;
        if (puntos > mejorPuntos) { mejor = o; mejorPuntos = puntos; }
      });

      opciones.forEach(function (o) {
        var marcar = o === mejor;
        if (o.a.classList.contains("ma-activo") !== marcar) o.a.classList.toggle("ma-activo", marcar);
        if (marcar && o.a.getAttribute("aria-current") !== "page") o.a.setAttribute("aria-current", "page");
        if (!marcar && o.a.hasAttribute("aria-current")) o.a.removeAttribute("aria-current");
      });

      // Un grupo dinámico solo existe en su propia pantalla.
      grupos.forEach(function (grupo) { if (grupo.dinamico && !grupoDeLaPantalla) grupoDeLaPantalla = grupo; });
      // Si la opción marcada está suelta (Resumen), ningún grupo es el actual.
      var grupoActual = mejor ? mejor.grupo : grupoDeLaPantalla;
      grupos.forEach(function (grupo) {
        var actual = grupo === grupoActual;
        if (grupo.caja.classList.contains("ma-grupo-actual") !== actual) grupo.caja.classList.toggle("ma-grupo-actual", actual);
        if ((grupo.item.soloAprobado && !accesoCompleto()) ||
            (tipo === "auxiliar" && grupo.item.permisos && !tienePermisoAuxiliar(grupo.item.permisos))) {
          if (!grupo.caja.hidden) grupo.caja.hidden = true;
        } else if (!grupo.dinamico) {
          var algunaVisible = Array.prototype.some.call(grupo.lista.children, function (hijo) { return !hijo.hidden; });
          if (grupo.caja.hidden === algunaVisible) grupo.caja.hidden = !algunaVisible;
        } else if (grupo.caja.hidden) {
          grupo.caja.hidden = false;
        }
        var conAviso = Boolean(grupo.lista.querySelector(".ma-aviso"));
        if (grupo.boton.classList.contains("ma-aviso") !== conAviso) grupo.boton.classList.toggle("ma-aviso", conAviso);
      });
      if (primeraVez) {
        primeraVez = false;
        if (grupoActual) abrirGrupo(grupoActual, true);
      }

      var titulo = grupoActual ? grupoActual.titulo : (mejor ? mejor.a.textContent.trim() : "");
      if (!titulo || (mejor && mejor.opcion.href === "/dashboard")) titulo = "Panel principal";
      if (tituloModulo.textContent !== titulo) tituloModulo.textContent = titulo;
    }

    var pendiente = null;
    function programar() {
      if (pendiente) return;
      pendiente = window.setTimeout(function () { pendiente = null; actualizar(); }, 40);
    }

    // Abre la vista pedida con "#vista" (al llegar desde otra pantalla o
    // al cambiar solo el "#" de la dirección). Las pantallas que arman su
    // menú tarde reciben unos reintentos cortos.
    function abrirVistaDelHash(intentos) {
      var hash = window.location.hash.replace(/^#/, "");
      if (!hash) return;
      var opcion = null;
      opciones.forEach(function (o) {
        var destino = partirHref(o.opcion.href);
        if (!opcion && o.opcion.proxy && destino.hash === hash && enLaMismaPagina(destino.ruta)) opcion = o.opcion;
      });
      if (!opcion) return;
      var original = buscarOriginal(opcion.proxy);
      if (!original || estaOculto(original)) {
        if (intentos > 0) window.setTimeout(function () { abrirVistaDelHash(intentos - 1); }, 150);
        return;
      }
      if (!estaActivo(original)) original.click();
      window.scrollTo(0, 0);                                    // el "#vista" no debe dejar la página desplazada
      programar();
    }

    actualizar();

    if (tipo === "auxiliar") {
      var alCambiarPermisos = function (codigos) {
        if (notaPermisos) notaPermisos.hidden = codigos.length > 0;
        cargasPermiso.forEach(function (carga) {
          if (carga.cargado || !tienePermisoAuxiliar(carga.item.permisos)) return;
          carga.cargado = true;
          cargarCatalogoReportes(carga.grupo, carga.item);
        });
        programar();
      };
      oyentesPermisos.push(alCambiarPermisos);
      if (permisosAuxiliar.conocido) alCambiarPermisos(permisosAuxiliar.codigos.slice());
    }

    if (tipo === "auditor") {
      oyentesAcceso.push(function () {
        if (notaRegistro) notaRegistro.hidden = accesoCompleto();
        if (accesoCompleto()) {
          cargasPendientes.splice(0).forEach(function (cargar) { cargar(); });
        }
        programar();
      });
    }

    if (window.MutationObserver) {
      new MutationObserver(function (cambios) {
        for (var i = 0; i < cambios.length; i++) {
          var objetivo = cambios[i].target;
          if (objetivo.nodeType !== 1 || !objetivo.closest(".menu-acordeon")) { programar(); return; }
        }
      }).observe(document.body, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ["class", "hidden", "style", "aria-current", "aria-selected"]
      });
    }
    window.addEventListener("hashchange", function () { abrirVistaDelHash(0); programar(); });
    window.setTimeout(function () { abrirVistaDelHash(20); }, 0);
  }


  /* ----------------------------------------------------------
     5. Consulta pública de certificados.

     /verificar-certificado es la misma pantalla de certificados en
     modo público: no traía la cabecera de las demás consultas
     públicas (no había cómo volver) y mostraba un menú lateral con
     una sola opción. Se le pone esa cabecera y se quita el lateral.
     ---------------------------------------------------------- */
  // Mismo menú que las páginas públicas desde el buscador unificado del
  // equipo (13/11): vigencia, norma, validar y constancia viven en él.
  var CONSULTAS_PUBLICAS = [
    ["/buscar_empresa", "Buscar empresa por NIT"],
    ["/verificar-certificado", "Verificar certificado"]
  ];

  function enlacesPublicos() {
    return CONSULTAS_PUBLICAS.map(function (c) {
      return '<a href="' + c[0] + '">' + c[1] + "</a>";
    }).join("");
  }

  function ajustarConsultaPublica() {
    if (!enLaMismaPagina("/verificar-certificado")) return;
    ponerEstilos();
    var lateral = document.querySelector("aside.comite-sidebar");
    if (lateral) lateral.classList.add("ma-oculto");
    var columnas = document.querySelector(".comite-layout");
    if (columnas) columnas.classList.add("ma-sin-lateral");

    var cabecera = document.querySelector("header.login-header");
    var contenido = cabecera && cabecera.querySelector(".header-content");
    if (!contenido || contenido.querySelector(".header-buttons")) return;
    var subtitulo = contenido.querySelector(".subtitle");
    if (subtitulo) {
      subtitulo.textContent = "Plataforma de gestión y consulta de certificados";
      // Misma tercera línea que las demás consultas públicas.
      if (!subtitulo.parentNode.querySelector(".cp-linea-sena")) {
        var linea = document.createElement("p");
        linea.className = "cp-linea-sena";
        linea.style.cssText = "font-size:12px;opacity:.85;margin-top:4px;";
        linea.textContent = "Servicio Nacional de Aprendizaje • CertiSENA";
        subtitulo.parentNode.appendChild(linea);
      }
    }

    var botones = document.createElement("div");
    botones.className = "header-buttons";
    botones.innerHTML =
      '<div class="nav-dropdown">' +
        '<button type="button" class="btn-login nav-dropdown-toggle" aria-haspopup="true">' +
          'Consulta pública <span class="nav-caret">▼</span></button>' +
        '<div class="nav-dropdown-menu"><div class="nav-dropdown-panel">' + enlacesPublicos() + "</div></div>" +
      "</div>" +
      '<a href="/login" class="btn-login">Iniciar sesión</a>' +
      '<a href="/register" class="btn-login">Registrarse</a>';
    contenido.appendChild(botones);

    var hamburguesa = document.createElement("button");
    hamburguesa.className = "hamburger-btn";
    hamburguesa.type = "button";
    hamburguesa.setAttribute("aria-label", "Menú");
    hamburguesa.innerHTML = "<span></span><span></span><span></span>";
    contenido.appendChild(hamburguesa);

    var movil = document.createElement("div");
    movil.className = "mobile-menu";
    movil.innerHTML =
      '<a href="/login">Iniciar sesión</a><a href="/register">Registrarse</a>' +
      '<div class="mobile-menu-group"><span class="mobile-menu-label">Consulta pública</span>' + enlacesPublicos() + "</div>";
    cabecera.appendChild(movil);

    hamburguesa.addEventListener("click", function () {
      hamburguesa.classList.toggle("active");
      movil.classList.toggle("open");
    });
  }

  function aplicar() {
    if (esSesionAuxiliar()) {
      aplicarPermisosEnPagina();
      vigilarPermisosEnPagina();
      ajustarPanelAuxiliar();
    }
    ajustarConsultaPublica();
    var rol = rolDelUsuario();
    if (rol) {
      var tipo = tipoDeRol(rol);
      var menu = menuDelRol(tipo);
      if (menu && !enLaMismaPagina("/verificar-certificado")) crearMenuAcordeon(menu, tipo);
      ajustarEnlacesAlPanel(panelDelRol(rol));
    }
    ajustarEnlacesDePerfil();
    if (/auditor/.test(rol) && !/administrar/.test(rol)) {
      ajustarCabeceraAuditor();
    }
  }

  // El acceso del auditor se pide en cuanto carga el script, antes de que
  // la pantalla dibuje nada.
  if (tipoDeRol(rolDelUsuario()) === "auditor") iniciarAccesoAuditor();
  // Igual los permisos del Auxiliar (menú, botones y panel).
  if (esSesionAuxiliar()) {
    oyentesPermisos.push(ajustarPanelAuxiliar);
    iniciarPermisosAuxiliar();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", aplicar);
  } else {
    aplicar();
  }
})();

/* ==========================================================
   Modales accesibles: carga static/modales.js (foco, Tab,
   Escape y roles ARIA en las ventanas modales hechas con div).
   Bloque independiente: no toca la lógica del menú.
   ========================================================== */
(function () {
  "use strict";
  if (window.__modalesAccesibles || document.querySelector('script[src^="/static/modales.js"]')) return;
  var s = document.createElement("script");
  s.src = "/static/modales.js?v=20261114";
  s.defer = true;
  (document.head || document.documentElement).appendChild(s);
})();
