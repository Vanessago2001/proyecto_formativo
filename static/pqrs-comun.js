/* ==========================================================
   PQRS · utilidades compartidas por /pqrs y /pqrs-gestion.
   Expone window.PQRS (sin dependencias).
   ========================================================== */
(function () {
  "use strict";

  var SEMAFORO = {
    vencida: "Vencida",
    proxima: "Próxima a vencer",
    en_termino: "En término",
    en_espera: "Esperando al peticionario",
    atendida_a_tiempo: "Atendida a tiempo",
    atendida_tarde: "Atendida fuera de término"
  };

  var ACCIONES = {
    radicar: "Radicada",
    asignar: "Responsable asignado",
    reasignar: "Responsable reasignado",
    cambiar_estado: "Cambio de estado",
    solicitar_informacion: "Información solicitada",
    aportar_informacion: "Información aportada por el peticionario",
    adjuntar: "Adjuntos agregados",
    responder: "Respuesta registrada",
    cerrar: "Cerrada",
    reabrir: "Reabierta",
    notificar: "Notificación por correo"
  };

  function esc(valor) {
    return String(valor == null ? "" : valor).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fecha(valor, conHora) {
    if (!valor) return "—";
    var texto = String(valor);
    if (/^\d{4}-\d{2}-\d{2}$/.test(texto)) {
      var p = texto.split("-");
      return p[2] + "/" + p[1] + "/" + p[0];
    }
    var d = new Date(texto);
    if (isNaN(d)) return texto;
    var opciones = { timeZone: "America/Bogota", day: "2-digit", month: "2-digit", year: "numeric" };
    if (conHora !== false) { opciones.hour = "2-digit"; opciones.minute = "2-digit"; }
    return d.toLocaleString("es-CO", opciones);
  }

  function token() {
    try { return localStorage.getItem("access_token"); } catch (_) { return null; }
  }

  function rolSesion() {
    try {
      var t = token();
      if (!t) return "";
      var parte = t.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      var datos = JSON.parse(decodeURIComponent(atob(parte).split("").map(function (c) {
        return "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2);
      }).join("")));
      if (datos.exp && datos.exp * 1000 < Date.now()) return "";
      return String(datos.role_name || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    } catch (_) {
      return "";
    }
  }

  function mensajeDeError(cuerpo, estado) {
    if (cuerpo && typeof cuerpo.detail === "string") return cuerpo.detail;
    if (cuerpo && Array.isArray(cuerpo.detail)) {
      return cuerpo.detail.map(function (d) {
        var campo = (d.loc || []).slice(-1)[0];
        return (campo ? campo + ": " : "") + String(d.msg || "").replace(/^Value error, /, "");
      }).join(" · ");
    }
    if (estado === 429) return "Demasiadas solicitudes seguidas. Espera un momento.";
    return "No se pudo completar la operación (" + estado + ").";
  }

  // fetch con token (si hay) y errores en español. `opciones.json` envía JSON.
  async function api(ruta, opciones) {
    opciones = opciones || {};
    var cabeceras = Object.assign({}, opciones.headers || {});
    var t = token();
    if (t && !opciones.sinSesion) cabeceras.Authorization = "Bearer " + t;
    var cuerpo = opciones.body;
    if (opciones.json !== undefined) {
      cabeceras["Content-Type"] = "application/json";
      cuerpo = JSON.stringify(opciones.json);
    }
    var respuesta = await fetch(ruta, { method: opciones.method || (cuerpo ? "POST" : "GET"), headers: cabeceras, body: cuerpo });
    if (respuesta.status === 401 && t && !opciones.sinSesion && opciones.redirigir !== false) {
      window.location.href = "/login";
      throw new Error("La sesión expiró.");
    }
    if (opciones.archivo) {
      if (!respuesta.ok) {
        var e = null;
        try { e = await respuesta.json(); } catch (_) { /* sin cuerpo */ }
        throw new Error(mensajeDeError(e, respuesta.status));
      }
      return respuesta;
    }
    var datos = null;
    try { datos = await respuesta.json(); } catch (_) { datos = null; }
    if (!respuesta.ok) throw new Error(mensajeDeError(datos, respuesta.status));
    return datos;
  }

  async function descargar(respuesta, nombrePorDefecto) {
    var nombre = nombrePorDefecto;
    var disp = respuesta.headers.get("Content-Disposition") || "";
    var m = /filename="?([^";]+)"?/i.exec(disp);
    if (m) nombre = m[1];
    var blob = await respuesta.blob();
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = nombre;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
  }

  function chipSemaforo(clave) {
    if (!clave) return "";
    return '<span class="pq-chip ' + esc(clave) + '">' + esc(SEMAFORO[clave] || clave) + "</span>";
  }

  function chipEstado(estado) {
    return '<span class="pq-chip estado">' + esc(estado) + "</span>";
  }

  function mostrar(caja, tipo, texto) {
    if (!caja) return;
    caja.className = "pq-msg " + (tipo || "");
    caja.textContent = texto || "";
    if (!texto) caja.className = "pq-msg";
  }

  function dato(etiqueta, valor) {
    return '<div class="pq-dato"><span>' + esc(etiqueta) + "</span><b>" + (valor == null || valor === "" ? "—" : valor) + "</b></div>";
  }

  // Ficha de la PQRS: datos, descripción, respuesta, historial y adjuntos.
  function fichaHTML(p, opciones) {
    opciones = opciones || {};
    var html = "";
    html += '<div class="pq-heading"><div><span class="pq-kicker">' + esc(p.tipo) + "</span>" +
      '<h2 class="pq-radicado">' + esc(p.radicado) + "</h2></div>" +
      '<div class="pq-acciones">' + chipEstado(p.estado) + " " + chipSemaforo(p.semaforo) + "</div></div>";
    html += '<div class="pq-detalle-grid">' +
      dato("Asunto", esc(p.asunto)) +
      dato("Radicada", esc(fecha(p.fecha_radicacion))) +
      dato("Fecha límite de respuesta", esc(fecha(p.fecha_limite))) +
      dato("Canal", esc(p.canal)) +
      (opciones.interno ? dato("Peticionario", esc(p.nombre_peticionario) + "<br><small>" + esc(p.tipo_documento) + " " + esc(p.numero_documento) + "</small>") : "") +
      (opciones.interno ? dato("Contacto", esc(p.correo) + (p.telefono ? "<br>" + esc(p.telefono) : "")) : "") +
      (p.empresa_nombre || p.nit ? dato("Empresa", esc(p.empresa_nombre || "") + (p.nit ? " · NIT " + esc(p.nit) : "")) : "") +
      (opciones.interno ? dato("Responsable", esc(p.responsable || "Sin asignar")) : "") +
      (p.dias_habiles_restantes != null ? dato("Días hábiles restantes", esc(p.dias_habiles_restantes)) : "") +
      "</div>";
    html += '<div class="pq-seccion"><h4>Descripción</h4><div class="pq-texto">' + esc(p.descripcion) + "</div></div>";
    if (p.informacion_solicitada) {
      html += '<div class="pq-seccion"><h4>Información que te pedimos</h4><div class="pq-texto">' + esc(p.informacion_solicitada) + "</div></div>";
    }
    if (p.respuesta) {
      html += '<div class="pq-seccion"><h4>Respuesta</h4><div class="pq-texto">' + esc(p.respuesta) + "</div>" +
        (p.fecha_respuesta ? "<small>Respondida el " + esc(fecha(p.fecha_respuesta)) + "</small>" : "") + "</div>";
    }
    var adjuntos = p.adjuntos || [];
    html += '<div class="pq-seccion"><h4>Adjuntos (' + adjuntos.length + ")</h4>";
    html += adjuntos.length
      ? '<ul class="pq-adjuntos">' + adjuntos.map(function (a) {
          return '<li><button type="button" data-adjunto="' + esc(a.id_adjunto) + '" data-nombre="' + esc(a.nombre_archivo) + '">' +
            esc(a.nombre_archivo) + "</button> <small>· " + (a.origen === "gestion" ? "CertiSENA" : "Peticionario") +
            " · " + esc(fecha(a.fecha_subida)) + "</small></li>";
        }).join("") + "</ul>"
      : '<p class="pq-ayuda" style="color:var(--gris-500);font-size:13px;margin:0">Sin adjuntos.</p>';
    html += "</div>";
    var historial = p.historial || [];
    if (historial.length) {
      html += '<div class="pq-seccion"><h4>Historial</h4><ol class="pq-linea">' + historial.map(function (h) {
        var cambio = h.estado_nuevo && h.estado_anterior && h.estado_nuevo !== h.estado_anterior
          ? " · " + esc(h.estado_anterior) + " → " + esc(h.estado_nuevo) : "";
        return "<li><strong>" + esc(ACCIONES[h.accion] || h.accion) + "</strong>" + cambio +
          "<br><time>" + esc(fecha(h.fecha)) + " · " + esc(h.actor) + "</time>" +
          (h.comentario ? "<p>" + esc(h.comentario) + "</p>" : "") + "</li>";
      }).join("") + "</ol></div>";
    }
    return html;
  }

  window.PQRS = {
    esc: esc, fecha: fecha, api: api, token: token, rolSesion: rolSesion, descargar: descargar,
    chipSemaforo: chipSemaforo, chipEstado: chipEstado, mostrar: mostrar, fichaHTML: fichaHTML,
    SEMAFORO: SEMAFORO
  };
})();
