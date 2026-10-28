/* ==========================================================
   Navegación común de CertiSENA

   Solo toca la barra superior y los menús; no cambia la lógica
   de ninguna pantalla ni los estilos definidos en cada página.

   1. "Panel" lleva al panel que corresponde al rol:
        Empresa -> /empresa   Comité -> /comite   Auditor -> /auditor
        los demás -> /dashboard
      Si ese panel es la pantalla actual, el enlace se oculta.
   2. En la pantalla de perfil no se muestra el enlace al perfil.
   3. En el resto, ese enlace se muestra como un icono.
   4. El menú lateral es el mismo en todas las pantallas del rol.
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
        .normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
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

  function enLaMismaPagina(ruta) {
    return window.location.pathname.replace(/\/$/, "") === ruta.replace(/\/$/, "");
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
     4. El menú lateral es el mismo en todas las pantallas.

     Cada pantalla traía su propia lista: unas con nueve opciones,
     otras con dos, y ninguna igual a la siguiente. Aquí se dibuja
     la del rol que entró, conservando las clases de la página para
     que cada una siga viéndose como estaba.

     No se tocan dos casos, porque ahí el menú hace otra cosa:
       · los menús con botones, que cambian de vista dentro de la
         misma pantalla (Comité, Apelaciones);
       · los que navegan por secciones con enlaces "#", como el
         formulario de registro del auditor.
     ---------------------------------------------------------- */

  // Mismo menú y en el mismo orden que el del panel principal.
  var MENU_ADMINISTRACION = [
    ["/dashboard", "Resumen"],
    ["/empresas", "Empresas registradas"],
    ["/dashboard#usuarios", "Gestionar usuarios"],
    ["/asignacion-auditores", "Asignación de auditores"],
    ["/consultar-auditorias-programadas-admin", "Consultar auditorías programadas"],
    ["/consultar-auditorias-programadas-admin#futuras", "Consultar programaciones futuras"],
    ["/consultar-agenda-auditor", "Consultar agenda de auditor"],
    ["/revision-solicitudes", "Revisión de solicitudes"],
    ["/banco-auditores", "Banco de auditores"],
    ["/conflictos-administrador", "Conflictos de interés"],
    ["/empresas-restringidas", "Consultar empresas restringidas"],
    ["/gestion-certificados", "Gestión de certificados"],
    ["/apelacion", "Apelaciones"],
    ["/comite", "Ir al Comité de certificación"],
    ["/reportes", "Reportes"],
    ["/profile", "Mi perfil"]
  ];

  var MENU_AUDITOR = [
    ["/auditor", "Mi registro"],
    ["/consultar-estado", "Estado del registro"],
    ["/catalogo-competencias-auditor", "Catálogo de competencias"],
    ["/conflictos-auditor", "Conflictos registrados"],
    ["/consultar-auditorias-programadas", "Auditorías programadas"],
    ["/programaciones-futuras-auditor", "Programaciones futuras"],
    ["/disponibilidad-auditor", "Disponibilidad semanal"],
    ["/notificaciones-auditor", "Notificaciones"],
    ["/perfil-auditor", "Mi perfil"],
    ["/reportes", "Reportes"]
  ];

  function menuDelRol(rol) {
    if (/admin|auxiliar/.test(rol)) return MENU_ADMINISTRACION;
    if (/auditor/.test(rol)) return MENU_AUDITOR;
    return null;                          // empresa y comité tienen el suyo
  }

  function navegaPorSecciones(nav) {
    /*
      Un menu que apunta a secciones de la propia pantalla (el formulario
      de registro del auditor) no se toca. Se reconoce porque esos
      destinos "#" existen aqui: un "#usuarios" que vive en otra pantalla
      no es navegacion interna, es un enlace que ademas no funciona.
    */
    var internos = nav.querySelectorAll('a[href^="#"]');
    if (!internos.length) return false;
    return Array.prototype.some.call(internos, function (enlace) {
      var destino = (enlace.getAttribute("href") || "").slice(1);
      return destino && document.getElementById(destino);
    });
  }

  // El panel principal encabeza su menú con el módulo abierto; las demás
  // pantallas repiten ese mismo encabezado para que el menú no cambie.
  function tituloDelModulo() {
    var partes = (document.title || "").split("|");
    return (partes[1] || "").trim() || "Panel principal";
  }

  function crearEncabezado() {
    var caja = document.createElement("div");
    caja.className = "admin-nav-heading";
    var kicker = document.createElement("span");
    kicker.textContent = "Administración";
    caja.appendChild(kicker);
    caja.appendChild(document.createTextNode(tituloDelModulo()));
    return caja;
  }

  // El panel original cierra su menú con "Cerrar sesión"; las pantallas que
  // no lo traían reciben el mismo enlace para que el menú no cambie.
  function crearSalir() {
    var enlace = document.createElement("a");
    enlace.setAttribute("href", "/login");
    enlace.className = "logout-link";
    enlace.textContent = "Cerrar sesión";
    enlace.addEventListener("click", function (evento) {
      evento.preventDefault();
      localStorage.clear();
      window.location.href = "/login";
    });
    return enlace;
  }

  function marcarActivo(enlace, destino, seccionAbierta) {
    var partes = destino.split("#");
    var ruta = partes[0];
    var seccion = partes[1] || "";
    if (!ruta || !enLaMismaPagina(ruta)) return;
    // Dos entradas pueden apuntar a la misma pantalla: la de la sección
    // solo se marca cuando esa sección está abierta, y la de la pantalla
    // completa solo cuando no hay una sección del menú abierta.
    if (seccion) {
      if (window.location.hash === "#" + seccion) enlace.classList.add("active");
      return;
    }
    if (!seccionAbierta) enlace.classList.add("active");
  }

  // Lo que identifica al elemento de salir, venga como enlace o como botón.
  var SELECTOR_SALIR = '#logoutLink, a[href="/login"], .js-logout, button.salir, a.salir';

  // Un menú con botones que cambian de vista en la misma pantalla se respeta:
  // esos botones son la pantalla, no la navegación del rol. El botón de salir
  // no cuenta, porque no cambia de vista: cierra la sesión.
  function tieneBotonDeVista(nav) {
    var botones = nav.querySelectorAll("button");
    for (var i = 0; i < botones.length; i++) {
      if (!botones[i].matches(SELECTOR_SALIR)) return true;
    }
    return false;
  }

  function unificarMenuLateral(rol) {
    var menu = menuDelRol(rol);
    if (!menu) return;

    var contenedores = document.querySelectorAll(
      "nav.admin-nav, aside.comite-sidebar nav, aside.sidebar nav, nav.module-menu"
    );

    Array.prototype.forEach.call(contenedores, function (nav) {
      var enlaces = nav.querySelectorAll("a[href]");
      if (!enlaces.length) return;
      if (tieneBotonDeVista(nav)) return;           // cambia de vista en la misma pantalla
      if (navegaPorSecciones(nav)) return;          // indice de secciones de la pantalla

      // Se conserva el elemento de salir, enlace o botón: su comportamiento
      // está atado a ese elemento, así que se mueve en vez de volver a crearlo.
      var salir = nav.querySelector(SELECTOR_SALIR);
      // La clase de la página se copia a cada opción, salvo "active":
      // si la primera opción venía marcada, se marcaban todas.
      var clase = (enlaces[0].className || "").replace(/\bactive\b/g, "").trim();

      nav.innerHTML = "";
      // El encabezado solo va en la barra plana del panel; las pantallas con
      // su propio encabezado de módulo ya lo muestran fuera del menú.
      if (menu === MENU_ADMINISTRACION && nav.classList.contains("admin-nav")) {
        nav.appendChild(crearEncabezado());
      }
      // Si la pantalla está abierta en una vista con sección (#futuras),
      // solo esa entrada queda marcada, no también la de la pantalla completa.
      var hash = window.location.hash;
      var seccionAbierta = hash && menu.some(function (opcion) {
        var partes = opcion[0].split("#");
        return partes[1] && "#" + partes[1] === hash && enLaMismaPagina(partes[0]);
      });
      menu.forEach(function (opcion) {
        var enlace = document.createElement("a");
        enlace.setAttribute("href", opcion[0]);
        enlace.textContent = opcion[1];
        if (clase) enlace.className = clase;
        marcarActivo(enlace, opcion[0], seccionAbierta);
        nav.appendChild(enlace);
      });
      if (salir) {
        nav.appendChild(salir);
      } else if (menu === MENU_ADMINISTRACION) {
        nav.appendChild(crearSalir());
      }
    });
  }

  function aplicar() {
    var rol = rolDelUsuario();
    if (rol) {
      unificarMenuLateral(rol);
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
