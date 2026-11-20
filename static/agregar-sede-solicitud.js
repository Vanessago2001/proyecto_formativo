/* =========================================================
   AGREGAR SEDE A UNA SOLICITUD APROBADA (Coordinador)

   20/11/2026: el Coordinador puede incluir en una solicitud ya
   Aprobada una sede activa que la empresa tenga registrada
   (SOL-021). Sirve para programar la visita de esa sede o para
   cumplir la regla de la sede principal antes de asignar auditor.

   Uso:
     AgregarSedeSolicitud.esCoordinador()  -> true/false
     AgregarSedeSolicitud.abrir({ idSolicitud, radicado, alAgregar })
   El servidor vuelve a comprobar el rol y el estado de la solicitud.
   ========================================================= */
(function () {
  "use strict";
  if (window.AgregarSedeSolicitud) return;

  function token() {
    return localStorage.getItem("access_token") || localStorage.getItem("accessToken") || localStorage.getItem("token") || "";
  }

  function esc(valor) {
    return String(valor == null ? "" : valor).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function esCoordinador() {
    try {
      var parte = token().split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      var datos = JSON.parse(decodeURIComponent(atob(parte).split("").map(function (c) {
        return "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2);
      }).join("")));
      var rol = String(datos.role_name || datos.rol || "").trim().toLowerCase();
      return ["coordinador", "administrador", "admin", "adm"].indexOf(rol) !== -1;
    } catch (_) {
      return false;
    }
  }

  async function pedir(ruta, opciones) {
    opciones = opciones || {};
    var headers = Object.assign({ Accept: "application/json", Authorization: "Bearer " + token() }, opciones.headers || {});
    if (opciones.body) headers["Content-Type"] = "application/json";
    var respuesta = await fetch(ruta, Object.assign({}, opciones, { headers: headers, credentials: "include" }));
    var cuerpo = await respuesta.json().catch(function () { return null; });
    if (!respuesta.ok) {
      var detalle = cuerpo && cuerpo.detail;
      throw new Error(typeof detalle === "string" ? detalle : "No se pudo completar la acción (HTTP " + respuesta.status + ").");
    }
    return cuerpo;
  }

  var dialogo = null;

  function crearDialogo() {
    if (dialogo) return dialogo;
    dialogo = document.createElement("dialog");
    dialogo.id = "agregarSedeSolicitudDialogo";
    dialogo.setAttribute("aria-labelledby", "agregarSedeSolicitudTitulo");
    dialogo.style.cssText = "max-width:640px;width:calc(100% - 32px);border:1px solid #d0d5dd;border-radius:12px;padding:20px;";
    dialogo.innerHTML =
      '<h3 id="agregarSedeSolicitudTitulo" style="margin:0 0 6px;">Agregar sede a la solicitud</h3>' +
      '<p class="hint" data-sede-subtitulo style="margin:0 0 12px;"></p>' +
      '<div data-sede-lista role="radiogroup" aria-label="Sedes de la empresa que se pueden agregar"></div>' +
      '<p data-sede-error role="alert" style="display:none;color:#b42318;font-size:13px;margin:8px 0 0;"></p>' +
      '<div class="modal-actions" style="display:flex;gap:8px;justify-content:flex-end;margin-top:16px;">' +
      '<button type="button" class="btn btn-secundario" data-sede-cancelar>Cancelar</button>' +
      '<button type="button" class="btn btn-primario" data-sede-confirmar disabled>Agregar sede</button>' +
      "</div>";
    document.body.appendChild(dialogo);
    dialogo.querySelector("[data-sede-cancelar]").addEventListener("click", function () { dialogo.close(); });
    dialogo.querySelector("[data-sede-lista]").addEventListener("change", function () {
      dialogo.querySelector("[data-sede-confirmar]").disabled = !dialogo.querySelector('input[name="sedeAgregar"]:checked');
    });
    return dialogo;
  }

  function mostrarError(mensaje) {
    var error = dialogo.querySelector("[data-sede-error]");
    error.textContent = mensaje || "";
    error.style.display = mensaje ? "block" : "none";
  }

  async function abrir(opciones) {
    opciones = opciones || {};
    var idSolicitud = opciones.idSolicitud;
    if (!idSolicitud) return;
    crearDialogo();
    var lista = dialogo.querySelector("[data-sede-lista]");
    var confirmar = dialogo.querySelector("[data-sede-confirmar]");
    dialogo.querySelector("[data-sede-subtitulo]").textContent =
      "Solicitud " + (opciones.radicado || "") + ". Solo se listan las sedes activas de la empresa que aún no están en la solicitud.";
    lista.innerHTML = '<p class="hint">Cargando sedes…</p>';
    confirmar.disabled = true;
    mostrarError("");
    if (!dialogo.open) dialogo.showModal();

    try {
      var sedes = await pedir("/solicitudes/" + encodeURIComponent(idSolicitud) + "/sedes/disponibles");
      if (!Array.isArray(sedes) || !sedes.length) {
        lista.innerHTML = '<p class="hint">La empresa no tiene más sedes activas para agregar. La empresa debe registrar la sede en su portal.</p>';
        return;
      }
      lista.innerHTML = sedes.map(function (sede, i) {
        return '<label style="display:flex;gap:10px;align-items:flex-start;padding:8px;border:1px solid #eaecf0;border-radius:8px;margin-bottom:6px;cursor:pointer;">' +
          '<input type="radio" name="sedeAgregar" value="' + esc(sede.id_sede) + '"' + (i === 0 && sedes.length === 1 ? " checked" : "") + ">" +
          "<span><strong>" + esc(sede.nombre_sede || "Sede") + "</strong>" + (sede.es_principal ? " (sede principal)" : "") +
          '<br><small>' + esc([sede.direccion, sede.ciudad, sede.departamento].filter(Boolean).join(" · ")) + "</small></span></label>";
      }).join("");
      confirmar.disabled = !lista.querySelector('input[name="sedeAgregar"]:checked');
    } catch (error) {
      lista.innerHTML = "";
      mostrarError(error.message);
    }

    confirmar.onclick = async function () {
      var elegida = lista.querySelector('input[name="sedeAgregar"]:checked');
      if (!elegida) return;
      confirmar.disabled = true;
      confirmar.textContent = "Agregando…";
      mostrarError("");
      try {
        var sede = await pedir("/solicitudes/" + encodeURIComponent(idSolicitud) + "/sedes", {
          method: "POST",
          body: JSON.stringify({ id_sede: elegida.value })
        });
        dialogo.close();
        if (typeof opciones.alAgregar === "function") await opciones.alAgregar(sede);
      } catch (error) {
        mostrarError(error.message);
        confirmar.disabled = false;
      } finally {
        confirmar.textContent = "Agregar sede";
      }
    };
  }

  window.AgregarSedeSolicitud = { abrir: abrir, esCoordinador: esCoordinador };
})();
