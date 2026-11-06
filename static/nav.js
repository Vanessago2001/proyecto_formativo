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
     Grupo:    { grupo, opciones: [...] }
     Dinámico: { texto, href, dinamico: selector } — fuera de esa
               pantalla es un enlace; en ella, un grupo con los
               elementos que la página dibuje (catálogo de reportes).
     ---------------------------------------------------------- */

  var REPORTES = { texto: "Reportes", href: "/reportes", dinamico: "#listaReportes button[data-codigo]" };
  var SALIR = { salir: true, texto: "Cerrar sesión" };

  // Módulo PQRS (static/pqrs_gestion.html): sus vistas son botones
  // button[data-view] y la página abre la vista del "#" al cargar.
  var GRUPO_PQRS = {
    grupo: "PQRS",
    opciones: [
      ["bandeja", "Bandeja de PQRS"],
      ["tiempos", "Tiempos de atención"],
      ["reportes", "Reportes"]
    ].map(function (v) {
      return { texto: v[1], href: "/pqrs-gestion#" + v[0], proxy: 'button[data-view="' + v[0] + '"]' };
    })
  };

  var GRUPO_COMITE = function (titulo) {
    return {
      grupo: titulo,
      opciones: [
        { texto: "Expedientes pendientes", href: "/comite#expedientes", proxy: 'aside.comite-sidebar button[data-view="expedientes"]' },
        { texto: "Historial de decisiones", href: "/comite#historico", proxy: 'aside.comite-sidebar button[data-view="historico"]' }
      ]
    };
  };

  var GRUPO_CERTIFICADOS = {
    grupo: "Gestión de certificados",
    opciones: [
      { texto: "Certificados", href: "/gestion-certificados#catalogo", proxy: "#catalogNav" },
      { texto: "Vencimientos", href: "/gestion-certificados#vencimientos", proxy: "#alertsNav", solo: ["admin", "auxiliar"] },
      { texto: "Consulta pública", href: "/gestion-certificados#consulta", proxy: 'aside.comite-sidebar button[data-view="consulta"]' }
    ]
  };

  var GRUPO_APELACIONES = function (titulo) {
    function vista(clave, texto, solo) {
      return { texto: texto, href: "/apelacion#" + clave, proxy: '#vistaNav button[data-vista="' + clave + '"]', solo: solo };
    }
    return {
      grupo: titulo,
      opciones: [
        vista("bandeja", "Bandeja del comité"),
        vista("expediente", "Expediente"),
        vista("requerimientos", "Requerimientos"),
        vista("decision", "Decisión del comité"),
        vista("asignar", "Asignar comité", ["admin", "auxiliar"])
      ]
    };
  };

  var MENU_ADMINISTRACION = {
    titulo: "Administración",
    items: [
      { texto: "Resumen", href: "/dashboard" },
      {
        grupo: "Usuarios",
        opciones: [
          // El panel solo muestra la gestión de usuarios al Administrador.
          { texto: "Gestionar usuarios", href: "/dashboard#usuarios", solo: ["admin"] },
          { texto: "Permisos de auxiliares", href: "/permisos-auxiliar", solo: ["admin"] }
        ]
      },
      {
        grupo: "Empresas",
        opciones: [
          { texto: "Registradas", href: "/empresas#listado", proxy: '#menu button[data-view="listado"]' },
          { texto: "Registrar empresa", href: "/empresas#registrar", proxy: '#menu button[data-view="registrar"]' },
          { texto: "Aprobaciones", textoAuxiliar: "Mis solicitudes de aprobación", href: "/empresas#aprobaciones", proxy: '#menu button[data-view="aprobaciones"]' }
        ]
      },
      { texto: "Asignación de auditores", href: "/asignacion-auditores" },
      {
        grupo: "Auditorías",
        opciones: [
          { texto: "Consultar auditorías programadas", href: "/consultar-auditorias-programadas-admin#listado", proxy: '.page-tabs a[data-vista="listado"]' },
          { texto: "Solicitudes de reprogramación", href: "/consultar-auditorias-programadas-admin#reprogramaciones", proxy: '.page-tabs a[data-vista="reprogramaciones"]' },
          { texto: "Consultar programaciones futuras", href: "/consultar-auditorias-programadas-admin#futuras", proxy: '.page-tabs a[data-vista="futuras"]' }
        ]
      },
      {
        grupo: "Consultar agenda de auditor",
        opciones: [
          ["schedule", "Programar una auditoría"],
          ["assignments", "Solicitudes con auditores asignados"],
          ["weekly", "Disponibilidad semanal"],
          ["blocked", "Registrar fecha no disponible"],
          ["month", "Disponibilidad mensual y auditorías"],
          ["history", "Historial de disponibilidad"],
          ["bitacora", "Bitácora de validación"]
        ].map(function (s) {
          return { texto: s[1], href: "/consultar-agenda-auditor#" + s[0], proxy: '.agenda-menu a[data-seccion="' + s[0] + '"]' };
        })
      },
      {
        grupo: "Revisión de solicitudes",
        opciones: [
          ["radicadas", "Solicitudes radicadas"],
          ["revision", "En revisión"],
          ["todas", "Todas las solicitudes"]
        ].map(function (f) {
          return { texto: f[1], href: "/revision-solicitudes#" + f[0], proxy: 'aside.comite-sidebar button[data-filtro="' + f[0] + '"]' };
        })
      },
      {
        grupo: "Banco de auditores",
        opciones: [
          { texto: "Banco de auditores", href: "/banco-auditores", activoEn: /^\/banco-auditores\/solicitud\// },
          { texto: "Auditores registrados", href: "/auditores-registrados" },
          { texto: "Conflictos de interés", href: "/conflictos-administrador" },
          { texto: "Consultar empresas restringidas", href: "/empresas-restringidas" }
        ]
      },
      GRUPO_CERTIFICADOS,
      GRUPO_APELACIONES("Apelaciones"),
      GRUPO_COMITE("Comité de certificación"),
      GRUPO_PQRS,
      REPORTES,
      { texto: "Mi perfil", href: "/profile" },
      { mfa: true },                       // solo en el panel, donde vive su lógica
      SALIR
    ]
  };

  var MENU_AUDITOR = {
    titulo: "Portal del auditor",
    items: [
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
        grupo: "Conflictos y restricciones",
        opciones: [
          { texto: "Consultar conflictos registrados", href: "/conflictos-auditor" },
          { texto: "Consultar empresas restringidas", href: "/empresas-restringidas" }
        ]
      },
      {
        grupo: "Auditorías",
        opciones: [
          { texto: "Consultar auditorías programadas", href: "/consultar-auditorias-programadas" },
          { texto: "Programaciones futuras", href: "/programaciones-futuras-auditor" }
        ]
      },
      {
        grupo: "Disponibilidad",
        opciones: [
          ["configurar-horario", "Horario semanal"],
          ["bloquear-fecha", "Bloquear fecha"],
          ["desbloquear-fecha", "Desbloquear fecha"],
          ["disponibilidad-extraordinaria", "Disponibilidad extraordinaria"],
          ["historial-disponibilidad", "Historial"]
        ].map(function (s) {
          return { texto: s[1], href: "/disponibilidad-auditor#" + s[0], proxy: '.side a[data-seccion="' + s[0] + '"]' };
        })
      },
      {
        grupo: "Catálogo de competencias",
        opciones: [
          { texto: "Competencias registradas", href: "/catalogo-competencias-auditor#vistaCompetencias", proxy: '.side a[data-vista="competencias"]' },
          { texto: "Registrar certificaciones vigentes", href: "/catalogo-competencias-auditor#vistaCertificaciones", proxy: '.side a[data-vista="certificaciones"]' }
        ]
      },
      GRUPO_PQRS,
      { texto: "Notificaciones", href: "/notificaciones-auditor", insignia: "notifBadge" },
      { texto: "Mi perfil", href: "/perfil-auditor" },
      REPORTES,
      SALIR
    ]
  };

  var MENU_COMITE = {
    titulo: "Comité de certificación",
    items: [
      GRUPO_COMITE("Comité de certificación"),
      GRUPO_CERTIFICADOS,
      GRUPO_APELACIONES("Apelaciones asignadas"),
      REPORTES,
      { texto: "Mi perfil", href: "/profile" },
      SALIR
    ]
  };

  // Menús propios de cada pantalla que quedan cubiertos por el lateral.
  var MENUS_INTERNOS = {
    "/apelacion": ["#vistaNav"],
    "/consultar-auditorias-programadas-admin": [".page-tabs"]
  };

  function tipoDeRol(rol) {
    if (/auxiliar/.test(rol)) return "auxiliar";
    if (/admin/.test(rol)) return "admin";
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
    "nav.menu-acordeon a.ma-enlace[hidden],nav.menu-acordeon .ma-grupo[hidden]{display:none}"
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
    return elemento.hidden || elemento.style.display === "none";
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
          raiz.appendChild(crearEnlace({ texto: item.texto, href: item.href }, null));
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
        if (o.a.hidden === visible) o.a.hidden = !visible;
        if (aqui && o.grupo && !grupoDeLaPantalla) grupoDeLaPantalla = o.grupo;
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
        if (!grupo.dinamico) {
          var algunaVisible = Array.prototype.some.call(grupo.lista.children, function (hijo) { return !hijo.hidden; });
          if (grupo.caja.hidden === algunaVisible) grupo.caja.hidden = !algunaVisible;
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
  var CONSULTAS_PUBLICAS = [
    ["/buscar_empresa", "Buscar empresa por NIT"],
    ["/", "Consultar estado de vigencia"],
    ["/verificar-certificado", "Verificar certificado"],
    ["/consulta-norma", "Consultar norma evaluada"],
    ["/vigencia", "Consultar vigencia y plazos"],
    ["/validar", "Validar autenticidad"],
    ["/constancia", "Descargar constancia pública"]
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
    if (subtitulo) subtitulo.textContent = "Plataforma de gestión y consulta de certificados";

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
    ajustarConsultaPublica();
    var rol = rolDelUsuario();
    if (rol) {
      var tipo = tipoDeRol(rol);
      var menu = menuDelRol(tipo);
      if (menu && !enLaMismaPagina("/verificar-certificado")) crearMenuAcordeon(menu, tipo);
      ajustarEnlacesAlPanel(panelDelRol(rol));
    }
    ajustarEnlacesDePerfil();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", aplicar);
  } else {
    aplicar();
  }
})();
