/* =========================================================
   SOLICITUDES · ETAPAS "RADICADAS", "EN REVISIÓN" Y "TODAS"

   Código de la antigua pantalla static/revision-solicitudes.html
   (cola, detalle, validar sedes, exportar a Excel y PDF), movido a la
   pantalla unificada static/solicitudes.html (18/11/2026) y ampliado
   con el ciclo de la solicitud sobre endpoints que ya existían:

     · Radicada    -> "Pasar a revisión"      PATCH /solicitudes/{id}/estado (SOL-054)
     · En revisión -> revisar documentos        POST .../documentos/{id}/aprobar|rechazar|solicitar-correccion
                      (SOL-038/037/039), "Aprobar solicitud" y "Rechazar solicitud" (SOL-054)
     · Aprobada    -> "Ir a asignar auditor"    (etapa "Por asignar auditor")

   El Auxiliar tiene SOL-054 "con aprobación": el backend responde 202 y
   el cambio queda pendiente del Coordinador (o 200 si tiene el permiso
   delegado). Aquí solo se informa; las reglas siguen en el backend.

   "Todas" es el buscador general: texto, estado, norma, fechas e
   inicio/fin y ubicación (static/filtros-ubicacion.js), con paginador.
   ========================================================= */
(() => {
  "use strict";

  const token = localStorage.getItem("access_token");
  if (!token) return;

  const ESTADOS = ["Borrador", "Radicada", "En revision", "Aprobada", "Rechazada", "Cancelada", "Cerrada"];
  const normalizarEstado = (valor) => String(valor || "").normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/_/g, " ").trim().toLowerCase();
  const esEstado = (valor, canonico) => {
    const v = normalizarEstado(valor);
    const c = normalizarEstado(canonico);
    if (c === "en revision") return /revision/.test(v);
    return v.startsWith(c.slice(0, -1));           // "Aprobada" == "APROBADO"
  };

  const FILTROS = {
    radicadas: {
      vacio: "No hay solicitudes radicadas esperando revisión.",
      coincide: (e) => esEstado(e, "Radicada")
    },
    revision: {
      vacio: "No hay solicitudes en revisión. Pase a revisión una solicitud radicada para empezar.",
      coincide: (e) => esEstado(e, "En revision")
    },
    todas: {
      vacio: "No hay solicitudes para mostrar con los filtros actuales.",
      coincide: () => true
    }
  };

  const estado = {
    filtro: "radicadas",
    busqueda: "",
    estadoTodas: "",
    norma: "",
    desde: "",
    hasta: "",
    pagina: 1,
    porPagina: 10,
    solicitudes: [],
    empresas: {},
    normas: {},
    seleccionada: null,
    cargada: false,
    documentos: [],
    sedes: []
  };

  const $ = (selector) => document.querySelector(selector);

  async function peticion(ruta, opciones) {
    const datos = Object.assign({}, opciones || {}, {
      headers: Object.assign({ Authorization: "Bearer " + token }, (opciones && opciones.headers) || {})
    });
    const respuesta = await fetch(ruta, datos);
    if (respuesta.status === 401) {
      localStorage.clear();
      window.location.href = "/login";
      throw new Error("La sesión terminó.");
    }
    const tipo = respuesta.headers.get("content-type") || "";
    const cuerpo = tipo.includes("json") ? await respuesta.json().catch(() => null) : null;
    if (!respuesta.ok) {
      const detalle = cuerpo && cuerpo.detail;
      throw new Error(typeof detalle === "string" ? detalle : "No fue posible completar la solicitud (" + respuesta.status + ").");
    }
    return { status: respuesta.status, cuerpo };
  }
  const api = async (ruta, opciones) => (await peticion(ruta, opciones)).cuerpo;
  const enviarJson = (ruta, metodo, cuerpo) => peticion(ruta, {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cuerpo || {})
  });

  async function obtenerArchivo(ruta) {
    const respuesta = await fetch(ruta, { headers: { Authorization: "Bearer " + token } });
    if (!respuesta.ok) throw new Error("No se pudo obtener el archivo (" + respuesta.status + ").");
    return URL.createObjectURL(await respuesta.blob());
  }

  async function descargar(ruta, nombre) {
    try {
      const url = await obtenerArchivo(ruta);
      const enlace = document.createElement("a");
      enlace.href = url;
      enlace.download = nombre;
      document.body.appendChild(enlace);
      enlace.click();
      enlace.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (error) {
      mostrar(error.message, "error");
    }
  }

  async function verEnPestana(ruta) {
    // Se abre la pestaña antes de esperar la descarga: así el navegador no la bloquea.
    const ventana = window.open("", "_blank");
    try {
      const url = await obtenerArchivo(ruta);
      if (ventana) ventana.location.href = url; else window.location.href = url;
      setTimeout(() => URL.revokeObjectURL(url), 120000);
    } catch (error) {
      if (ventana) ventana.close();
      mostrar(error.message, "error");
    }
  }

  function mostrar(mensaje, tipo, accionHtml) {
    const caja = $("#feedback");
    caja.innerHTML = "";
    caja.className = "comite-feedback" + (mensaje ? " " + tipo : "");
    if (!mensaje) return;
    const texto = document.createElement("span");
    texto.textContent = mensaje;
    caja.appendChild(texto);
    if (accionHtml) caja.insertAdjacentHTML("beforeend", " " + accionHtml);
  }

  const esc = (valor) => String(valor == null ? "" : valor)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const fecha = (valor) => valor ? new Date(valor).toLocaleDateString("es-CO") : "-";
  const fact = (etiqueta, valor) => "<div><dt>" + esc(etiqueta) + "</dt><dd>" + esc(valor) + "</dd></div>";
  const valorONo = (valor) => valor === null || valor === undefined || valor === "" ? "No registrado" : valor;
  const estadoVisible = (valor) => /revision/i.test(normalizarEstado(valor)) ? "En revisión" : (valor || "-");

  function claseEstado(valor) {
    const texto = String(valor || "").toLowerCase();
    if (/(cancel|rechaz|inactiv|exclu)/.test(texto)) return "rejected";
    if (/(radicad|aprobad|validad|^activ)/.test(texto)) return "approved";
    return "pending";
  }
  const chip = (valor) => '<span class="comite-status ' + claseEstado(valor) + '">' + esc(estadoVisible(valor)) + "</span>";

  function nombreEmpresa(solicitud) {
    const empresa = estado.empresas[solicitud.id_empresa];
    return empresa ? empresa.nombre : "Sin empresa";
  }

  function codigoNorma(solicitud) {
    const norma = estado.normas[solicitud.id_norma];
    return norma ? norma.codigo || norma.nombre : "Sin norma";
  }

  const fechaSolicitud = (s) => s.fecha_radicacion || s.fecha || s.fecha_creacion;

  // ---------------- cola de solicitudes ----------------
  async function cargar() {
    $("#resultCount").textContent = "Cargando solicitudes...";
    try {
      // El listado admite 200 por página: se piden páginas hasta agotar (máx. 1000).
      const listarTodas = async () => {
        let lista = [];
        for (let desplazamiento = 0; desplazamiento < 1000; desplazamiento += 200) {
          const pagina = await api("/solicitudes/?limite=200&incluir_ubicacion=true&desplazamiento=" + desplazamiento) || [];
          lista = lista.concat(pagina);
          if (pagina.length < 200) break;
        }
        return lista;
      };
      const [todas, normas, empresas] = await Promise.all([
        listarTodas(),
        api("/solicitudes/normas").catch(() => []),
        api("/api/empresas/").catch(() => [])
      ]);
      estado.solicitudes = todas;
      estado.normas = Object.fromEntries((normas || []).map((n) => [n.id_norma, n]));
      estado.empresas = Object.fromEntries((empresas || []).map((e) => [String(e.id_empresa), e]));
      estado.cargada = true;
      llenarNormas();
      filtrosUbicacion.sugerir("ciudad", estado.solicitudes.map((s) => lugarSolicitud(s).ciudad));
      filtrosUbicacion.sugerir("departamento", estado.solicitudes.map((s) => s.sedes_departamentos || []));
      filtrosUbicacion.sugerir("pais", estado.solicitudes.map((s) => s.sedes_paises || []));
      renderizarCola();
    } catch (error) {
      estado.solicitudes = [];
      renderizarCola();
      mostrar(error.message, "error");
    }
  }

  function llenarNormas() {
    const select = $("#filtroNorma");
    const actual = select.value;
    const opciones = Object.values(estado.normas)
      .sort((a, b) => String(a.codigo || a.nombre).localeCompare(String(b.codigo || b.nombre)))
      .map((n) => '<option value="' + esc(n.id_norma) + '">' + esc([n.codigo, n.nombre].filter(Boolean).join(" · ")) + "</option>");
    select.innerHTML = '<option value="">Todas las normas</option>' + opciones.join("");
    select.value = actual;
  }

  // Búsqueda flexible: sin mayúsculas, tildes, guiones ni espacios. Si se
  // escribe solo un número se compara con el consecutivo del radicado sin
  // ceros a la izquierda ("1", "000001" y "0000001" encuentran ...-000001).
  function normalizarBusqueda(valor) {
    return String(valor || "").normalize("NFD").replace(/[̀-ͯ]/g, "")
      .toLowerCase().replace(/[^a-z0-9]/g, "");
  }
  function coincideBusqueda(valor, texto) {
    const v = normalizarBusqueda(valor);
    const q = normalizarBusqueda(texto);
    if (!q) return true;
    if (v.includes(q)) return true;
    if (/^\d+$/.test(q)) {
      const consecutivo = String(valor || "").match(/(\d+)\s*$/);
      return Boolean(consecutivo) && Number(consecutivo[1]) === Number(q);
    }
    return false;
  }

  function lugarSolicitud(s) {
    const empresa = estado.empresas[s.id_empresa] || {};
    return {
      ciudad: [empresa.ciudad].concat(s.sedes_ciudades || []),
      departamento: s.sedes_departamentos || [],
      pais: s.sedes_paises || []
    };
  }

  function diaLocal(valor) {
    if (!valor) return "";
    const d = new Date(valor);
    if (Number.isNaN(d.getTime())) return String(valor).slice(0, 10);
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  function visibles() {
    const { coincide } = FILTROS[estado.filtro];
    const texto = estado.busqueda;
    const ubicacion = estado.ubicacion || {};
    const enTodas = estado.filtro === "todas";
    return estado.solicitudes.filter((s) => {
      if (!coincide(s.estado || "")) return false;
      if (enTodas && estado.estadoTodas && !esEstado(s.estado, estado.estadoTodas)) return false;
      if (estado.norma && String(s.id_norma) !== estado.norma) return false;
      if (estado.desde || estado.hasta) {
        const dia = diaLocal(fechaSolicitud(s));
        if (!dia) return false;
        if (estado.desde && dia < estado.desde) return false;
        if (estado.hasta && dia > estado.hasta) return false;
      }
      if (!FiltrosUbicacion.cumple(ubicacion, lugarSolicitud(s))) return false;
      if (!texto) return true;
      const empresa = estado.empresas[s.id_empresa] || {};
      return [s.numero_radicado, empresa.nombre, empresa.nit, codigoNorma(s)].some((v) => coincideBusqueda(v, texto));
    });
  }

  function hayOtrosFiltros() {
    return Boolean(estado.busqueda || estado.norma || estado.desde || estado.hasta ||
      (estado.filtro === "todas" && estado.estadoTodas));
  }

  function accionFila(s) {
    if (esEstado(s.estado, "Radicada")) return "Revisar";
    if (esEstado(s.estado, "En revision")) return "Revisar";
    return "Ver";
  }

  function renderizarCola() {
    if (!estado.cargada) return;
    const lista = visibles();
    const ubicacion = estado.ubicacion || {};
    const total = lista.length;
    const totalPaginas = Math.max(1, Math.ceil(total / estado.porPagina));
    if (estado.pagina > totalPaginas) estado.pagina = totalPaginas;
    const inicio = (estado.pagina - 1) * estado.porPagina;
    const pagina = lista.slice(inicio, inicio + estado.porPagina);

    $("#resultCount").textContent = total + (total === 1 ? " solicitud" : " solicitudes");
    $("#solicitudesRevisionBody").innerHTML = pagina.length
      ? pagina.map((s) => '<tr' + (String(s.id_solicitud) === String(estado.seleccionada) ? ' class="fila-seleccionada"' : "") + ">" +
        "<td><strong>" + esc(s.numero_radicado || "Borrador") + "</strong><br><span class=\"comite-muted\">" + fecha(fechaSolicitud(s)) + "</span></td>" +
        "<td>" + esc(nombreEmpresa(s)) + "</td>" +
        "<td>" + esc(codigoNorma(s)) + "</td>" +
        "<td>" + chip(s.estado) + "</td>" +
        '<td><button class="btn btn-secundario btn-sm" type="button" data-revisar="' + esc(s.id_solicitud) + '">' + accionFila(s) + "</button></td>" +
        "</tr>").join("")
      : '<tr><td colspan="5"><div class="comite-table-empty">' + esc(FiltrosUbicacion.hayFiltros(ubicacion) && !hayOtrosFiltros()
        ? FiltrosUbicacion.mensajeVacio("solicitudes", ubicacion)
        : (hayOtrosFiltros() || FiltrosUbicacion.hayFiltros(ubicacion) ? FILTROS.todas.vacio : FILTROS[estado.filtro].vacio)) + "</div></td></tr>";
    filtrosUbicacion.anunciar(FiltrosUbicacion.hayFiltros(ubicacion)
      ? (total ? $("#resultCount").textContent + " en esa ubicación." : FiltrosUbicacion.mensajeVacio("solicitudes", ubicacion))
      : "");
    renderizarPaginador(total, totalPaginas);
  }

  function renderizarPaginador(total, totalPaginas) {
    const pager = $("#revisionPager");
    const botones = $("#revisionPagerButtons");
    botones.innerHTML = "";
    if (!total) { pager.style.display = "none"; return; }
    pager.style.display = "flex";
    const inicio = (estado.pagina - 1) * estado.porPagina + 1;
    const fin = Math.min(estado.pagina * estado.porPagina, total);
    $("#revisionPagerInfo").textContent = "Mostrando " + inicio + "-" + fin + " de " + total + " solicitudes";
    const boton = (texto, pagina, opciones) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "pager-btn" + (opciones && opciones.activo ? " active" : "");
      b.textContent = texto;
      b.disabled = Boolean(opciones && opciones.deshabilitado);
      if (opciones && opciones.etiqueta) b.setAttribute("aria-label", opciones.etiqueta);
      if (opciones && opciones.activo) b.setAttribute("aria-current", "page");
      b.addEventListener("click", () => { estado.pagina = pagina; renderizarCola(); });
      botones.appendChild(b);
    };
    boton("‹", estado.pagina - 1, { deshabilitado: estado.pagina <= 1, etiqueta: "Página anterior" });
    const paginas = [];
    const agregar = (p) => {
      const ultima = paginas[paginas.length - 1];
      if (ultima === p) return;
      if (typeof ultima === "number" && p - ultima > 1) paginas.push("…");
      paginas.push(p);
    };
    agregar(1);
    for (let p = estado.pagina - 1; p <= estado.pagina + 1; p++) if (p > 1 && p < totalPaginas) agregar(p);
    if (totalPaginas > 1) agregar(totalPaginas);
    paginas.forEach((p) => {
      if (p === "…") {
        const span = document.createElement("span");
        span.className = "pager-ellipsis";
        span.textContent = "…";
        botones.appendChild(span);
      } else {
        boton(String(p), p, { activo: p === estado.pagina, etiqueta: "Ir a la página " + p });
      }
    });
    boton("›", estado.pagina + 1, { deshabilitado: estado.pagina >= totalPaginas, etiqueta: "Página siguiente" });
  }

  // ---------------- detalle, documentos y decisiones ----------------
  async function cargarDetalle(id) {
    estado.seleccionada = id;
    renderizarCola();
    $("#detailPanel").innerHTML = '<div class="comite-loading">Cargando solicitud...</div>';
    try {
      const [info, sedes, documentos] = await Promise.all([
        api("/solicitudes/" + id + "/informacion-general"),
        api("/solicitudes/" + id + "/sedes"),
        api("/solicitudes/" + id + "/documentos").catch(() => null)
      ]);
      estado.sedes = sedes || [];
      estado.documentos = documentos;
      renderizarDetalle(info, estado.sedes, null);
      if (window.matchMedia("(max-width: 1100px)").matches) $("#detailPanel").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      $("#detailPanel").innerHTML = '<div class="comite-empty-state"><h3>No se pudo cargar la solicitud</h3><p>' + esc(error.message) + "</p></div>";
      mostrar(error.message, "error");
    }
  }

  const ESTADO_DOC = {
    Pendiente: "Pendiente de revisión",
    Aprobado: "Aprobado",
    Rechazado: "Rechazado",
    Correccion: "Corrección solicitada"
  };

  function htmlDocumentos(enRevision) {
    const docs = estado.documentos;
    if (docs === null) return '<p class="comite-muted">No se pudieron consultar los documentos.</p>';
    if (!docs.length) return '<p class="comite-muted">La empresa no ha adjuntado documentos.</p>';
    return '<ul class="comite-item-list documentos-revision">' + docs.map((d) => {
      const acciones = [];
      acciones.push('<button type="button" class="btn btn-secundario btn-sm" data-doc-ver="' + esc(d.id_documento) + '">Ver</button>');
      if (enRevision) {
        if (d.estado !== "Aprobado") acciones.push('<button type="button" class="btn btn-primario btn-sm" data-doc-accion="aprobar" data-doc="' + esc(d.id_documento) + '">Aprobar</button>');
        if (d.estado !== "Correccion") acciones.push('<button type="button" class="btn btn-secundario btn-sm" data-doc-accion="solicitar-correccion" data-doc="' + esc(d.id_documento) + '">Pedir corrección</button>');
        if (d.estado !== "Rechazado") acciones.push('<button type="button" class="btn btn-peligro-contorno btn-sm" data-doc-accion="rechazar" data-doc="' + esc(d.id_documento) + '">Rechazar</button>');
      }
      return "<li><strong>" + esc(d.tipo_documento) + "</strong>" +
        "<span>" + esc(d.nombre_archivo) + " · versión " + esc(d.version) + " " +
        '<span class="comite-status ' + (d.estado === "Aprobado" ? "approved" : d.estado === "Rechazado" ? "rejected" : "pending") + '">' +
        esc(ESTADO_DOC[d.estado] || d.estado) + "</span></span>" +
        (d.observaciones ? '<span class="comite-muted">Observación: ' + esc(d.observaciones) + "</span>" : "") +
        '<span class="documento-acciones">' + acciones.join("") + "</span></li>";
    }).join("") + "</ul>";
  }

  function resumenDocumentos() {
    const docs = estado.documentos || [];
    const sinAprobar = docs.filter((d) => d.estado !== "Aprobado");
    return { total: docs.length, sinAprobar: sinAprobar.length };
  }

  function renderizarDetalle(info, sedes, validacion) {
    estado.info = info;
    const validable = !["Borrador", "Cancelada"].includes(info.estado);
    const radicada = esEstado(info.estado, "Radicada");
    const enRevision = esEstado(info.estado, "En revision");
    const aprobada = esEstado(info.estado, "Aprobada");

    const listaSedes = sedes.length
      ? '<ul class="comite-item-list">' + sedes.map((s) =>
        "<li><strong>" + esc(s.nombre_sede) + (s.es_principal ? " (principal)" : "") + "</strong>" +
        "<span>" + esc([s.ciudad, s.departamento].filter(Boolean).join(", ") || "Sin ubicación") + " " +
        chip(s.estado_sede === "Inactiva" ? "Inactiva" : s.estado_en_solicitud) + "</span></li>").join("") + "</ul>"
      : '<p class="comite-muted">La solicitud no tiene sedes incluidas.</p>';

    let resultado = "";
    if (validacion) {
      resultado = '<div class="comite-detail-section"><h4>Resultado de la validación</h4>' +
        (validacion.valida
          ? '<p class="comite-readonly-note">Todas las sedes están completas y coinciden con lo declarado.</p>'
          : '<ul class="comite-item-list">' + validacion.inconsistencias.map((i) => "<li><span>" + esc(i) + "</span></li>").join("") + "</ul>") +
        "</div>";
    }

    // Paso siguiente del ciclo según el estado.
    let ciclo = "";
    if (radicada) {
      ciclo = '<p class="comite-muted">Paso siguiente: tomar la solicitud para revisar sus documentos.</p>' +
        '<div class="comite-decision-actions"><button type="button" class="comite-button primary btn btn-primario" data-ciclo="revision">Pasar a revisión</button></div>';
    } else if (enRevision) {
      const r = resumenDocumentos();
      ciclo = '<p class="comite-muted">' + (r.total
        ? (r.sinAprobar ? r.sinAprobar + " de " + r.total + " documento(s) sin aprobar." : "Todos los documentos están aprobados.")
        : "Sin documentos adjuntos.") + " Pida correcciones desde cada documento.</p>" +
        '<div class="comite-decision-actions">' +
        '<button type="button" class="comite-button primary btn btn-primario" data-ciclo="aprobar">Aprobar solicitud</button>' +
        '<button type="button" class="comite-button btn btn-peligro-contorno" data-ciclo="rechazar">Rechazar solicitud</button></div>';
    } else if (aprobada) {
      ciclo = '<p class="comite-muted">Solicitud aprobada: el paso siguiente es asignarle un auditor.</p>' +
        '<div class="comite-decision-actions"><button type="button" class="comite-button primary btn btn-primario" data-ir-asignar="1">Ir a asignar auditor</button></div>';
    }

    $("#detailPanel").innerHTML =
      '<div class="comite-detail-heading"><div><span class="comite-kicker">Solicitud seleccionada</span><h3>' +
      esc(info.numero_radicado || "Borrador") + "</h3></div>" + chip(info.estado) + "</div>" +
      '<dl class="comite-facts">' +
      fact("Empresa", info.empresa_nombre || "No registrada") +
      fact("NIT", info.empresa_nit || "No registrado") +
      fact("Norma", info.norma_codigo ? [info.norma_codigo, info.norma_version].filter(Boolean).join(" ") : "No registrada") +
      fact("Contacto", valorONo(info.persona_contacto)) +
      fact("Empleados", valorONo(info.numero_empleados)) +
      fact("Sedes declaradas / incluidas", valorONo(info.numero_sedes) + " / " + info.sedes_incluidas) +
      "</dl>" +
      (ciclo ? '<div class="comite-detail-section"><h4>Ciclo de la solicitud</h4>' + ciclo + "</div>" : "") +
      '<div class="comite-detail-section"><h4>Documentos (' + ((estado.documentos || []).length) + ")</h4>" + htmlDocumentos(enRevision) + "</div>" +
      '<div class="comite-detail-section"><h4>Sedes incluidas (' + sedes.length + ")</h4>" + listaSedes + "</div>" +
      resultado +
      '<div class="comite-detail-section"><h4>Acciones</h4>' +
      (validable ? "" : '<p class="comite-readonly-note">Solo se validan las sedes de solicitudes radicadas.</p>') +
      '<div class="comite-decision-actions">' +
      '<button id="validarButton" class="comite-button primary btn btn-primario" type="button"' + (validable ? "" : " disabled") + ">Validar sedes</button>" +
      '<button class="comite-button secondary btn btn-secundario" type="button" data-descargar="excel">Exportar sedes a Excel</button>' +
      '<button class="comite-button secondary btn btn-secundario" type="button" data-descargar="pdf">Descargar PDF</button>' +
      "</div></div>";
  }

  async function validar() {
    const id = estado.seleccionada;
    if (!id) return;
    try {
      const validacion = await api("/solicitudes/" + id + "/sedes/validar", { method: "POST" });
      const sedes = await api("/solicitudes/" + id + "/sedes");
      estado.sedes = sedes || [];
      renderizarDetalle(estado.info, estado.sedes, validacion);
      const total = validacion.inconsistencias.length;
      mostrar(
        validacion.valida
          ? "Sedes validadas sin observaciones."
          : "Validación registrada con " + total + (total === 1 ? " observación." : " observaciones."),
        validacion.valida ? "success" : "error"
      );
    } catch (error) {
      mostrar(error.message, "error");
    }
  }

  // ---------------- ventana de decisión (motivo / observación) ----------------
  const modal = {
    raiz: () => $("#decisionModal"),
    accion: null,
    origen: null
  };

  function abrirDecision(opciones) {
    modal.accion = opciones.alConfirmar;
    modal.minimo = opciones.minimo || 0;
    modal.origen = document.activeElement;
    $("#decisionTitulo").textContent = opciones.titulo;
    $("#decisionTexto").textContent = opciones.texto || "";
    $("#decisionEtiqueta").textContent = opciones.etiqueta || "Observación";
    const campo = $("#decisionCampo");
    campo.value = "";
    campo.placeholder = opciones.placeholder || "";
    campo.maxLength = opciones.maximo || 1000;
    campo.classList.remove("campo-invalido");
    campo.removeAttribute("aria-invalid");
    $("#decisionCampoBloque").hidden = Boolean(opciones.sinCampo);
    $("#decisionError").style.display = "none";
    const confirmar = $("#decisionConfirmar");
    confirmar.textContent = opciones.boton || "Confirmar";
    confirmar.className = "btn " + (opciones.peligro ? "btn-peligro" : "btn-primario");
    confirmar.disabled = false;
    modal.raiz().classList.add("show");
    setTimeout(() => (opciones.sinCampo ? confirmar : campo).focus(), 50);
  }

  function cerrarDecision() {
    modal.raiz().classList.remove("show");
    modal.accion = null;
    if (modal.origen && document.body.contains(modal.origen)) modal.origen.focus();
    modal.origen = null;
  }

  async function confirmarDecision() {
    if (!modal.accion) return;
    const campo = $("#decisionCampo");
    const texto = campo.value.trim();
    const error = $("#decisionError");
    if (!$("#decisionCampoBloque").hidden && texto.length < modal.minimo) {
      error.textContent = "Escriba al menos " + modal.minimo + " caracteres.";
      error.style.display = "block";
      campo.classList.add("campo-invalido");
      campo.setAttribute("aria-invalid", "true");
      campo.focus();
      return;
    }
    const boton = $("#decisionConfirmar");
    boton.disabled = true;
    try {
      await modal.accion(texto);
      cerrarDecision();
    } catch (e) {
      error.textContent = e.message;
      error.style.display = "block";
    } finally {
      boton.disabled = false;
    }
  }

  // ---------------- cambios de estado (SOL-054) ----------------
  async function cambiarEstado(nuevo, motivo) {
    const id = estado.seleccionada;
    const info = estado.info || {};
    const { status, cuerpo } = await enviarJson("/solicitudes/" + id + "/estado", "PATCH", { estado: nuevo, motivo: motivo || null });
    if (status === 202) {
      mostrar((cuerpo && cuerpo.mensaje) || "La acción quedó pendiente de aprobación del Coordinador.", "success");
      await cargarDetalle(id);
      return;
    }
    await cargar();
    recargarContadores();
    if (nuevo === "Aprobada") {
      mostrar("Solicitud " + (info.numero_radicado || "") + " aprobada. Ya puede asignarle un auditor.", "success",
        '<button type="button" class="btn btn-primario btn-sm" data-ir-asignar="1">Ir a asignar auditor</button>');
    } else if (nuevo === "En revision") {
      mostrar("La solicitud " + (info.numero_radicado || "") + " pasó a revisión.", "success",
        '<button type="button" class="btn btn-secundario btn-sm" data-ir-etapa="revision">Ver en "En revisión"</button>');
    } else {
      mostrar("La solicitud " + (info.numero_radicado || "") + " quedó en estado " + nuevo + ".", "success");
    }
    await cargarDetalle(id);
  }

  function accionCiclo(tipo) {
    const info = estado.info || {};
    const radicado = info.numero_radicado || "la solicitud";
    if (tipo === "revision") {
      abrirDecision({
        titulo: "Pasar a revisión",
        texto: "La solicitud " + radicado + " pasará a \"En revisión\" y la empresa ya no podrá cancelarla.",
        etiqueta: "Observación (opcional)",
        maximo: 500,
        boton: "Pasar a revisión",
        alConfirmar: (texto) => cambiarEstado("En revision", texto)
      });
    } else if (tipo === "aprobar") {
      const r = resumenDocumentos();
      abrirDecision({
        titulo: "Aprobar solicitud",
        texto: (r.sinAprobar
          ? "Atención: " + r.sinAprobar + " documento(s) aún no están aprobados. "
          : "") + "Al aprobar " + radicado + " queda lista para asignarle un auditor.",
        etiqueta: "Observación (opcional)",
        maximo: 500,
        boton: "Aprobar solicitud",
        alConfirmar: (texto) => cambiarEstado("Aprobada", texto)
      });
    } else if (tipo === "rechazar") {
      abrirDecision({
        titulo: "Rechazar solicitud",
        texto: "La empresa verá el motivo en el historial de " + radicado + ".",
        etiqueta: "Motivo del rechazo (obligatorio)",
        placeholder: "Explique por qué se rechaza (mínimo 10 caracteres)",
        minimo: 10,
        maximo: 500,
        peligro: true,
        boton: "Rechazar solicitud",
        alConfirmar: (texto) => cambiarEstado("Rechazada", texto)
      });
    }
  }

  // ---------------- revisión de documentos (SOL-037/038/039) ----------------
  function accionDocumento(accion, idDocumento) {
    const doc = (estado.documentos || []).find((d) => String(d.id_documento) === String(idDocumento));
    if (!doc) return;
    const ruta = "/solicitudes/" + estado.seleccionada + "/documentos/" + idDocumento + "/" + accion;
    const ejecutar = async (texto) => {
      await enviarJson(ruta, "POST", { observaciones: texto || null });
      estado.documentos = await api("/solicitudes/" + estado.seleccionada + "/documentos").catch(() => estado.documentos);
      renderizarDetalle(estado.info, estado.sedes, null);
      const textos = { aprobar: "aprobado", rechazar: "rechazado", "solicitar-correccion": "devuelto para corrección" };
      mostrar("Documento \"" + doc.tipo_documento + "\" " + textos[accion] + ".", "success");
    };
    if (accion === "aprobar") {
      abrirDecision({
        titulo: "Aprobar documento",
        texto: "\"" + doc.tipo_documento + "\" quedará aprobado y la empresa ya no podrá reemplazarlo.",
        etiqueta: "Observación (opcional)",
        boton: "Aprobar documento",
        alConfirmar: ejecutar
      });
    } else {
      const rechazar = accion === "rechazar";
      abrirDecision({
        titulo: rechazar ? "Rechazar documento" : "Pedir corrección",
        texto: "\"" + doc.tipo_documento + "\": la empresa verá este texto y podrá subir una versión nueva.",
        etiqueta: rechazar ? "Motivo del rechazo (obligatorio)" : "Corrección que debe hacer la empresa (obligatorio)",
        placeholder: "Mínimo 5 caracteres",
        minimo: 5,
        peligro: rechazar,
        boton: rechazar ? "Rechazar documento" : "Pedir corrección",
        alConfirmar: ejecutar
      });
    }
  }

  // ---------------- integración con la pantalla ----------------
  function recargarContadores() {
    if (window.SolicitudesEtapas) window.SolicitudesEtapas.recargarContadores();
  }

  function irAAsignar() {
    const info = estado.info || {};
    if (window.SolicitudesEtapas) {
      window.SolicitudesEtapas.ir("por-asignar", { solicitud: estado.seleccionada, radicado: info.numero_radicado || "" });
    }
  }

  function mostrarEtapa(filtro) {
    if (!FILTROS[filtro]) filtro = "radicadas";
    const cambio = estado.filtro !== filtro;
    estado.filtro = filtro;
    estado.pagina = cambio ? 1 : estado.pagina;
    const enTodas = filtro === "todas";
    $("#filtroEstadoBloque").hidden = !enTodas;
    if (cambio) mostrar("", "");
    if (!estado.cargada) {
      cargar();
    } else {
      renderizarCola();
    }
  }

  // ---------------- eventos ----------------
  $("#filtroEstado").innerHTML = '<option value="">Todos los estados</option>' +
    ESTADOS.map((e) => '<option value="' + esc(e) + '">' + esc(estadoVisible(e)) + "</option>").join("");

  $("#filtrosUbicacion").innerHTML = FiltrosUbicacion.html({
    prefijo: "revFiltro",
    panel: true,
    ayudas: { departamento: "De alguna sede incluida", pais: "De alguna sede incluida" }
  });
  const filtrosUbicacion = FiltrosUbicacion.ligar($("#filtrosUbicacion"), {
    prefijo: "revFiltro",
    alCambiar: (valores) => { estado.ubicacion = valores; estado.pagina = 1; renderizarCola(); }
  });

  const alFiltrar = () => { estado.pagina = 1; renderizarCola(); };
  $("#searchForm").addEventListener("submit", (evento) => {
    evento.preventDefault();
    estado.busqueda = $("#searchInput").value.trim();
    alFiltrar();
  });
  $("#searchInput").addEventListener("input", () => {
    estado.busqueda = $("#searchInput").value.trim();
    alFiltrar();
  });
  $("#filtroEstado").addEventListener("change", (e) => { estado.estadoTodas = e.target.value; alFiltrar(); });
  $("#filtroNorma").addEventListener("change", (e) => { estado.norma = e.target.value; alFiltrar(); });
  // Fecha inicio <= Fecha fin: cada selector limita al otro.
  $("#filtroDesde").addEventListener("change", (e) => {
    estado.desde = e.target.value || "";
    $("#filtroHasta").min = estado.desde;
    alFiltrar();
  });
  $("#filtroHasta").addEventListener("change", (e) => {
    estado.hasta = e.target.value || "";
    $("#filtroDesde").max = estado.hasta;
    alFiltrar();
  });
  $("#limpiarFiltrosRevision").addEventListener("click", () => {
    ["#searchInput", "#filtroEstado", "#filtroNorma", "#filtroDesde", "#filtroHasta"].forEach((s) => { $(s).value = ""; });
    $("#filtroDesde").max = "";
    $("#filtroHasta").min = "";
    Object.assign(estado, { busqueda: "", estadoTodas: "", norma: "", desde: "", hasta: "" });
    filtrosUbicacion.limpiar(true);
    estado.ubicacion = {};
    alFiltrar();
  });
  $("#revisionPageSize").addEventListener("change", (e) => {
    estado.porPagina = Number(e.target.value) || 10;
    alFiltrar();
  });

  $("#solicitudesRevisionBody").addEventListener("click", (evento) => {
    const boton = evento.target.closest("[data-revisar]");
    if (boton) cargarDetalle(boton.dataset.revisar);
  });

  $("#detailPanel").addEventListener("click", (evento) => {
    if (evento.target.closest("#validarButton")) return validar();
    const ciclo = evento.target.closest("[data-ciclo]");
    if (ciclo) return accionCiclo(ciclo.dataset.ciclo);
    if (evento.target.closest("[data-ir-asignar]")) return irAAsignar();
    const doc = evento.target.closest("[data-doc-accion]");
    if (doc) return accionDocumento(doc.dataset.docAccion, doc.dataset.doc);
    const ver = evento.target.closest("[data-doc-ver]");
    if (ver) return verEnPestana("/solicitudes/" + estado.seleccionada + "/documentos/" + ver.dataset.docVer + "/ver");
    const boton = evento.target.closest("[data-descargar]");
    if (!boton || !estado.seleccionada) return;
    const radicado = (estado.info && estado.info.numero_radicado) || "borrador";
    if (boton.dataset.descargar === "excel") {
      descargar("/solicitudes/" + estado.seleccionada + "/sedes/excel", "sedes-" + radicado + ".xlsx");
    } else {
      descargar("/solicitudes/" + estado.seleccionada + "/pdf", radicado + ".pdf");
    }
  });

  $("#feedback").addEventListener("click", (evento) => {
    if (evento.target.closest("[data-ir-asignar]")) return irAAsignar();
    const etapa = evento.target.closest("[data-ir-etapa]");
    if (etapa && window.SolicitudesEtapas) window.SolicitudesEtapas.ir(etapa.dataset.irEtapa);
  });

  $("#decisionCancelar").addEventListener("click", cerrarDecision);
  $("#decisionConfirmar").addEventListener("click", confirmarDecision);
  $("#decisionModal").addEventListener("keydown", (evento) => { if (evento.key === "Escape") cerrarDecision(); });
  $("#decisionModal").addEventListener("click", (evento) => { if (evento.target.id === "decisionModal") cerrarDecision(); });

  $("#refreshButton").addEventListener("click", async () => {
    await cargar();
    recargarContadores();
    if (estado.seleccionada) cargarDetalle(estado.seleccionada);
  });

  window.SolicitudesRevision = {
    mostrar: mostrarEtapa,
    recargar: async () => { if (estado.cargada) await cargar(); }
  };
})();
