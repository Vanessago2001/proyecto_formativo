/* ==========================================================
   Enlace "PQRS" en la navegación

   - Sin sesión iniciada: el botón PQRS aparece en la cabecera de
     todas las páginas públicas (antes de "Iniciar sesión") y en el
     menú del celular.
   - Con sesión iniciada: el enlace PQRS no aparece en la cabecera
     ni en los menús.

   Solo toca enlaces a la página pública /pqrs; la bandeja de gestión
   (/pqrs-gestion) no se ve afectada.
   ========================================================== */
(function () {
  "use strict";

  var TITULO = "Peticiones, quejas, reclamos y sugerencias";
  var ZONAS_DE_NAVEGACION = "header, nav, .mobile-menu, .header-buttons, .menu-acordeon";

  // Hay sesión si existe un token que todavía no venció.
  function haySesion() {
    try {
      var token = localStorage.getItem("access_token");
      if (!token) return false;
      var parte = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      var datos = JSON.parse(atob(parte));
      return !datos.exp || datos.exp * 1000 > Date.now();
    } catch (_) {
      return false;
    }
  }

  // /pqrs, /pqrs#... o /pqrs?...  (no /pqrs-gestion)
  function esEnlacePqrs(enlace) {
    var ruta = (enlace.getAttribute("href") || "").split(/[?#]/)[0].replace(/\/$/, "");
    return ruta === "/pqrs";
  }

  function enlacesPqrsEnNavegacion() {
    return Array.prototype.filter.call(
      document.querySelectorAll(ZONAS_DE_NAVEGACION.split(", ").map(function (z) { return z + " a[href]"; }).join(", ")),
      esEnlacePqrs
    );
  }

  function enlaceLogin(contenedor) {
    return Array.prototype.find.call(contenedor.querySelectorAll("a[href]"), function (a) {
      return (a.getAttribute("href") || "").split(/[?#]/)[0] === "/login";
    });
  }

  function agregarEnCabecera() {
    document.querySelectorAll(".header-buttons").forEach(function (botones) {
      if (Array.prototype.some.call(botones.querySelectorAll("a[href]"), esEnlacePqrs)) return;
      var enlace = document.createElement("a");
      enlace.href = "/pqrs";
      enlace.className = "btn-login";
      enlace.title = TITULO;
      enlace.textContent = "PQRS";
      var login = enlaceLogin(botones);
      botones.insertBefore(enlace, login || null);
    });
  }

  function agregarEnMenuMovil() {
    document.querySelectorAll(".mobile-menu").forEach(function (menu) {
      if (Array.prototype.some.call(menu.querySelectorAll("a[href]"), esEnlacePqrs)) return;
      var enlace = document.createElement("a");
      enlace.href = "/pqrs";
      enlace.textContent = "PQRS: peticiones, quejas y reclamos";
      var login = enlaceLogin(menu);
      if (login && login.parentNode === menu) {
        menu.insertBefore(enlace, login.nextSibling);
      } else {
        menu.insertBefore(enlace, menu.firstChild);
      }
    });
  }

  function aplicar() {
    if (haySesion()) {
      enlacesPqrsEnNavegacion().forEach(function (enlace) {
        enlace.hidden = true;
        enlace.style.display = "none";
      });
      return;
    }
    agregarEnCabecera();
    agregarEnMenuMovil();
  }

  // Algunas cabeceras se arman con JavaScript (nav.js en /verificar-certificado):
  // se aplica al cargar y otra vez cuando terminó de cargar todo.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", aplicar);
  } else {
    aplicar();
  }
  window.addEventListener("load", aplicar);
})();
