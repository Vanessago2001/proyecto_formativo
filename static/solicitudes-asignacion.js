/* =========================================================
   SOLICITUDES · ETAPAS "POR ASIGNAR AUDITOR" Y "CON AUDITORES"

   Código de la antigua pantalla static/asignacion-auditores.html
   (18/11/2026), movido sin cambiar sus reglas a la pantalla unificada
   static/solicitudes.html. Cambios: lo usa también el Auxiliar (el
   backend ya le permitía consultar y asignar; cancelar y resolver
   cambios siguen siendo solo del Coordinador), las listas se cargan
   al abrir su etapa y cada cambio refresca los contadores de etapas.
   Se carga como script clásico: los onclick del HTML usan sus
   funciones globales.
   ========================================================= */

    /* =========================================================
       AUTENTICACIÓN
    ========================================================= */

    function tokenPayload() {
      try {
        const token = localStorage.getItem("access_token");
        if (!token) return null;
        const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
        return JSON.parse(atob(payload));
      } catch (error) {
        console.error("No se pudo leer el token:", error);
        return null;
      }
    }

    const token = localStorage.getItem("access_token");
    const user = tokenPayload();

    if (!token || !user) {
      location.href = "/login";
    }

    // Rol de la sesión ("Administrador" es el nombre anterior de "Coordinador").
    const rolSesion = String((user && user.role_name) || "").trim().toLowerCase();
    const esCoordinador = ["coordinador", "administrador", "admin", "adm"].includes(rolSesion);
    // Puede gestionar asignaciones (consultar y asignar): Coordinador o Auxiliar.
    const isAdmin = esCoordinador || ["auxiliar", "aux"].includes(rolSesion);

    // Refresca los contadores de etapas de la pantalla (static/solicitudes.js).
    function refrescarContadores() {
      if (window.SolicitudesEtapas) window.SolicitudesEtapas.recargarContadores();
    }


    /* =========================================================
       ELEMENTOS
    ========================================================= */

    const adminView = document.getElementById("adminView");
    const regularView = document.getElementById("regularView");
    const welcomeTitle = document.getElementById("welcomeTitle");
    const roleDescription = document.getElementById("roleDescription");
    const headerAvatar = document.getElementById("headerAvatar");
    const message = document.getElementById("message");
    const solicitudSelect = document.getElementById("solicitud");

    const solicitudesUbicacionRaiz = document.getElementById("solicitudesUbicacionFiltros");
    solicitudesUbicacionRaiz.innerHTML = FiltrosUbicacion.html({
      prefijo: "sol",
      limpiar: false,
      estado: false,
      titulo: "Filtrar solicitudes por ubicación"
    });
    const filtrosSolicitudesUbicacion = FiltrosUbicacion.ligar(solicitudesUbicacionRaiz, {
      prefijo: "sol",
      retardo: 300,
      alCambiar: () => cargarSolicitudes(1)
    });

    const auditorUbicacionRaiz = document.getElementById("auditorUbicacionFiltros");
    auditorUbicacionRaiz.innerHTML = FiltrosUbicacion.html({
      prefijo: "auditor",
      campos: ["ciudad", "departamento"],
      etiquetas: { ciudad: "Ciudad de residencia", departamento: "Departamento de residencia" },
      limpiar: false,
      estado: false,
      titulo: "Filtrar auditores por ubicación"
    });
    const filtrosAuditoresUbicacion = FiltrosUbicacion.ligar(auditorUbicacionRaiz, {
      prefijo: "auditor",
      campos: ["ciudad", "departamento"],
      retardo: 300,
      alCambiar: () => loadAuditores(1)
    });

    const auditorSearchInput = document.getElementById("auditorSearch");
    const auditorCityFilter = filtrosAuditoresUbicacion.entradas.ciudad;
    const auditorDeptFilter = filtrosAuditoresUbicacion.entradas.departamento;
    // Solo se pinta la respuesta de la última búsqueda (las anteriores se cancelan).
    let abortoSolicitudes = null;
    let abortoAuditores = null;
    const valoresUbicacionAuditores = () => filtrosAuditoresUbicacion.valores();
    const auditorModalityFilter = document.getElementById("auditorModalityFilter");
    const auditorCompetenceFilter = document.getElementById("auditorCompetenceFilter");
    const auditorConflictFilter = document.getElementById("auditorConflictFilter");
    const auditorDescartarConflictos = document.getElementById("auditorDescartarConflictos");
    const auditorPageInfo = document.getElementById("auditorPageInfo");
    const auditorPrevPage = document.getElementById("auditorPrevPage");
    const auditorNextPage = document.getElementById("auditorNextPage");
    const applyAuditorFilters = document.getElementById("applyAuditorFilters");
    const clearAuditorFilters = document.getElementById("clearAuditorFilters");

    const assignBtn = document.getElementById("assignBtn");
    const clearBtn = document.getElementById("clearBtn");
    const requestInfo = document.getElementById("requestInfo");
    const auditorsSection = document.getElementById("auditorsSection");
    const auditorsList = document.getElementById("auditorsList");
    const auditorsCounter = document.getElementById("auditorsCounter");
    const validationBox = document.getElementById("validationBox");
    const assignmentsTableBody = document.getElementById("assignmentsTableBody");
    const assignmentCounter = document.getElementById("assignmentCounter");
    const emptyState = document.getElementById("emptyState");
    const tableLoading = document.getElementById("tableLoading");
    const assignmentForm = document.getElementById("assignmentForm");
    const assignmentsToggle = document.getElementById("assignmentsToggle");
    const assignmentsContent = document.getElementById("assignmentsContent");

    assignmentsToggle.addEventListener("click", () => {
      const expanded = assignmentsToggle.getAttribute("aria-expanded") === "true";
      assignmentsToggle.setAttribute("aria-expanded", String(!expanded));
      assignmentsContent.hidden = expanded;
    });


    /* =========================================================
       DATOS LOCALES
    ========================================================= */

    let solicitudes = [];
    let auditores = [];
    let auditorSeleccionado = null;
    let auditorAdvertenciaActual = null;
    const auditoresSeleccionados = new Map();
    const auditoresForzados = new Set();
    // Justificación escrita al confirmar "Sí, asignar de todas formas".
    const justificacionesForzado = new Map();
    const auditorRolesAsignados = new Map();

    let asignaciones = [];
    const asignacionesPagerState = { pagina: 1, porPagina: 5 };
    let paginaAuditores = 1;
    let paginaSolicitudes = 1;
    let totalPaginasAuditores = 0;
    let totalAuditoresFiltrados = 0;
    const tamanoPaginaAuditores = 12;


    /* =========================================================
       USUARIO
    ========================================================= */

    const currentName = user?.nombre || user?.name || user?.sub || "Usuario";
    const currentRole = user?.role_name || "Usuario";

    // El título de la pantalla lo pone static/solicitudes.js según la etapa.
    if (!isAdmin && roleDescription) roleDescription.textContent = "Acceso restringido";
    if (headerAvatar) {
      headerAvatar.textContent = currentName.charAt(0).toUpperCase();
    }


    /* =========================================================
       VISTA SEGÚN ROL
    ========================================================= */

    if (isAdmin) {
      adminView.style.display = "grid";
    } else {
      regularView.classList.add("show");
    }


    /* =========================================================
       HEADERS
    ========================================================= */

    function headers() {
      return {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + token
      };
    }


    /* =========================================================
       MENSAJES
    ========================================================= */

    let messageTimer = null;

    function showMessage(text, type = "success") {
      clearTimeout(messageTimer);
      message.textContent = text;
      message.className = "message show " + type;
      messageTimer = setTimeout(() => {
        message.className = "message";
        message.textContent = "";
      }, 5000);
    }


    /* =========================================================
       FORMATEAR FECHA
    ========================================================= */

    function formatDate(value) {
      if (!value) return "-";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleDateString("es-CO");
    }

    function formatDateTime(value) {
      if (!value) return "-";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleString("es-CO", { dateStyle: "short", timeStyle: "short" });
    }


    /* =========================================================
       CARGAR SOLICITUDES APROBADAS
    ========================================================= */

    async function loadSolicitudes() {
      if (solicitudSelect) solicitudSelect.innerHTML = '<option value="">Cargando solicitudes...</option>';
      try {
        const response = await fetch("/asignacion-auditores/solicitudes", { headers: headers() });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(typeof data.detail === "string" ? data.detail : "No se pudieron cargar las solicitudes.");
        }

        solicitudes = Array.isArray(data.items)
          ? data.items
          : (Array.isArray(data.asignaciones)
            ? data.asignaciones
            : (Array.isArray(data) ? data : []));

        const isTable = !!document.getElementById('solicitudesBody');
        if (isTable) {
          renderSolicitudesTable(solicitudes);
          const total = Number(data.total || 0);
          const totalPages = Number(data.total_pages || 1);
          const info = document.getElementById('solicitudesSummary');
          if (info) info.textContent = `Mostrando ${Math.min((paginaSolicitudes - 1) * 12 + 1, total)}-${Math.min(paginaSolicitudes * 12, total)} de ${total} solicitudes. Página ${paginaSolicitudes} de ${totalPages}.`;
          const prev = document.getElementById('solPrevPage');
          const next = document.getElementById('solNextPage');
          if (prev) prev.disabled = paginaSolicitudes <= 1;
          if (next) next.disabled = paginaSolicitudes >= totalPages;
          return;
        }

        if (!solicitudSelect) return;

        solicitudSelect.innerHTML = '<option value="">Seleccione una solicitud</option>';

        if (solicitudes.length === 0) {
          solicitudSelect.innerHTML = '<option value="">No hay solicitudes aprobadas</option>';
          return;
        }

        solicitudes.forEach((solicitud) => {
          const option = document.createElement("option");
          option.value = solicitud.id_solicitud;
          const radicado = solicitud.numero_radicado || "Sin radicado";
          const empresa = solicitud.empresa_nombre || "Empresa sin nombre";
          const norma = solicitud.norma_codigo || solicitud.norma_nombre || "Norma no disponible";
          option.textContent = `${radicado} - ${empresa} - ${norma}`;
          solicitudSelect.appendChild(option);
        });

      } catch (error) {
        console.error(error);
        if (solicitudSelect) solicitudSelect.innerHTML = '<option value="">Error al cargar solicitudes</option>';
        showMessage(error.message, "error");
      }
    }


    /* =========================================================
       MOSTRAR INFORMACIÓN SOLICITUD
    ========================================================= */

    function showRequestInfo(solicitud) {
      if (!solicitud) {
        requestInfo.classList.remove("show");
        return;
      }
      document.getElementById("infoRadicado").textContent = solicitud.numero_radicado || "Sin radicado";
      document.getElementById("infoEmpresa").textContent = solicitud.empresa_nombre || "No disponible";
      document.getElementById("infoNorma").textContent = solicitud.norma_codigo || solicitud.norma_nombre || "No disponible";
      document.getElementById("infoVersion").textContent = solicitud.norma_version || "No disponible";
      document.getElementById("infoEstado").textContent = solicitud.estado || "No disponible";
      document.getElementById("infoFechaSolicitud").textContent = formatDate(solicitud.fecha);
      requestInfo.classList.add("show");
      mostrarSedesSolicitud(solicitud);
    }

    /* Sedes de la solicitud (20/11/2026): el auditor se asigna a una
       solicitud que incluye la sede principal; el Coordinador puede agregar
       sedes a la solicitud aprobada. */
    let sedesSolicitudDe = "";
    async function mostrarSedesSolicitud(solicitud) {
      const destino = document.getElementById("infoSedes");
      const boton = document.getElementById("infoAgregarSede");
      if (!destino) return;
      const id = String(solicitud?.id_solicitud || "");
      sedesSolicitudDe = id;
      destino.textContent = "Cargando sedes…";
      if (boton) {
        boton.style.display = window.AgregarSedeSolicitud?.esCoordinador() ? "" : "none";
        boton.onclick = () => window.AgregarSedeSolicitud.abrir({
          idSolicitud: id,
          radicado: solicitud.numero_radicado,
          alAgregar: async (sede) => {
            await mostrarSedesSolicitud(solicitud);
            showMessage(`Sede "${sede?.nombre_sede || ""}" agregada a la solicitud.`, "success");
          }
        });
      }
      try {
        const res = await fetch(`/solicitudes/${encodeURIComponent(id)}/sedes`, { headers: headers() });
        const data = await res.json().catch(() => []);
        if (sedesSolicitudDe !== id) return;
        if (!res.ok) throw new Error(typeof data?.detail === "string" ? data.detail : "No se pudieron consultar las sedes.");
        const sedes = (Array.isArray(data) ? data : []).filter(s => s.estado_sede !== "Inactiva");
        if (!sedes.length) {
          destino.innerHTML = '<span style="color:#b42318;">La solicitud no tiene sedes incluidas: no se puede asignar auditor.</span>';
          return;
        }
        const filas = sedes.map(s =>
          `<div>${s.es_principal ? "<strong>Principal:</strong> " : ""}${escapeHTML(s.nombre_sede || "Sede")} — ${escapeHTML([s.direccion, s.ciudad, s.departamento].filter(Boolean).join(", "))}</div>`
        ).join("");
        const aviso = sedes.some(s => s.es_principal)
          ? ""
          : '<div style="color:#b42318;margin-top:4px;">Falta la sede principal de la empresa: agréguela para poder asignar auditor.</div>';
        destino.innerHTML = filas + aviso;
      } catch (error) {
        if (sedesSolicitudDe === id) destino.textContent = error.message;
      }
    }


    /* =========================================================
       OBTENER SOLICITUD SELECCIONADA
    ========================================================= */

    let solicitudSeleccionada = null;

    function getSelectedSolicitud() {
      return solicitudSeleccionada;
    }


    /* =========================================================
       CARGAR AUDITORES ELEGIBLES
    ========================================================= */

    async function loadAuditores(page = paginaAuditores) {
      const solicitud = getSelectedSolicitud();
      if (!solicitud) {
        auditorsSection.classList.remove("show");
        validationBox.classList.remove("show");
        auditorsList.innerHTML = "";
        auditorSeleccionado = null;
        auditorPageInfo.textContent = "Selecciona una solicitud para consultar auditores.";
        auditorPrevPage.disabled = true;
        auditorNextPage.disabled = true;
        updateAssignButton();
        return;
      }

      paginaAuditores = Math.max(1, page);
      auditorsList.innerHTML = '<div class="loading">Consultando candidatos...</div>';
      auditorsSection.classList.add("show");
      validationBox.classList.remove("show");

      try {
        const params = new URLSearchParams({
          page: String(paginaAuditores),
          page_size: String(tamanoPaginaAuditores)
        });
        if (auditorSearchInput.value.trim()) params.set("buscar", auditorSearchInput.value.trim());
        if (auditorCityFilter.value.trim()) params.set("ciudad", auditorCityFilter.value.trim());
        if (auditorDeptFilter.value.trim()) params.set("departamento", auditorDeptFilter.value.trim());
        if (auditorModalityFilter.value) params.set("modalidad", auditorModalityFilter.value);
        if (auditorCompetenceFilter.value) params.set("competencia", auditorCompetenceFilter.value);
        const conflictoFiltro = auditorDescartarConflictos?.checked ? "no" : (auditorConflictFilter?.value || "");
        if (conflictoFiltro) params.set("conflicto", conflictoFiltro);

        if (abortoAuditores) abortoAuditores.abort();
        const controlador = new AbortController();
        abortoAuditores = controlador;
        const response = await fetch(
          `/asignacion-auditores/solicitudes/${encodeURIComponent(solicitud.id_solicitud)}/auditores?${params.toString()}`,
          { headers: headers(), signal: controlador.signal }
        );
        const data = await response.json();
        if (!response.ok) {
          throw new Error(typeof data.detail === "string" ? data.detail : "No se pudieron consultar los auditores.");
        }

        auditores = Array.isArray(data.items) ? data.items : [];
        paginaAuditores = Number(data.page || 1);
        totalPaginasAuditores = Number(data.total_pages || 0);
        totalAuditoresFiltrados = Number(data.total || 0);
        auditorsCounter.textContent = `${totalAuditoresFiltrados} resultado(s)`;
        auditorPageInfo.textContent = totalAuditoresFiltrados
          ? `Página ${paginaAuditores} de ${totalPaginasAuditores} · ${totalAuditoresFiltrados} auditor(es)`
          : "No hay resultados para los filtros seleccionados.";
        auditorPrevPage.disabled = paginaAuditores <= 1 || totalPaginasAuditores === 0;
        auditorNextPage.disabled = paginaAuditores >= totalPaginasAuditores || totalPaginasAuditores === 0;
        renderAuditors(auditores);
        const ubicacionAud = valoresUbicacionAuditores();
        document.getElementById("auditorsEstado").textContent = FiltrosUbicacion.hayFiltros(ubicacionAud)
          ? (totalAuditoresFiltrados
            ? `${totalAuditoresFiltrados} auditor(es) en esa ubicación.`
            : FiltrosUbicacion.mensajeVacio("auditores que residan", ubicacionAud))
          : "";
        updateAssignButton();
      } catch (error) {
        if (error && error.name === "AbortError") return;
        console.error(error);
        auditores = [];
        auditorsList.innerHTML = `<div class="no-auditors">${escapeHTML(error.message)}</div>`;
        auditorsCounter.textContent = "0 resultados";
        auditorPageInfo.textContent = "No fue posible cargar los auditores.";
        auditorPrevPage.disabled = true;
        auditorNextPage.disabled = true;
      }
    }


    /* =========================================================
       RENDER AUDITORES
    ========================================================= */
    function renderAuditors(lista) {
      auditorsList.innerHTML = "";
      if (!lista.length) {
        const ubicacionAud = valoresUbicacionAuditores();
        const soloUbicacion = FiltrosUbicacion.hayFiltros(ubicacionAud) && !auditorSearchInput.value.trim() &&
          !auditorModalityFilter.value && !auditorCompetenceFilter.value && !auditorConflictFilter.value && !auditorDescartarConflictos.checked;
        auditorsList.innerHTML = '<div class="no-auditors">' + escapeHTML(soloUbicacion
          ? FiltrosUbicacion.mensajeVacio("auditores que residan", ubicacionAud)
          : "No hay auditores que coincidan con los filtros. Prueba con otros criterios.") + '</div>';
        return;
      }

      lista.forEach((auditor) => {
        const id = String(auditor.id_usuario);
        const seleccionado = auditoresSeleccionados.has(id);
        const card = document.createElement("div");
        card.className = `auditor-card${seleccionado ? " selected" : ""}${auditor.elegible ? "" : " ineligible"}`;
        card.dataset.auditorId = id;

        const estadoCompetencia = auditor.competencia_norma
          ? '<span class="check ok">Competencia vigente: ' + escapeHTML((auditor.norma_codigo ? auditor.norma_codigo + " - " : "") + (auditor.norma_nombre || "Sin nombre")) + '</span>'
          : '<span class="check fail">Sin competencia vigente</span>';
        const estadoConflicto = auditor.conflicto_interes
          ? '<span class="check fail">Conflicto de interés</span>'
          : '<span class="check ok">Sin conflicto</span>';
        const estadoAsignacion = auditor.ya_asignado
          ? '<span class="check fail">Ya asignado</span>'
          : '';
        const estadoElegibilidad = auditor.elegible
          ? '<span class="check ok">Elegible para asignación</span>'
          : '<span class="check fail">No elegible</span>';

        card.innerHTML = `
          <div class="auditor-header">
            <input type="checkbox" class="auditor-check-input"
              data-auditor-id="${escapeHTML(id)}"
              aria-label="Seleccionar ${escapeHTML(auditor.nombre || "auditor")}"
              ${seleccionado ? "checked" : ""}
              onchange="toggleAuditorCheckedById(this.dataset.auditorId, this.checked)" />
            <div>
              <button type="button" class="auditor-name auditor-name-btn" aria-haspopup="dialog" title="Ver detalle del auditor">${escapeHTML(auditor.nombre || "Sin nombre")}</button>
              <div class="auditor-email">${escapeHTML(auditor.correo || "Sin correo")}</div>
              <div class="auditor-meta">Documento: ${escapeHTML([auditor.tipo_doc, auditor.num_doc].filter(Boolean).join(" ") || "No registrado")}</div>
              <div class="auditor-meta">Ciudad: ${escapeHTML(auditor.ciudad_residencia || "No registrada")} · Modalidad: ${escapeHTML(auditor.modalidad_preferida || "No definida")}</div>
            </div>
          </div>
          <div class="auditor-checks">
            ${estadoElegibilidad}
            ${estadoCompetencia}
            ${estadoConflicto}
            ${estadoAsignacion}
            <span class="check">Disponibilidad y cruces: Agenda</span>
          </div>
          ${auditor.elegible ? "" : `<div class="eligibility-note">${escapeHTML(auditor.motivo || "No cumple las condiciones de asignación.")}</div>`}
          <div class="auditor-role-picker" style="display:${seleccionado ? "block" : "none"};margin-top:12px;color:#256d00;font-weight:700;" onclick="event.stopPropagation();">
            Se asignará como Auditor
          </div>`;

        card.addEventListener("click", (event) => {
          if (event.target?.type === "checkbox" || event.target?.closest(".auditor-role-picker")) return;
          abrirModalAuditor(auditor);
        });
        auditorsList.appendChild(card);
      });
    }


    /* =========================================================
       SELECCIONAR AUDITOR
    ========================================================= */

    function selectAuditor(auditor, card) {
      document.querySelectorAll(".auditor-card").forEach(item => item.classList.remove("selected"));
      card.classList.add("selected");
      auditorSeleccionado = auditor;
      renderValidacionesSeleccionados();
      updateAssignButton();
    }


    /* =========================================================
       MODAL RESULTADO
    ========================================================= */

    // Enlace a Agenda con la solicitud ya elegida en "Programar una auditoría".
    function urlProgramarVisita(idSolicitud) {
      return "/consultar-agenda-auditor?solicitud=" + encodeURIComponent(String(idSolicitud)) + "#schedule";
    }

    function mostrarResultadoAsignacion(texto, tipo, idSolicitudProgramar = null) {
      const modal = document.getElementById("assignmentResultModal");
      const title = document.getElementById("assignmentResultTitle");
      const body = document.getElementById("assignmentResultBody");
      title.textContent =
        tipo === "success"
          ? "Asignación realizada"
          : tipo === "error"
            ? "Error en la asignación"
            : "Resultado de la asignación";
      title.style.color =
        tipo === "success"
          ? "#256d00"
          : tipo === "error"
            ? "#b42318"
            : "#1d4ed8";
      body.textContent = texto;
      // Acceso directo: tras asignar con éxito se ofrece programar la visita.
      const programar = document.getElementById("assignmentResultProgramar");
      const siguiente = document.getElementById("assignmentResultNext");
      const aceptar = document.getElementById("assignmentResultAceptar");
      const ofrecer = Boolean(idSolicitudProgramar);
      programar.style.display = ofrecer ? "" : "none";
      siguiente.style.display = ofrecer ? "" : "none";
      if (ofrecer) programar.href = urlProgramarVisita(idSolicitudProgramar);
      aceptar.textContent = ofrecer ? "Programar después" : "Aceptar";
      aceptar.className = ofrecer ? "btn btn-secundario secondary-action" : "btn btn-primario primary-action";
      modal.classList.add("show");
      (ofrecer ? programar : aceptar).focus();
    }

    function cerrarResultadoAsignacion() {
      document
        .getElementById("assignmentResultModal")
        .classList.remove("show");
    }

    document
      .getElementById("assignmentResultModal")
      .addEventListener("click", (event) => {
        if (event.target.id === "assignmentResultModal") {
          event.currentTarget.classList.remove("show");
        }
      });

    /* =========================================================
       VALIDACIONES VISUALES
    ========================================================= */

    function setCheck(id, texto, estado) {
      const element = document.getElementById(id);
      element.textContent = texto;
      element.className = "validation-item " + (estado === true ? "ok" : estado === false ? "fail" : "neutral");
    }

    function renderValidacionesSeleccionados() {
      const box = document.getElementById("validationBox");
      const seleccionados = Array.from(auditoresSeleccionados.values());
      if (!seleccionados.length) {
        box.classList.remove("show");
        return;
      }
      box.classList.add("show");
      const html = seleccionados.map((auditor) => {
        const normaTexto = auditor.norma_nombre
          ? (auditor.norma_codigo ? auditor.norma_codigo + " - " : "") + auditor.norma_nombre
          : "Norma no especificada";
        const checks = [
          { texto: "Usuario activo", estado: auditor.estado_usuario === "Activo" },
          { texto: "Auditor aprobado", estado: ["Activo", "Aprobada", "Aprobado"].includes(auditor.estado_auditor) },
          { texto: "Competencia en norma: " + normaTexto, estado: auditor.competencia_norma === true },
          { texto: "Sin conflicto de interés", estado: auditor.conflicto_interes === false },
          { texto: "Disponibilidad real: se valida en Agenda", estado: null },
          { texto: "Cruces horarios: se validan en Agenda", estado: null },
        ];
        return `
          <div class="validation-auditor" style="margin-bottom:14px;padding:12px;border:1px solid #e2e8f0;border-radius:10px;background:#fff;">
            <div style="margin-bottom:8px;font-weight:700;color:#256d00;">${escapeHTML(auditor.nombre || "Auditor")}</div>
            <div class="validation-grid">
              ${checks.map(c => `<div class="validation-item ${c.estado === true ? "ok" : c.estado === false ? "fail" : "neutral"}">${escapeHTML(c.texto)}</div>`).join("")}
            </div>
          </div>
        `;
      }).join("");
      box.innerHTML = `<div style="margin-bottom:12px;font-weight:700;color:#1f2937;">Validaciones de auditores seleccionados</div>` + html;
    }

    function toggleAuditorChecked(auditor, checked) {
      toggleAuditorCheckedById(String(auditor.id_usuario), checked);
    }

    async function toggleAuditorCheckedById(id, checked) {
      id = String(id);
      const auditor = auditores.find(item => String(item.id_usuario) === id);
      if (!auditor) return;

      const card = document.querySelector(`.auditor-card[data-auditor-id="${CSS.escape(id)}"]`);
      const checkbox = card ? card.querySelector('.auditor-check-input') : null;
      const picker = card ? card.querySelector('.auditor-role-picker') : null;
      if (checked && !auditor.elegible) {
        if (checkbox) checkbox.checked = false;
        await abrirModalAdvertencia(auditor);
        return;
      }

      if (checked) {
        // Solo un auditor por solicitud: marcar uno desmarca el anterior.
        desmarcarOtrosAuditores(id);
        auditoresSeleccionados.set(id, auditor);
        if (picker) picker.style.display = 'block';
        auditorSeleccionado = auditor;
        renderValidacionesSeleccionados();
      } else {
        auditoresSeleccionados.delete(id);
        auditorRolesAsignados.delete(id);
        auditoresForzados.delete(id);
        justificacionesForzado.delete(id);
        if (picker) picker.style.display = 'none';
        if (auditorSeleccionado && String(auditorSeleccionado.id_usuario) === id) {
          auditorSeleccionado = null;
          validationBox.classList.remove("show");
        }
      }
      if (card) card.classList.toggle("selected", checked);
      updateAssignButton();
    }

    function desmarcarOtrosAuditores(idConservar) {
      Array.from(auditoresSeleccionados.keys()).forEach((otro) => {
        if (otro === String(idConservar)) return;
        auditoresSeleccionados.delete(otro);
        auditoresForzados.delete(otro);
        justificacionesForzado.delete(otro);
        const tarjeta = document.querySelector(`.auditor-card[data-auditor-id="${CSS.escape(otro)}"]`);
        if (tarjeta) {
          tarjeta.classList.remove("selected");
          const marca = tarjeta.querySelector('.auditor-check-input');
          const aviso = tarjeta.querySelector('.auditor-role-picker');
          if (marca) marca.checked = false;
          if (aviso) aviso.style.display = 'none';
        }
      });
    }

    async function abrirModalAdvertencia(auditor) {
      const id = String(auditor.id_usuario);
      document.getElementById('advertenciaTexto').textContent =
        auditor.motivo || 'Este auditor no cumple las condiciones automáticas de asignación.';
      const lista = document.getElementById('advertenciaCompetencias');
      lista.innerHTML = 'Cargando competencias...';
      const motivosLista = document.getElementById('advertenciaMotivos');
      const bloqueForzar = document.getElementById('advertenciaForzar');
      const botonForzar = document.getElementById('advertenciaConfirmar');
      const justificacion = document.getElementById('advertenciaJustificacion');
      motivosLista.innerHTML = '<li>Consultando...</li>';
      bloqueForzar.style.display = 'none';
      botonForzar.style.display = 'none';
      justificacion.value = justificacionesForzado.get(id) || '';
      justificacion.classList.remove('campo-invalido');
      document.getElementById('advertenciaError').style.display = 'none';
      document.getElementById('modalAdvertencia').classList.add('show');
      auditorAdvertenciaActual = auditor;
      // Razones concretas y si se puede forzar (el conflicto de interés no).
      const solicitud = getSelectedSolicitud();
      try {
        const res = await fetch(`/asignacion-auditores/solicitudes/${encodeURIComponent(solicitud.id_solicitud)}/auditores/${encodeURIComponent(id)}/elegibilidad`, { headers: headers() });
        const info = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(typeof info.detail === 'string' ? info.detail : 'No se pudo consultar la elegibilidad.');
        const motivos = Array.isArray(info.motivos) && info.motivos.length ? info.motivos : [auditor.motivo || 'No cumple las condiciones de asignación.'];
        motivosLista.innerHTML = motivos.map(m => `<li>${escapeHTML(m)}</li>`).join('');
        // "Asignar de todas formas": Coordinador, o Auxiliar con SOL-048 delegado.
        const puedeForzar = esCoordinador || Boolean(window.CertiPermisos && window.CertiPermisos.tiene('SOL-048'));
        if (info.forzable && puedeForzar) {
          bloqueForzar.style.display = '';
          botonForzar.style.display = '';
          setTimeout(() => justificacion.focus(), 50);
        } else if (info.bloqueante) {
          motivosLista.insertAdjacentHTML('beforeend', '<li><strong>Esta condición no se puede forzar.</strong></li>');
        }
      } catch (error) {
        motivosLista.innerHTML = `<li>${escapeHTML(error.message)}</li>`;
      }
      try {
        const response = await fetch(`/auditores/registro/${encodeURIComponent(id)}`, {
          headers: { 'Authorization': `Bearer ${token}`, 'Accept': 'application/json' }
        });
        const data = await response.json().catch(() => ({}));
        const competencias = Array.isArray(data.competencias) ? data.competencias : [];
        if (!competencias.length) {
          lista.innerHTML = 'No tiene competencias registradas.';
          return;
        }
        lista.innerHTML = competencias.map(item => {
          const titulo = item.titulo_institucion || 'Sin título';
          const tipo = item.tipo_competencia || 'Competencia';
          const norma = item.norma_nombre || item.norma_codigo || 'Sin nombre de norma';
          return `<li><strong>${tipo}</strong> — ${titulo} — Norma: ${norma}</li>`;
        }).join('');
      } catch {
        lista.innerHTML = 'No fue posible cargar las competencias.';
      }
    }

    function cerrarModalAdvertencia() {
      document.getElementById('modalAdvertencia').classList.remove('show');
      auditorAdvertenciaActual = null;
    }

    function confirmarAsignacionNoElegible() {
      const auditor = auditorAdvertenciaActual;
      if (!auditor) return;
      const id = String(auditor.id_usuario);
      const campo = document.getElementById('advertenciaJustificacion');
      const texto = campo.value.trim();
      if (texto.length < 10) {
        const error = document.getElementById('advertenciaError');
        error.textContent = 'Escriba una justificación de al menos 10 caracteres para asignarlo de todas formas.';
        error.style.display = 'block';
        campo.classList.add('campo-invalido');
        campo.setAttribute('aria-invalid', 'true');
        campo.focus();
        return;
      }
      justificacionesForzado.set(id, texto);
      desmarcarOtrosAuditores(id);
      auditoresSeleccionados.set(id, auditor);
      auditoresForzados.add(id);
      const card = document.querySelector(`.auditor-card[data-auditor-id="${CSS.escape(id)}"]`);
      const checkbox = card ? card.querySelector('.auditor-check-input') : null;
      const picker = card ? card.querySelector('.auditor-role-picker') : null;
      if (checkbox) checkbox.checked = true;
      if (picker) picker.style.display = 'block';
      if (card) card.classList.add('selected');
      cerrarModalAdvertencia();
      renderValidacionesSeleccionados();
      updateAssignButton();
    }

    function updateAssignButton() {
      const solicitud = getSelectedSolicitud();
      const seleccionados = Array.from(auditoresSeleccionados.values());
      const elegibles = seleccionados.length === 1 && seleccionados.every(auditor => {
        const id = String(auditor.id_usuario);
        return auditor.elegible === true || auditoresForzados.has(id);
      });
      const valido = Boolean(isAdmin && solicitud && elegibles);
      assignBtn.disabled = !valido;
      assignBtn.title = !elegibles ? "Selecciona un auditor elegible (solo un auditor por solicitud)." : "";
      if (auditorsSection.classList.contains("show")) {
        auditorsCounter.textContent = `${totalAuditoresFiltrados} resultado(s) · ${auditoresSeleccionados.size} seleccionado(s)`;
      }
    }


    /* =========================================================
       CAMBIOS DEL FORMULARIO
    ========================================================= */

    const buscarSolicitudesDebounced = debounce(() => cargarSolicitudes(1), 300);
    document.getElementById('solBuscar')?.addEventListener('input', buscarSolicitudesDebounced);
    document.getElementById('solNorma')?.addEventListener('change', () => cargarSolicitudes(1));
    document.getElementById('solSector')?.addEventListener('change', () => cargarSolicitudes(1));
    // Fecha inicio <= Fecha fin: cada selector limita al otro.
    document.getElementById('solDesde')?.addEventListener('change', (e) => {
      const fin = document.getElementById('solHasta');
      if (fin) fin.min = e.target.value || '';
      cargarSolicitudes(1);
    });
    document.getElementById('solHasta')?.addEventListener('change', (e) => {
      const inicio = document.getElementById('solDesde');
      if (inicio) inicio.max = e.target.value || '';
      cargarSolicitudes(1);
    });

    // Sugerencias (valores existentes) para los campos de ubicación; no obligan a elegir de la lista.
    (async function cargarSugerenciasUbicacion() {
      try {
        const res = await fetch('/asignacion-auditores/ubicaciones', { headers: headers() });
        if (!res.ok) return;
        const datos = await res.json();
        filtrosSolicitudesUbicacion.sugerir("ciudad", datos.solicitudes?.ciudades);
        filtrosSolicitudesUbicacion.sugerir("departamento", datos.solicitudes?.departamentos);
        filtrosSolicitudesUbicacion.sugerir("pais", datos.solicitudes?.paises);
        filtrosAuditoresUbicacion.sugerir("ciudad", datos.auditores?.ciudades);
        filtrosAuditoresUbicacion.sugerir("departamento", datos.auditores?.departamentos);
      } catch (_) { /* sin sugerencias: los filtros siguen funcionando */ }
    })();

    function debounce(fn, delay = 350) {
      let timer = null;
      return (...args) => {
        clearTimeout(timer);
        timer = setTimeout(() => fn(...args), delay);
      };
    }

    const buscarAuditoresDebounced = debounce(() => loadAuditores(1), 300);
    auditorSearchInput.addEventListener("input", buscarAuditoresDebounced);
    auditorModalityFilter.addEventListener("change", () => loadAuditores(1));
    auditorCompetenceFilter.addEventListener("change", () => loadAuditores(1));
    auditorConflictFilter.addEventListener("change", () => loadAuditores(1));
    auditorDescartarConflictos.addEventListener("change", () => loadAuditores(1));

    clearAuditorFilters.addEventListener("click", () => {
      auditorSearchInput.value = "";
      filtrosAuditoresUbicacion.limpiar(true);
      auditorModalityFilter.value = "";
      auditorCompetenceFilter.value = "";
      auditorConflictFilter.value = "";
      auditorDescartarConflictos.checked = false;
      loadAuditores(1);
    });
    auditorPrevPage.addEventListener("click", () => {
      if (paginaAuditores > 1) loadAuditores(paginaAuditores - 1);
    });
    auditorNextPage.addEventListener("click", () => {
      if (paginaAuditores < totalPaginasAuditores) loadAuditores(paginaAuditores + 1);
    });


    /* =========================================================
       CREAR ASIGNACIÓN
    ========================================================= */

    assignmentForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const solicitud = getSelectedSolicitud();
      if (!solicitud) {
        showMessage("Seleccione una solicitud aprobada.", "error");
        return;
      }
      const seleccionados = Array.from(auditoresSeleccionados.values());
      if (!seleccionados.length) {
        showMessage("Seleccione al menos un auditor elegible.", "error");
        return;
      }
      if (seleccionados.length > 1) {
        showMessage("Solo un auditor por solicitud: seleccione un único auditor.", "error");
        return;
      }

      assignBtn.disabled = true;
      assignBtn.textContent = "Asignando...";
      const resultados = [];
      const enOrden = seleccionados;

      try {
        for (const selected of enOrden) {
          const payload = {
            id_solicitud: solicitud.id_solicitud,
            id_auditor: selected.id_usuario
          };
          // Antes no se enviaba ninguna marca: el servidor volvía a validar y
          // rechazaba siempre al auditor "asignado de todas formas".
          if (auditoresForzados.has(String(selected.id_usuario))) {
            payload.forzar = true;
            payload.justificacion = justificacionesForzado.get(String(selected.id_usuario)) || "";
          }
          try {
            const response = await fetch("/asignacion-auditores/", {
              method: "POST",
              headers: headers(),
              body: JSON.stringify(payload)
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
              throw new Error(typeof data.detail === "string" ? data.detail : "No fue posible asignar el auditor.");
            }
            resultados.push({ ok: true, text: `${selected.nombre}: ${data.mensaje || "asignación realizada."}` });
          } catch (error) {
            console.error(error);
            resultados.push({ ok: false, text: `${selected.nombre}: ${error.message}` });
          }
        }

        const correctos = resultados.filter(item => item.ok).length;
        const fallidos = resultados.length - correctos;
        mostrarResultadoAsignacion(
          resultados.map(item => item.text).join("\n"),
          fallidos ? (correctos ? "info" : "error") : "success",
          correctos ? solicitud.id_solicitud : null
        );

        auditoresSeleccionados.clear();
        auditorRolesAsignados.clear();
        auditoresForzados.clear();
        auditorSeleccionado = null;
        validationBox.classList.remove("show");
        refrescarContadores();
        await loadAsignaciones();
        // La lista se recarga: si la solicitud quedó con su equipo completo
        // deja de ofrecerse y el formulario se limpia.
        await cargarSolicitudes(paginaSolicitudes);
        if (solicitudes.some(item => String(item.id_solicitud) === String(solicitud.id_solicitud))) {
          await loadAuditores(paginaAuditores);
        } else {
          resetForm();
          solicitudSeleccionada = null;
          updateAssignButton();
        }
      } catch (error) {
        console.error(error);
        showMessage(error?.message || String(error), "error");
      } finally {
        assignBtn.textContent = "Asignar auditor";
        updateAssignButton();
      }
    });


    /* =========================================================
       LIMPIAR
    ========================================================= */

    clearBtn.addEventListener("click", resetForm);

    function resetForm() {
      assignmentForm.reset();
      if (solicitudSelect) solicitudSelect.value = "";
      auditorSearchInput.value = "";
      filtrosAuditoresUbicacion.limpiar(true);
      auditorModalityFilter.value = "";
      auditorCompetenceFilter.value = "";
      requestInfo.classList.remove("show");
      auditorsSection.classList.remove("show");
      validationBox.classList.remove("show");
      auditorsList.innerHTML = "";
      auditorSeleccionado = null;
      auditorsCounter.textContent = "0 resultados";
      auditorPageInfo.textContent = "Selecciona una solicitud para consultar auditores.";
      auditorPrevPage.disabled = true;
      auditorNextPage.disabled = true;
      paginaAuditores = 1;
      auditoresSeleccionados.clear();
      auditorRolesAsignados.clear();
      auditoresForzados.clear();
      updateAssignButton();
    }


    /* =========================================================
       CARGAR ASIGNACIONES
    ========================================================= */

    async function loadAsignaciones() {
      tableLoading.style.display = "block";
      emptyState.style.display = "none";
      try {
        const response = await fetch("/asignacion-auditores/", { headers: headers() });
        const data = await response.json();
        if (!response.ok) {
          throw new Error(typeof data.detail === "string" ? data.detail : "No se pudieron cargar las asignaciones.");
        }
        asignaciones = Array.isArray(data)
          ? data.filter(item => String(item.estado_asignacion || "").toUpperCase() !== "CANCELADA")
          : [];
        renderAsignaciones();
      } catch (error) {
        console.error(error);
        tableLoading.style.display = "none";
        showMessage(error.message, "error");
      }
    }


    /* =========================================================
       PAGINACION DE ASIGNACIONES
    ========================================================= */

    function paginasVisiblesAsignaciones(totalPaginas, paginaActual) {
      const paginas = [];
      const agregar = (p) => {
        const ultima = paginas[paginas.length - 1];
        if (ultima === p) return;
        if (typeof ultima === "number" && p - ultima > 1) paginas.push("…");
        paginas.push(p);
      };
      agregar(1);
      for (let p = paginaActual - 1; p <= paginaActual + 1; p++) {
        if (p > 1 && p < totalPaginas) agregar(p);
      }
      if (totalPaginas > 1) agregar(totalPaginas);
      return paginas;
    }

    function renderAsignacionesPaginador() {
      const pager = document.getElementById("assignmentsPager");
      const contenedor = document.getElementById("assignmentsPagerButtons");
      const info = document.getElementById("assignmentsPagerInfo");
      contenedor.innerHTML = "";
      const total = asignaciones.length;
      if (total === 0) {
        pager.style.display = "none";
        return;
      }
      pager.style.display = "flex";
      const totalPaginas = Math.max(1, Math.ceil(total / asignacionesPagerState.porPagina));
      if (asignacionesPagerState.pagina > totalPaginas) asignacionesPagerState.pagina = totalPaginas;
      const inicio = (asignacionesPagerState.pagina - 1) * asignacionesPagerState.porPagina + 1;
      const fin = Math.min(asignacionesPagerState.pagina * asignacionesPagerState.porPagina, total);
      info.textContent = `Mostrando ${inicio}-${fin} de ${total} asignaciones`;
      const irAPagina = (p) => {
        if (p === asignacionesPagerState.pagina) return;
        asignacionesPagerState.pagina = p;
        renderAsignaciones();
      };
      const btnAnterior = document.createElement("button");
      btnAnterior.type = "button";
      btnAnterior.className = "pager-btn";
      btnAnterior.textContent = "‹";
      btnAnterior.disabled = asignacionesPagerState.pagina <= 1;
      btnAnterior.setAttribute("aria-label", "Página anterior");
      btnAnterior.addEventListener("click", () => irAPagina(asignacionesPagerState.pagina - 1));
      contenedor.appendChild(btnAnterior);
      paginasVisiblesAsignaciones(totalPaginas, asignacionesPagerState.pagina).forEach((p) => {
        if (p === "…") {
          const span = document.createElement("span");
          span.className = "pager-ellipsis";
          span.textContent = "…";
          contenedor.appendChild(span);
          return;
        }
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "pager-btn" + (p === asignacionesPagerState.pagina ? " active" : "");
        btn.textContent = p;
        btn.setAttribute("aria-label", "Ir a la página " + p);
        if (p === asignacionesPagerState.pagina) btn.setAttribute("aria-current", "page");
        btn.addEventListener("click", () => irAPagina(p));
        contenedor.appendChild(btn);
      });
      const btnSiguiente = document.createElement("button");
      btnSiguiente.type = "button";
      btnSiguiente.className = "pager-btn";
      btnSiguiente.textContent = "›";
      btnSiguiente.disabled = asignacionesPagerState.pagina >= totalPaginas;
      btnSiguiente.setAttribute("aria-label", "Página siguiente");
      btnSiguiente.addEventListener("click", () => irAPagina(asignacionesPagerState.pagina + 1));
      contenedor.appendChild(btnSiguiente);
    }

    document.getElementById("assignmentsPageSize").addEventListener("change", (e) => {
      asignacionesPagerState.porPagina = Number(e.target.value);
      asignacionesPagerState.pagina = 1;
      renderAsignaciones();
    });


    /* =========================================================
       RENDER ASIGNACIONES
    ========================================================= */

    function renderAsignaciones() {
      tableLoading.style.display = "none";
      assignmentsTableBody.innerHTML = "";

      assignmentCounter.textContent = `${asignaciones.length} ${asignaciones.length === 1 ? "asignación" : "asignaciones"}`;

      renderAsignacionesPaginador();

      if (asignaciones.length === 0) {
        emptyState.style.display = "block";
        return;
      }
      emptyState.style.display = "none";

      const inicioPagina = (asignacionesPagerState.pagina - 1) * asignacionesPagerState.porPagina;
      const pagina = asignaciones.slice(inicioPagina, inicioPagina + asignacionesPagerState.porPagina);

      pagina.forEach((asignacion) => {
        const row = document.createElement("tr");
        const enConflicto = asignacion.conflicto_interes === true;
        if (enConflicto) row.classList.add("fila-conflicto");
        let statusClass = "assigned";
        const estado = asignacion.tiene_programacion
          ? (asignacion.estado_programacion || "Programada")
          : (asignacion.estado_asignacion || "Asignado");
        const estadoVisible = (!asignacion.fecha_inicio_planificada && !asignacion.fecha_fin_planificada && !/cancelad/i.test(estado))
          ? "Asignado · pendiente de programación"
          : estado;

        if (/pendiente/i.test(estadoVisible)) statusClass = "pending";
        if (/inactivo|cancelado|eliminado/i.test(estado)) statusClass = "inactive";

        row.innerHTML = `
          <td>${escapeHTML(asignacion.numero_radicado || String(asignacion.id_solicitud))}</td>
          <td>${escapeHTML(asignacion.auditor_nombre || "-")}</td>
          <td>${escapeHTML(asignacion.auditor_correo || "-")}</td>
          <td>${escapeHTML(asignacion.fecha_inicio_planificada ? formatDateTime(asignacion.fecha_inicio_planificada) : "Pendiente en Agenda")}</td>
          <td>${escapeHTML(asignacion.fecha_fin_planificada ? formatDateTime(asignacion.fecha_fin_planificada) : "Pendiente en Agenda")}</td>
          <td>Auditor</td>
          <td><span class="status ${statusClass}">${escapeHTML(estadoVisible)}</span>${enConflicto
            ? '<br><span class="status conflicto" title="El auditor tiene un conflicto de interés activo con la empresa de esta solicitud">Conflicto de interés: debe reasignarse</span>'
            : ''}</td>
          <td>
            <div class="actions">
              <button type="button" class="btn btn-secundario btn-sm action-btn action-view">Ver</button>
              ${asignacion.tiene_programacion
                ? `<a class="btn btn-secundario btn-sm action-btn" href="${escapeHTML(urlProgramarVisita(asignacion.id_solicitud))}" title="Abre Agenda con esta solicitud: verá la visita ya programada y podrá elegir otra sede de la empresa para programarla">Programar otra sede</a>`
                : `<a class="btn btn-primario btn-sm action-btn" href="${escapeHTML(urlProgramarVisita(asignacion.id_solicitud))}" title="Abre Agenda con esta solicitud seleccionada para programar la visita">Programar visita</a>`}
              ${!esCoordinador ? '' : enConflicto
                ? `<button type="button" class="btn btn-peligro btn-sm action-btn action-conflicto" title="Cancela la asignación por conflicto de interés, aunque tenga visita programada">Cancelar por conflicto</button>`
                : `<button type="button" class="btn btn-peligro-contorno btn-sm action-btn action-cancel" ${asignacion.tiene_programacion ? 'disabled title="La visita ya está programada: cancélela o reprográmela desde Agenda antes de cancelar la asignación."' : ''}>Cancelar asignación</button>`}
            </div>
            ${!esCoordinador && enConflicto ? '<span class="action-hint">Conflicto de interés: el Coordinador debe cancelar esta asignación.</span>' : ''}
            ${esCoordinador && asignacion.tiene_programacion && !enConflicto ? '<span class="action-hint">Tiene visita programada: para cancelarla use Agenda (cancelar o reprogramar la visita).</span>' : ''}
          </td>`;

        const viewButton = row.querySelector(".action-view");
        viewButton.addEventListener("click", () => viewAssignment(asignacion));

        const conflictoButton = row.querySelector(".action-conflicto");
        if (conflictoButton) {
          conflictoButton.addEventListener("click", () => abrirRetiroConflicto(asignacion, conflictoButton));
        }

        const cancelButton = row.querySelector(".action-cancel");
        if (cancelButton) cancelButton.addEventListener("click", async () => {
          if (!confirm(`¿Desea cancelar la asignación de ${asignacion.auditor_nombre || "este auditor"} en la solicitud ${asignacion.numero_radicado || asignacion.id_solicitud}? Esta acción no se puede deshacer.`)) return;
          try {
            const response = await fetch(`/asignacion-auditores/${encodeURIComponent(asignacion.id)}`, {
              method: "DELETE",
              headers: headers()
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
              throw new Error(typeof data.detail === "string" ? data.detail : "No fue posible cancelar la asignación.");
            }
            showMessage(data.mensaje || "Asignación cancelada correctamente.", "success");
            refrescarContadores();
            await loadAsignaciones();
          } catch (error) {
            console.error(error);
            showMessage(error.message, "error");
          }
        });

        assignmentsTableBody.appendChild(row);
      });
    }


    /* =========================================================
       VER DETALLES
    ========================================================= */

    /* =========================================================
       RETIRO POR CONFLICTO DE INTERÉS
    ========================================================= */

    let retiroConflictoPendiente = null;
    let retiroConflictoOrigen = null;

    function abrirRetiroConflicto(asignacion, origen) {
      retiroConflictoPendiente = asignacion;
      retiroConflictoOrigen = origen || null;
      document.getElementById("retiroConflictoTexto").textContent =
        `${asignacion.auditor_nombre || "El auditor"} tiene un conflicto de interés activo con la empresa de la solicitud ${asignacion.numero_radicado || asignacion.id_solicitud}. No puede seguir asignado.`;
      document.getElementById("retiroConflictoMotivo").value = "";
      document.getElementById("retiroConflictoError").style.display = "none";
      document.getElementById("retiroConflictoModal").classList.add("show");
      setTimeout(() => document.getElementById("retiroConflictoCancelar").focus(), 50);
    }

    function cerrarRetiroConflicto() {
      document.getElementById("retiroConflictoModal").classList.remove("show");
      retiroConflictoPendiente = null;
      if (retiroConflictoOrigen && document.body.contains(retiroConflictoOrigen)) retiroConflictoOrigen.focus();
      retiroConflictoOrigen = null;
    }

    document.getElementById("retiroConflictoCancelar").addEventListener("click", cerrarRetiroConflicto);
    document.getElementById("retiroConflictoModal").addEventListener("keydown", (event) => {
      if (event.key === "Escape") cerrarRetiroConflicto();
    });
    document.getElementById("retiroConflictoConfirmar").addEventListener("click", async () => {
      if (!retiroConflictoPendiente) return;
      const boton = document.getElementById("retiroConflictoConfirmar");
      const error = document.getElementById("retiroConflictoError");
      boton.disabled = true;
      try {
        const response = await fetch(`/asignacion-auditores/${encodeURIComponent(retiroConflictoPendiente.id)}/retirar-por-conflicto`, {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({ motivo: document.getElementById("retiroConflictoMotivo").value.trim() || null })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(typeof data.detail === "string" ? data.detail : "No fue posible cancelar la asignación.");
        }
        cerrarRetiroConflicto();
        showMessage(data.mensaje || "Asignación cancelada por conflicto de interés.", "success");
        refrescarContadores();
        await loadAsignaciones();
      } catch (e) {
        error.textContent = e.message;
        error.style.display = "block";
      } finally {
        boton.disabled = false;
      }
    });

    function viewAssignment(assignment) {
      document.getElementById("detailSolicitud").textContent = assignment.numero_radicado || assignment.id_solicitud || "-";
      document.getElementById("detailAuditor").textContent = assignment.auditor_nombre || "-";
      document.getElementById("detailCorreo").textContent = assignment.auditor_correo || "-";
      document.getElementById("detailRol").textContent = "Auditor";
      document.getElementById("detailInicio").textContent = assignment.fecha_inicio_planificada
        ? formatDateTime(assignment.fecha_inicio_planificada)
        : "Pendiente de programación en Agenda";
      document.getElementById("detailFin").textContent = assignment.fecha_fin_planificada
        ? formatDateTime(assignment.fecha_fin_planificada)
        : "Pendiente de programación en Agenda";
      document.getElementById("detailEstado").textContent = assignment.estado_asignacion || "-";
      document.getElementById("detailsModal").classList.add("show");
    }


    /* =========================================================
       CERRAR MODAL
    ========================================================= */

    document.getElementById("closeDetailsBtn").addEventListener("click", () => {
      document.getElementById("detailsModal").classList.remove("show");
    });

    document.getElementById("detailsModal").addEventListener("click", (event) => {
      if (event.target.id === "detailsModal") {
        event.currentTarget.classList.remove("show");
      }
    });


    /* =========================================================
       ESCAPAR HTML
    ========================================================= */

    function escapeHTML(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }


    /* =========================================================
       LOGOUT
    ========================================================= */

    document.getElementById("logoutLink")?.addEventListener("click", (event) => {
      event.preventDefault();
      localStorage.removeItem("access_token");
      location.href = "/login";
    });


    /* =========================================================
       RENDER SOLICITUDES TABLA
    ========================================================= */

    function renderSolicitudesTable(lista) {
      const tbody = document.getElementById('solicitudesBody');
      if (!tbody) return;
      const empty = document.getElementById('solicitudesEmpty');
      if (!lista.length) {
        tbody.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
      }
      if (empty) empty.style.display = 'none';
      tbody.innerHTML = lista.map((solicitud) => {
        const radicado = solicitud.numero_radicado || solicitud.id_solicitud || '-';
        const empresa = solicitud.empresa_nombre || '-';
        const normaCodigo = solicitud.norma_codigo || '-';
        const normaNombre = solicitud.norma_nombre || '-';
        const fecha = solicitud.fecha ? new Date(solicitud.fecha).toLocaleDateString('es-CO') : '-';
        // Solo llegan solicitudes sin auditores activos (con uno ya quedan
        // completas). Si el servidor informara alguno, se indica cuántos.
        const asignados = Number(solicitud.auditores_asignados || 0);
        const equipo = asignados
          ? `<br><span class="help-text">Ya tiene ${asignados} auditor(es)</span>`
          : '';
        return `<tr>
          <td>${escapeHTML(radicado)}${equipo}</td>
          <td>${escapeHTML(empresa)}${solicitud.empresa_ciudad ? `<br><span class="help-text">${escapeHTML(solicitud.empresa_ciudad)}</span>` : ''}</td>
          <td>${escapeHTML(normaCodigo)}<br><span class="help-text">${escapeHTML(normaNombre)}</span></td>
          <td>${escapeHTML(fecha)}</td>
          <td class="row-actions">
            ${solicitud.tiene_programacion
              ? '<span class="status assigned">Programada</span>'
              : `<button class="btn btn-primario btn-sm mini-btn" type="button" onclick="seleccionarSolicitud('${escapeHTML(solicitud.id_solicitud)}')">Seleccionar</button>`}
          </td>
        </tr>`;
      }).join('');
    }

    async function cargarSolicitudes(page = 1) {
      paginaSolicitudes = page;
      const params = new URLSearchParams();
      params.set('page', page);
      const buscar = document.getElementById('solBuscar')?.value.trim();
      const ciudad = document.getElementById('solCiudad')?.value.trim();
      const departamento = document.getElementById('solDepartamento')?.value.trim();
      const pais = document.getElementById('solPais')?.value.trim();
      const desde = document.getElementById('solDesde')?.value;
      const hasta = document.getElementById('solHasta')?.value;
      const norma = document.getElementById('solNorma')?.value.trim();
      const sector = document.getElementById('solSector')?.value.trim();
      if (desde && hasta && desde > hasta) {
        showMessage('La fecha inicio no puede ser posterior a la fecha fin.', 'error');
        return;
      }
      if (buscar) params.set('buscar', buscar);
      if (ciudad) params.set('ciudad', ciudad);
      if (departamento) params.set('departamento', departamento);
      if (pais) params.set('pais', pais);
      if (desde) params.set('desde', desde);
      if (hasta) params.set('hasta', hasta);
      if (norma) params.set('norma', norma);
      if (sector) params.set('sector', sector);
      try {
        if (abortoSolicitudes) abortoSolicitudes.abort();
        const controlador = new AbortController();
        abortoSolicitudes = controlador;
        const res = await fetch('/asignacion-auditores/solicitudes?' + params.toString(), { headers: headers(), signal: controlador.signal });
        const data = await res.json().catch(() => ({}));
        solicitudes = Array.isArray(data.items) ? data.items : [];
        renderSolicitudesTable(solicitudes);
        const total = Number(data.total || 0);
        const ubicacionSol = { ciudad, departamento, pais };
        const porUbicacion = FiltrosUbicacion.hayFiltros(ubicacionSol);
        const vacioTexto = document.getElementById('solicitudesEmptyTexto');
        if (vacioTexto) {
          vacioTexto.textContent = porUbicacion && !buscar && !norma && !sector && !desde && !hasta
            ? FiltrosUbicacion.mensajeVacio('solicitudes', ubicacionSol)
            : 'Ajuste los filtros para ver más resultados.';
        }
        const estadoSol = document.getElementById('solicitudesEstado');
        if (estadoSol) {
          estadoSol.textContent = porUbicacion
            ? (total ? `${total} solicitud(es) en esa ubicación.` : FiltrosUbicacion.mensajeVacio('solicitudes', ubicacionSol))
            : '';
        }
        const totalPages = Number(data.total_pages || 1);
        const info = document.getElementById('solicitudesSummary');
        if (info) info.textContent = `Mostrando ${Math.min((page - 1) * 12 + 1, total)}-${Math.min(page * 12, total)} de ${total} solicitudes. Página ${page} de ${totalPages}.`;
        const prev = document.getElementById('solPrevPage');
        const next = document.getElementById('solNextPage');
        if (prev) prev.disabled = page <= 1;
        if (next) next.disabled = page >= totalPages;
      } catch (error) {
        if (error && error.name === 'AbortError') return;
        console.error('No se pudieron cargar las solicitudes:', error);
      }
    }

    function limpiarFiltrosSolicitudes() {
      ['solBuscar', 'solNorma', 'solSector'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
      filtrosSolicitudesUbicacion.limpiar(true);
      ['solDesde', 'solHasta'].forEach(id => { const el = document.getElementById(id); if (el) { el.value = ''; el.min = ''; el.max = ''; } });
      cargarSolicitudes(1);
    }

    function seleccionarSolicitud(id) {
      const solicitud = solicitudes.find(item => String(item.id_solicitud) === String(id));
      if (!solicitud) return;
      solicitudSeleccionada = solicitud;
      document.getElementById('infoRadicado').textContent = solicitud.numero_radicado || solicitud.id_solicitud || '-';
      document.getElementById('infoEmpresa').textContent = solicitud.empresa_nombre || '-';
      document.getElementById('infoNorma').textContent = (solicitud.norma_codigo || '') + (solicitud.norma_nombre ? ' - ' + solicitud.norma_nombre : '');
      document.getElementById('infoVersion').textContent = solicitud.norma_version || '-';
      document.getElementById('infoEstado').textContent = solicitud.estado || '-';
      document.getElementById('infoFechaSolicitud').textContent = solicitud.fecha ? new Date(solicitud.fecha).toLocaleDateString('es-CO') : '-';
      requestInfo.classList.add('show');
      mostrarSedesSolicitud(solicitud);
      auditoresSeleccionados.clear();
      auditorRolesAsignados.clear();
      auditoresForzados.clear();
      auditorSeleccionado = null;
      validationBox.classList.remove('show');
      updateAssignButton();
      loadAuditores(1);
      document.getElementById('auditorsSection')?.classList.add('show');
    }

    /* =========================================================
       SOLICITUDES DE CAMBIO DE LA EMPRESA
    ========================================================= */

    async function loadSolicitudesCambio() {
      const cuerpo = document.getElementById("changeTableBody");
      const vacio = document.getElementById("changeEmpty");
      try {
        const response = await fetch("/asignacion-auditores/solicitudes-cambio", { headers: headers() });
        const data = await response.json().catch(() => []);
        if (!response.ok) {
          throw new Error(typeof data.detail === "string" ? data.detail : "No se pudieron cargar las solicitudes de cambio.");
        }
        const lista = Array.isArray(data) ? data : [];
        const pendientes = lista.filter(item => item.estado === "Pendiente").length;
        document.getElementById("changeCounter").textContent =
          `${pendientes} ${pendientes === 1 ? "pendiente" : "pendientes"}`;
        vacio.style.display = lista.length ? "none" : "block";
        cuerpo.innerHTML = lista.map(item => `
          <tr>
            <td>${escapeHTML(item.numero_radicado || item.id_solicitud)}</td>
            <td>${escapeHTML(item.empresa_nombre || "-")}</td>
            <td>${escapeHTML(item.auditor_nombre || "-")}</td>
            <td style="max-width:320px;white-space:normal">${escapeHTML(item.motivo || "")}</td>
            <td>${escapeHTML(item.fecha_solicitud ? formatDateTime(item.fecha_solicitud) : "-")}</td>
            <td><span class="status ${item.estado === "Pendiente" ? "pending" : (item.estado === "Aprobada" ? "assigned" : "inactive")}">${escapeHTML(item.estado)}</span>
              ${item.respuesta ? `<br><small>${escapeHTML(item.respuesta)}</small>` : ""}</td>
            <td>${item.estado === "Pendiente" && !esCoordinador ? '<span class="help-text">La resuelve el Coordinador</span>' : item.estado === "Pendiente" ? `
              <div class="actions">
                <button type="button" class="btn btn-primario btn-sm action-btn" data-resolver="1" data-id="${escapeHTML(item.id_solicitud_cambio)}">Aprobar</button>
                <button type="button" class="btn btn-peligro-contorno btn-sm action-btn" data-resolver="0" data-id="${escapeHTML(item.id_solicitud_cambio)}">Rechazar</button>
              </div>` : "-"}</td>
          </tr>`).join("");
      } catch (error) {
        console.error(error);
        showMessage(error.message, "error");
      }
    }

    document.getElementById("changeTableBody").addEventListener("click", async (evento) => {
      const boton = evento.target.closest("[data-resolver]");
      if (!boton) return;
      const aprobar = boton.dataset.resolver === "1";
      const respuesta = prompt(aprobar
        ? "Aprobar: la asignación del auditor quedará cancelada. Escriba la respuesta para la empresa (mínimo 10 caracteres):"
        : "Rechazar: escriba a la empresa por qué no procede el cambio (mínimo 10 caracteres):");
      if (respuesta === null) return;
      if (respuesta.trim().length < 10) {
        showMessage("La respuesta debe tener al menos 10 caracteres.", "error");
        return;
      }
      try {
        const response = await fetch(`/asignacion-auditores/solicitudes-cambio/${encodeURIComponent(boton.dataset.id)}/resolver`, {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({ aprobar, respuesta: respuesta.trim() })
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(typeof data.detail === "string" ? data.detail : "No fue posible resolver la solicitud.");
        }
        showMessage(data.mensaje || "Solicitud resuelta.", "success");
        refrescarContadores();
        await Promise.all([loadSolicitudesCambio(), loadAsignaciones()]);
      } catch (error) {
        console.error(error);
        showMessage(error.message, "error");
      }
    });

    /* =========================================================
       ETAPAS DE LA PANTALLA "SOLICITUDES"
       Las listas se piden al abrir su etapa (antes, todas al cargar).
    ========================================================= */

    async function activarEtapaAsignacion(etapa) {
      if (!isAdmin) return;
      if (etapa === "por-asignar") {
        await cargarSolicitudes(paginaSolicitudes || 1);
      } else if (etapa === "con-auditores") {
        await Promise.all([loadAsignaciones(), loadSolicitudesCambio()]);
      }
    }

    // Desde "En revisión" (tras aprobar) o "Todas": deja la solicitud
    // elegida en "Por asignar auditor". Busca por radicado para que aparezca
    // aunque no esté en la primera página.
    async function abrirSolicitudParaAsignar(id, radicado) {
      limpiarCamposSolicitudes();
      const buscar = document.getElementById("solBuscar");
      if (buscar && radicado) buscar.value = radicado;
      await cargarSolicitudes(1);
      const encontrada = solicitudes.some(item => String(item.id_solicitud) === String(id));
      if (encontrada) {
        seleccionarSolicitud(id);
        document.getElementById("requestInfo")?.scrollIntoView({ behavior: "smooth", block: "start" });
        return true;
      }
      showMessage("La solicitud ya no está pendiente de auditor: puede que ya tenga uno asignado (véala en \"Con auditores\").", "info");
      return false;
    }

    function limpiarCamposSolicitudes() {
      ['solBuscar', 'solNorma', 'solSector'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
      filtrosSolicitudesUbicacion.limpiar(true);
      ['solDesde', 'solHasta'].forEach(id => { const el = document.getElementById(id); if (el) { el.value = ''; el.min = ''; el.max = ''; } });
    }

    window.SolicitudesAsignacion = {
      activar: activarEtapaAsignacion,
      abrirSolicitud: abrirSolicitudParaAsignar,
      puedeGestionar: isAdmin,
      esCoordinador
    };


    async function abrirModalAuditor(auditor) {
      const modal = document.getElementById('auditorModal');
      const title = document.getElementById('auditorModalTitle');
      const body = document.getElementById('auditorModalBody');
      modal.classList.add('show');
      title.textContent = auditor.nombre || 'Auditor';
      body.innerHTML = '<div class="audit-empty">Cargando...</div>';
      const token = localStorage.getItem('access_token');
      try {
        const response = await fetch(`/auditores/registro/${auditor.id_usuario}`, {
          headers: { 'Authorization': `Bearer ${token}`, 'Accept': 'application/json' }
        });
        const data = await response.json().catch(() => ({}));
        const competencias = Array.isArray(data.competencias) ? data.competencias : [];
        const documentos = Array.isArray(data.documentos) ? data.documentos : [];
        const normalizarBooleano = function (valor) { return valor === true ? 'Sí' : valor === false ? 'No' : (valor === null || valor === undefined ? 'No disponible' : String(valor)); };
        const fotoUrl = data?.perfil?.foto_url ? data.perfil.foto_url : '';
        body.innerHTML = `
          <div class="auditor-modal-grid">
            <div class="audit-modal-field"><label>Nombre</label><span>${escapeHTML(data.nombre || auditor.nombre || '-')}</span></div>
            <div class="audit-modal-field"><label>Correo</label><span>${escapeHTML(data.correo || auditor.correo || '-')}</span></div>
            <div class="audit-modal-field"><label>Estado auditor</label><span>${escapeHTML(data.estado_auditor || auditor.estado_auditor || '-')}</span></div>
            <div class="audit-modal-field"><label>Observaciones</label><span>${escapeHTML(data.observaciones_tecnicas || '-')}</span></div>
            <div class="audit-modal-field"><label>Foto del auditor</label>
               <div class="audit-photo">
                 ${fotoUrl ? `<img src="${escapeHTML(fotoUrl)}" alt="Foto del auditor" onerror="this.parentNode.innerHTML='<div class=&quot;audit-empty&quot;>No disponible.</div>'" />` : '<div class="audit-empty">Sin foto registrada.</div>'}
               </div>
            </div>
          </div>
          <div class="modal-section">
            <h3>Competencias</h3>
            ${competencias.length ? '<ul class="audit-list">' + competencias.map(c => '<li><strong>' + escapeHTML(c.tipo_competencia || '-') + '</strong> — Norma: ' + escapeHTML(c.norma_nombre || '-') + ' (' + escapeHTML(c.norma_codigo || '-') + ')' + ' — Sector IAF: ' + escapeHTML(c.codigo_sector_iaf || '-') + ' — ' + escapeHTML(c.titulo_institucion || '-') + ' — Vigente: ' + normalizarBooleano(c.es_vigente) + '</li>').join('') + '</ul>' : '<div class="audit-empty">Sin competencias registradas.</div>'}
          </div>
          <div class="modal-section">
            <h3>Documentos adjuntos</h3>
            ${documentos.length ? documentos.map(d => '<div class="doc-item"><div style="flex:1;"><strong>' + escapeHTML(d.tipo_documento || '-') + '</strong> — ' + escapeHTML(d.estado_revision || '-') + ' — ' + escapeHTML(d.nombre_archivo || '-') + '</div>' + (d.url_archivo ? '<a class="btn btn-secundario btn-sm" href="' + escapeHTML(d.url_archivo) + '" target="_blank" rel="noopener" title="Ver documento" aria-label="Ver ' + escapeHTML(d.tipo_documento || 'documento') + '"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg>Ver</a>' : '') + '</div>').join('') : '<div class="audit-empty">Sin documentos registrados.</div>'}
          </div>
        `;
      } catch {
        body.innerHTML = '<div class="audit-empty">No fue posible cargar la información.</div>';
      }
    }

    function cerrarModalAuditor() { document.getElementById('auditorModal').classList.remove('show'); }
