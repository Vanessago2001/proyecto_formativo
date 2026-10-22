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
   ========================================================== */
(function () {
  "use strict";

  var ICONO_PERFIL =
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"' +
    ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"' +
    ' focusable="false" style="vertical-align:middle">' +
    '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path>' +
    '<circle cx="12" cy="7" r="4"></circle></svg>';

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

  function aplicar() {
    var rol = rolDelUsuario();
    if (rol) ajustarEnlacesAlPanel(panelDelRol(rol));
    ajustarEnlacesDePerfil();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", aplicar);
  } else {
    aplicar();
  }
})();
