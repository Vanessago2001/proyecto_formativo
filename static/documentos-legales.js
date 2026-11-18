/* =========================================================
   DOCUMENTOS LEGALES DE LA EMPRESA (componente comun)

   Tabla de documentos de existencia de la empresa (RUT, Camara de
   Comercio, Representacion Legal y los opcionales) con su estado,
   fecha de carga, Ver / Descargar y Subir / Reemplazar.

   Lo usan el portal de empresa (static/empresa.html, vista
   "Documentos legales") y "Mi empresa" (static/empresas.html, rol
   Empresa). Endpoints (modules/empresas):

     GET  /api/empresas/{id}/documentos/tipos
     GET  /api/empresas/{id}/documentos
     GET  /api/empresas/{id}/requisitos
     POST /api/empresas/{id}/documentos               (subir, EMP-011)
     PUT  /api/empresas/{id}/documentos/{id_doc}      (reemplazar, EMP-012)
     GET  /api/empresas/{id}/documentos/{id_doc}/archivo  (ver/descargar)

   Uso:
     await DocumentosLegales.pintar(contenedor, {
       api,                 // fetch con token de la pantalla (lanza Error)
       token,               // para Ver / Descargar el archivo
       idEmpresa,
       mostrar,             // (mensaje, tipo) aviso de la pantalla
       alCambiar: (req) => {}  // tras subir/reemplazar (opcional)
     });
   Devuelve los requisitos (GET /requisitos) de la empresa.
   ========================================================= */
(function () {
  "use strict";
  if (window.DocumentosLegales) return;

  var MODIFICABLES = ["Pendiente", "Rechazado", "Correccion"];

  function esc(valor) {
    return String(valor == null ? "" : valor)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function claseEstado(valor) {
    var texto = String(valor || "").toLowerCase();
    if (/(cancel|rechaz|inactiv|exclu|correcci|vencid)/.test(texto)) return "rejected";
    if (/(radicad|aprobad|validad|^activ|completo)/.test(texto)) return "approved";
    return "pending";
  }

  function chip(valor) {
    return '<span class="comite-status ' + claseEstado(valor) + '">' + esc(valor || "-") + "</span>";
  }

  function fecha(valor) {
    return valor ? new Date(valor).toLocaleDateString("es-CO") : "-";
  }

  function boton(accion, texto, id) {
    return '<button class="btn btn-sm btn-secundario" type="button" data-legal-accion="' + accion + '" data-id="' + esc(id) + '">' + texto + "</button>";
  }

  async function archivo(opciones, idDocumento, nombre, abrir) {
    try {
      var ruta = "/api/empresas/" + opciones.idEmpresa + "/documentos/" + idDocumento + "/archivo";
      var respuesta = await fetch(ruta, { headers: { Authorization: "Bearer " + opciones.token } });
      if (!respuesta.ok) {
        var cuerpo = await respuesta.json().catch(function () { return null; });
        throw new Error((cuerpo && typeof cuerpo.detail === "string") ? cuerpo.detail : "No fue posible abrir el documento (" + respuesta.status + ").");
      }
      var url = URL.createObjectURL(await respuesta.blob());
      if (abrir) {
        window.open(url, "_blank");
      } else {
        var enlace = document.createElement("a");
        enlace.href = url;
        enlace.download = nombre || "";
        document.body.appendChild(enlace);
        enlace.click();
        enlace.remove();
      }
      setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
    } catch (error) {
      opciones.mostrar(error.message, "error");
    }
  }

  async function subir(contenedor, opciones, entrada) {
    var archivoElegido = entrada.files[0];
    if (!archivoElegido) return;
    entrada.disabled = true;
    var datos = new FormData();
    datos.append("archivo", archivoElegido);
    var base = "/api/empresas/" + opciones.idEmpresa + "/documentos";
    try {
      if (entrada.dataset.reemplazar) {
        await opciones.api(base + "/" + entrada.dataset.reemplazar, { method: "PUT", body: datos });
      } else {
        datos.append("tipo_documento", entrada.dataset.tipoLegal);
        await opciones.api(base, { method: "POST", body: datos });
      }
      var req = await pintar(contenedor, opciones);
      if (typeof opciones.alCambiar === "function") opciones.alCambiar(req);
      opciones.mostrar("Documento \"" + entrada.dataset.tipoLegal + "\" guardado. Queda pendiente de revisión del Coordinador.", "success");
    } catch (error) {
      entrada.disabled = false;
      entrada.value = "";
      opciones.mostrar(error.message, "error");
    }
  }

  async function pintar(contenedor, opciones) {
    var base = "/api/empresas/" + opciones.idEmpresa;
    var resultados = await Promise.all([
      opciones.api(base + "/documentos/tipos"),
      opciones.api(base + "/documentos"),
      opciones.api(base + "/requisitos")
    ]);
    var tipos = resultados[0], documentos = resultados[1] || [], req = resultados[2];
    var obligatorios = tipos.obligatorios || req.documentos_obligatorios || [];

    var filas = tipos.tipos.map(function (tipo) {
      var obligatorio = obligatorios.indexOf(tipo) !== -1;
      var resumen = req.documentos.find(function (d) { return d.tipo_documento === tipo; });
      var actual = resumen && resumen.id_documento
        ? documentos.find(function (d) { return String(d.id_documento) === String(resumen.id_documento); })
        : documentos.find(function (d) { return d.tipo_documento === tipo; });
      var situacion = resumen ? resumen.estado : (actual ? actual.estado_validacion : null);
      var control;
      if (actual && situacion === "Aprobado") {
        control = '<span class="comite-muted">Aprobado: ya no se puede cambiar.</span>';
      } else {
        var reemplazar = actual && MODIFICABLES.indexOf(actual.estado_validacion) !== -1 && situacion !== "Vencido";
        control = '<input type="file" aria-label="' + esc((reemplazar ? "Reemplazar: " : "Subir: ") + tipo) + '" data-tipo-legal="' + esc(tipo) + '"' +
          (reemplazar ? ' data-reemplazar="' + esc(actual.id_documento) + '"' : "") + ' accept=".pdf,.doc,.docx,.jpg,.jpeg,.png">';
      }
      return "<tr><td><strong>" + esc(tipo) + "</strong></td><td>" + (obligatorio ? "Sí" : "No") + "</td>" +
        "<td>" + (actual ? esc(actual.nombre_archivo || "") + " (v" + esc(actual.version) + ") " : "") +
        chip(situacion ? (situacion === "Correccion" ? "Corrección pedida" : situacion) : "Sin subir") + "</td>" +
        "<td>" + (actual ? fecha(actual.fecha_subida) : "-") + "</td>" +
        "<td>" + esc((actual && actual.observaciones) || "-") + "</td>" +
        "<td>" + control + "</td>" +
        '<td><div class="acciones-tabla">' + (actual
          ? boton("ver", "Ver", actual.id_documento) + boton("descargar", "Descargar", actual.id_documento)
          : "-") + "</div></td></tr>";
    }).join("");

    contenedor.innerHTML = '<div class="comite-panel">' +
      '<div class="comite-panel-heading"><div><h3>Documentos legales de la empresa</h3><p>Obligatorios cargados: ' +
      req.documentos_al_dia + "/" + req.documentos_total + " · Aprobados por el Coordinador: " + req.documentos_aprobados + "/" + req.documentos_total +
      ". Formatos: PDF, Word, JPG o PNG · Máximo 10 MB.</p></div>" + chip(req.documentos_faltantes.length ? "Pendiente" : "Completo") + "</div>" +
      '<div class="comite-table-wrap"><table><thead><tr><th>Documento</th><th>Obligatorio</th><th>Situación</th><th>Cargado</th><th>Observaciones</th><th>Archivo</th><th>Acciones</th></tr></thead><tbody>' +
      filas + "</tbody></table></div>" +
      '<p class="comite-readonly-note" style="margin-top:12px">Un documento rechazado o con corrección pedida debe reemplazarse. Una vez aprobado ya no se puede cambiar.</p>' +
      "</div>";

    contenedor.querySelectorAll("input[data-tipo-legal]").forEach(function (entrada) {
      entrada.addEventListener("change", function () { subir(contenedor, opciones, entrada); });
    });
    contenedor.querySelectorAll("button[data-legal-accion]").forEach(function (b) {
      b.addEventListener("click", function () {
        var doc = documentos.find(function (d) { return String(d.id_documento) === b.dataset.id; }) || {};
        archivo(opciones, b.dataset.id, doc.nombre_archivo, b.dataset.legalAccion === "ver");
      });
    });
    return req;
  }

  window.DocumentosLegales = { pintar: pintar };
})();
