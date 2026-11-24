/* =========================================================
   FORMULARIO DE SEDE EN VENTANA MODAL (componente comun)

   Es el mismo formulario que tenia la seccion "Mi empresa"
   (static/empresas.html): mismos campos, mismas validaciones,
   mismos mensajes y mismos endpoints (EMP-021 / EMP-022):

     Registrar: POST /api/empresas/{id}/sedes
     Editar:    PUT  /api/empresas/{id}/sedes/{id_sede}

   Lo usan el portal de empresa (static/empresa.html, vista Sedes y
   panel "Antes de solicitar la certificacion") y la gestion de
   empresas del Coordinador/Auxiliar (static/empresas.html).

   Uso:
     SedeForm.abrir({
       enviar: (ruta, metodo, cuerpo) => Promise,  // el de la pantalla
       idEmpresa: "uuid",
       empresas: [{ id_empresa, nombre, nit }],    // opcional: si hay
                                                   // varias, se elige aqui
       sede: { ...sede },                          // opcional: editar
       nota: "texto bajo el titulo",               // opcional
       alGuardar: ({ sede, mensaje, editada, idEmpresa }) => {}
     });

   La ventana es accesible (role="dialog", aria-modal, foco en el
   primer campo, Tab atrapado y Escape por static/modales.js) y los
   errores salen dentro de ella, junto a los botones.
   ========================================================= */
(function () {
  "use strict";
  if (window.SedeForm) return;

  var abierta = null;

  function esc(valor) {
    return String(valor == null ? "" : valor)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // Mismos ayudantes que static/empresas.html.
  function campo(id, etiqueta, valor, clase, tipo) {
    return '<div class="' + (clase || "") + '"><label for="' + id + '">' + etiqueta + "</label>" +
      '<input id="' + id + '" type="' + (tipo || "text") + '" value="' + esc(valor == null ? "" : valor) + '"></div>';
  }

  function selector(id, etiqueta, opciones, valor, clase) {
    return '<div class="' + (clase || "") + '"><label for="' + id + '">' + etiqueta + '</label><select id="' + id + '">' +
      opciones.map(function (o) {
        return '<option value="' + esc(o[0]) + '"' + (o[0] === valor ? " selected" : "") + ">" + esc(o[1]) + "</option>";
      }).join("") + "</select></div>";
  }

  function fact(etiqueta, valor) {
    return "<div><dt>" + esc(etiqueta) + "</dt><dd>" + esc(valor) + "</dd></div>";
  }

  function campos(sede, empresas, idEmpresa) {
    if (sede) {
      return '<dl class="comite-facts">' + fact("Ciudad", sede.ciudad) + fact("Departamento", sede.departamento || "-") + fact("País", sede.pais || "-") + "</dl>" +
        '<p class="comite-readonly-note">Ciudad, departamento y país no se pueden cambiar. Si están mal, inactive la sede y registre otra.</p>' +
        '<div class="portal-form-grid" style="margin-top:14px">' +
        campo("sedeFormNombre", "Nombre de la sede", sede.nombre_sede) +
        selector("sedeFormPrincipal", "Sede principal", [["false", "No"], ["true", "Sí"]], String(Boolean(sede.es_principal))) +
        campo("sedeFormDireccion", "Dirección", sede.direccion) +
        selector("sedeFormEstado", "Estado", [["Activa", "Activa"], ["Inactiva", "Inactiva"]], sede.estado || "Activa") +
        "</div>";
    }
    var lista = empresas || [];
    var elegirEmpresa = lista.length > 1
      ? selector("sedeFormEmpresa", "Empresa", lista.map(function (e) {
        return [String(e.id_empresa), e.nombre + (e.nit ? " · NIT " + e.nit : "")];
      }), String(idEmpresa || lista[0].id_empresa), "full")
      : "";
    return '<div class="portal-form-grid">' + elegirEmpresa +
      campo("sedeFormNombre", "Nombre de la sede", "") +
      selector("sedeFormPrincipal", "Sede principal", [["false", "No"], ["true", "Sí"]], "false") +
      campo("sedeFormDireccion", "Dirección", "", "full") +
      campo("sedeFormCiudad", "Ciudad", "") + campo("sedeFormDepartamento", "Departamento", "") + campo("sedeFormPais", "País", "Colombia") +
      '<p class="full comite-readonly-note" style="margin-top:0">Ciudad, departamento y país solo se indican ahora: después no se pueden cambiar.</p>' +
      "</div>";
  }

  function val(modal, id) {
    var el = modal.querySelector("#" + id);
    return el ? el.value.trim() : "";
  }

  function soloLetrasYEspacios(valor) {
    return /^[\p{L} ]+$/u.test(valor);
  }

  // Misma lógica que guardarSede() de empresas.html.
  async function guardar(modal, opciones) {
    var sede = opciones.sede;
    var idEmpresa = val(modal, "sedeFormEmpresa") || String(opciones.idEmpresa || "");
    if (!idEmpresa) throw new Error("No se encontró la empresa de la sede.");
    var base = "/api/empresas/" + idEmpresa;

    if (sede) {
      var actualizada = await opciones.enviar(base + "/sedes/" + sede.id_sede, "PUT", {
        nombre_sede: val(modal, "sedeFormNombre"),
        direccion: val(modal, "sedeFormDireccion"),
        es_principal: val(modal, "sedeFormPrincipal") === "true",
        estado: val(modal, "sedeFormEstado")
      });
      return { sede: actualizada, mensaje: "Sede actualizada.", editada: true, idEmpresa: idEmpresa };
    }

    var cuerpo = {
      nombre_sede: val(modal, "sedeFormNombre"),
      direccion: val(modal, "sedeFormDireccion"),
      ciudad: val(modal, "sedeFormCiudad"),
      departamento: val(modal, "sedeFormDepartamento") || null,
      pais: val(modal, "sedeFormPais") || null,
      es_principal: val(modal, "sedeFormPrincipal") === "true",
      estado: "Activa"
    };
    if (!cuerpo.nombre_sede || !cuerpo.direccion || !cuerpo.ciudad) throw new Error("Nombre, dirección y ciudad son obligatorios.");
    if (!soloLetrasYEspacios(cuerpo.ciudad)) throw new Error("La ciudad solo puede contener letras y espacios.");
    if (cuerpo.departamento && !soloLetrasYEspacios(cuerpo.departamento)) {
      throw new Error("El departamento solo puede contener letras y espacios.");
    }
    var aviso = "Ciudad: " + cuerpo.ciudad + "\nDepartamento: " + (cuerpo.departamento || "-") + "\nPaís: " + (cuerpo.pais || "Colombia") +
      "\n\nEstos datos no se podrán cambiar después. ¿Son correctos?";
    if (!window.confirm(aviso)) return null;
    var creada = await opciones.enviar(base + "/sedes", "POST", cuerpo);
    return { sede: creada, mensaje: "Sede registrada.", editada: false, idEmpresa: idEmpresa };
  }

  function cerrar() {
    if (!abierta) return;
    var actual = abierta;
    abierta = null;
    actual.modal.remove();
    var opener = actual.opener;
    if (opener && opener.isConnected && typeof opener.focus === "function") {
      try { opener.focus({ preventScroll: true }); } catch (_) { opener.focus(); }
    }
  }

  function abrir(opciones) {
    opciones = opciones || {};
    if (typeof opciones.enviar !== "function") throw new Error("SedeForm.abrir necesita la función enviar.");
    cerrar();

    var sede = opciones.sede || null;
    var titulo = sede ? "Editar sede: " + sede.nombre_sede : "Registrar sede";
    var modal = document.createElement("div");
    modal.className = "modal-overlay";
    modal.setAttribute("data-modal", "sede");
    modal.setAttribute("role", "dialog");
    modal.setAttribute("aria-modal", "true");
    modal.setAttribute("aria-labelledby", "sedeFormTitulo");
    modal.innerHTML =
      '<div class="modal-card" style="width:640px;max-width:calc(100% - 32px);max-height:calc(100vh - 32px);overflow:auto">' +
      '<form id="sedeFormModal" novalidate>' +
      '<h3 id="sedeFormTitulo">' + esc(titulo) + "</h3>" +
      (opciones.nota ? '<p class="comite-muted" style="margin:0 0 14px">' + esc(opciones.nota) + "</p>" : "") +
      campos(sede, opciones.empresas, opciones.idEmpresa) +
      '<div id="sedeFormError" class="comite-feedback" role="alert" style="margin:14px 0 0"></div>' +
      '<div class="comite-decision-actions">' +
      '<button class="comite-button primary btn btn-primario" type="submit">' + (sede ? "Guardar cambios" : "Registrar sede") + "</button>" +
      '<button class="comite-button secondary btn btn-secundario" type="button" data-cerrar>Cancelar</button>' +
      "</div></form></div>";

    abierta = {
      modal: modal,
      opener: document.activeElement && document.activeElement !== document.body ? document.activeElement : null
    };
    document.body.appendChild(modal);

    var form = modal.querySelector("form");
    var error = modal.querySelector("#sedeFormError");
    var botonGuardar = form.querySelector('button[type="submit"]');

    function mostrarError(mensaje) {
      error.textContent = mensaje || "";
      error.className = "comite-feedback" + (mensaje ? " error" : "");
    }

    modal.querySelector("[data-cerrar]").addEventListener("click", cerrar);
    // Clic en el fondo oscuro: cierra (no en la tarjeta).
    modal.addEventListener("mousedown", function (ev) { if (ev.target === modal) cerrar(); });
    // Escape: si static/modales.js no está cargado, lo resuelve el propio componente.
    modal.addEventListener("keydown", function (ev) {
      if ((ev.key === "Escape" || ev.key === "Esc") && !ev.defaultPrevented) {
        ev.preventDefault();
        cerrar();
      }
    });

    form.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      mostrarError("");
      botonGuardar.disabled = true;
      try {
        var resultado = await guardar(modal, opciones);
        if (!resultado) return;          // canceló la confirmación
        cerrar();
        if (typeof opciones.alGuardar === "function") await opciones.alGuardar(resultado);
      } catch (e) {
        mostrarError((e && e.message) || "No fue posible guardar la sede.");
      } finally {
        if (botonGuardar.isConnected) botonGuardar.disabled = false;
      }
    });

    var primero = modal.querySelector("input, select");
    if (primero) primero.focus();
    return modal;
  }

  window.SedeForm = { abrir: abrir, cerrar: cerrar };
})();
