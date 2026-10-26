/* Guard de sesión compartido.
 *
 * Los endpoints de datos ya validan el estado de la cuenta en el servidor.
 * Este guard solo evita que una cuenta inactivada siga viendo la interfaz:
 * consulta /auth/session y redirige a la pantalla de cuenta inactiva cuando
 * corresponde. Nunca reemplaza la validación del backend.
 */
(function () {
  "use strict";

  var token = null;
  try {
    token = localStorage.getItem("access_token");
  } catch (_) {
    return;
  }

  if (!token) return;

  function normalizarRol(valor) {
    var base = String(valor || "")
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .replace(/[\s_-]+/g, "");
    if (base === "administrador") return "admin";
    if (base === "superadministrador") return "superadmin";
    return base;
  }

  fetch("/auth/session", {
    headers: { Authorization: "Bearer " + token },
    cache: "no-store",
  })
    .then(function (respuesta) {
      if (!respuesta.ok) return null;
      return respuesta.json();
    })
    .then(function (sesion) {
      if (!sesion || sesion.activo !== false) return;

      var rol = normalizarRol(sesion.role_name);
      try {
        localStorage.removeItem("access_token");
        localStorage.removeItem("token_type");
      } catch (_) {}

      window.location.replace(rol === "auditor" ? "/cuenta-inactiva" : "/login");
    })
    .catch(function () {
      /* Sin conexión: las llamadas protegidas seguirán validando el estado. */
    });
})();
