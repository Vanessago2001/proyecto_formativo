/*
 * Mi disponibilidad (auditor)
 * ---------------------------------------------------------------
 * Bloque común para que el auditor configure su horario semanal mientras
 * ve, en un calendario (mes o semana), las auditorías que ya tiene
 * programadas y sus fechas bloqueadas. Lo usa:
 *   - static/disponibilidad_auditor.html (sección "Mi disponibilidad semanal",
 *     #configurar-horario; el menú del auditor lleva ahí)
 *
 * Al pulsar un día con información (bloqueado, ocupado con visita o con
 * franjas declaradas) se abre un modal con el detalle; el auditor puede
 * desbloquear desde ahí (DELETE /agenda-auditor/{id}/no-disponible?fecha=).
 *
 * Endpoints (los mismos de siempre):
 *   POST /agenda-auditor/{id}/disponibilidad-semanal
 *   GET  /agenda-auditor/{id}/disponibilidad-mensual?anio=&mes=
 * Solo el propio auditor puede guardar su horario (el backend responde 403
 * a cualquier otra persona, incluido el Coordinador).
 *
 * Uso:  MiDisponibilidad.montar(elementoContenedor, { idUsuario, token, alGuardar })
 *
 * El calendario (mes/semana, anterior/hoy/siguiente, leyenda) es un
 * componente aparte que también usa la vista mensual del Coordinador
 * (static/consultar_agenda_auditor.html#month):
 *   MiDisponibilidad.calendario(contenedor, {
 *     titulo, leyenda: [[clase, texto]], vistaInicial: "mes" | "semana",
 *     maxPorDia,                       // en la vista mes: el resto va a "+N más"
 *     cargarMes: async (anio, mes) => Map(fecha ISO -> día),
 *     chips: (dia, detallado, fechaIso) => [html, ...],
 *     estadoDia: (dia, fechaIso) => "bloqueado" | "ocupado con 1 visita" | "" (vacío: no abre),
 *     detalleDia: (dia, fechaIso) => ({ html, alAbrir(cuerpo, cerrar) })
 *   })  ->  { recargar(), pintar(), abrirDia(fechaIso, origen) }
 *   MiDisponibilidad.dialogo({ titulo, html, origen, alAbrir })  (modal accesible)
 *   MiDisponibilidad.detalle.{visita, bloqueo, disponible}       (bloques del modal)
 */
(function () {
    "use strict";

    const DIAS = [
        { clave: "lunes", texto: "Lunes", fin: "17:00" },
        { clave: "martes", texto: "Martes", fin: "17:00" },
        { clave: "miercoles", texto: "Miércoles", fin: "17:00" },
        { clave: "jueves", texto: "Jueves", fin: "17:00" },
        { clave: "viernes", texto: "Viernes", fin: "17:00" },
        { clave: "sabado", texto: "Sábado", fin: "12:00" },
        { clave: "domingo", texto: "Domingo", fin: "12:00" }
    ];
    const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
        "agosto", "septiembre", "octubre", "noviembre", "diciembre"];
    const TERMINALES = ["CANCELADA", "CANCELADO", "FINALIZADA", "FINALIZADO"];

    const ESTILOS = `
.md-bloque { display: grid; gap: 22px; }
.md-titulo { margin: 0 0 6px; font-size: 16px; color: var(--sena-verde-oscuro, #1f5f00); }
.md-ayuda { margin: 0 0 12px; color: #5f6f69; font-size: 13px; }
.md-rejilla { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
.md-campo { display: flex; flex-direction: column; gap: 6px; }
.md-campo label { font-size: 12px; font-weight: 600; color: #475569; }
.md-campo input { min-height: 38px; padding: 6px 10px; border: 1px solid var(--campo-borde, #cbd5e1); border-radius: var(--campo-radio, 8px); font: inherit; }
.md-dias { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin-top: 14px; }
.md-dia { min-width: 0; border: 1px solid #e2e8f0; border-radius: 10px; padding: 10px; background: #f8fafc; }
.md-dia.activo { border-color: #39a900; background: #f3faef; }
.md-dia label.md-dia-nombre { display: flex; gap: 8px; align-items: center; font-weight: 700; font-size: 13px; cursor: pointer; }
.md-dia .md-horas { display: flex; gap: 6px; margin-top: 8px; }
.md-dia .md-horas input { width: 100%; min-width: 0; flex: 1 1 0; min-height: 34px; padding: 4px 6px; border: 1px solid #cbd5e1; border-radius: 6px; font: inherit; font-size: 13px; }
.md-acciones { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; align-items: center; }
.md-aviso { display: none; margin-top: 12px; padding: 10px 14px; border-radius: 8px; font-size: 13px; line-height: 1.5; white-space: pre-line; }
.md-aviso.ok { display: block; background: #ecfdf3; color: #17582c; border: 1px solid #cfe3c5; }
.md-aviso.error { display: block; background: #fef2f2; color: #8a2020; border: 1px solid #e7bfbb; }
.md-aviso.info { display: block; background: #eff6ff; color: #244f89; border: 1px solid #c6d5ef; }
.md-aviso:focus { outline: 2px solid #39a900; outline-offset: 2px; }
.md-invalido { border-color: #b42318 !important; box-shadow: 0 0 0 3px rgba(180,35,24,.15); }
.md-cal-barra { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.md-cal-barra .md-cal-titulo { font-weight: 700; font-size: 15px; text-transform: capitalize; }
.md-cal-barra .md-grupo { display: flex; gap: 6px; flex-wrap: wrap; }
.md-cal-barra .btn[aria-pressed="true"] { background: var(--sena-verde, #39a900); color: #fff; border-color: var(--sena-verde, #39a900); }
.md-leyenda { display: flex; flex-wrap: wrap; gap: 12px; font-size: 12px; color: #475569; margin: 8px 0 12px; }
.md-leyenda span::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; background: var(--md-c); }
.md-mes { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }
.md-mes .md-cab { font-size: 11px; font-weight: 700; text-align: center; color: #64748b; padding: 4px 0; text-transform: uppercase; }
.md-celda { min-height: 86px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 4px; background: #fff; font-size: 11px; overflow: hidden; }
.md-celda.fuera { background: #f8fafc; color: #94a3b8; }
.md-celda.hoy { outline: 2px solid #39a900; outline-offset: -2px; }
.md-celda .md-num { font-weight: 700; font-size: 12px; }
.md-chip { display: block; margin-top: 3px; padding: 2px 4px; border-radius: 4px; line-height: 1.3; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; background: var(--md-c); color: var(--md-t, #0f172a); }
.md-libre { --md-c: #dcfce7; --md-t: #14532d; }
.md-ocupado { --md-c: #fee2e2; --md-t: #7f1d1d; }
.md-bloqueado { --md-c: #e2e8f0; --md-t: #334155; }
.md-semana { display: grid; gap: 8px; }
.md-semana .md-fila { display: grid; grid-template-columns: 130px 1fr; gap: 10px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 10px; background: #fff; }
.md-semana .md-fila.hoy { border-color: #39a900; }
.md-semana .md-fecha { font-weight: 700; font-size: 13px; text-transform: capitalize; }
.md-semana .md-chip { white-space: normal; font-size: 12px; padding: 4px 6px; }
.md-vacio { color: #64748b; font-size: 12px; }
button.md-chip { width: 100%; border: 0; font: inherit; text-align: left; cursor: pointer; }
button.md-chip:hover { filter: brightness(.95); text-decoration: underline; }
button.md-chip:focus-visible { outline: 2px solid #1f5f00; outline-offset: 1px; }
.md-mas { --md-c: transparent; --md-t: #1f5f00; font-weight: 700; }
.md-finalizada { --md-c: #e0e7ff; --md-t: #312e81; }
/* Días con información: toda la celda abre el detalle (modal). */
.md-clic { cursor: pointer; transition: border-color .15s, box-shadow .15s; }
.md-clic:hover { border-color: #39a900; box-shadow: 0 1px 4px rgba(15,23,42,.12); }
.md-dia-btn { display: inline-flex; align-items: center; gap: 4px; min-width: 24px; min-height: 24px; padding: 0 4px; margin: 0; border: 0; border-radius: 6px; background: transparent; color: inherit; font: inherit; font-weight: 700; cursor: pointer; text-align: left; }
.md-celda .md-dia-btn { font-size: 12px; }
.md-dia-btn:hover { background: #f3faef; text-decoration: underline; }
.md-dia-btn:focus-visible { outline: 3px solid #1f5f00; outline-offset: 1px; }
.md-clic:has(.md-dia-btn:focus-visible) { border-color: #1f5f00; box-shadow: 0 0 0 2px #1f5f00; }
.md-dia-btn .md-ver { font-size: 10px; font-weight: 600; color: #1f5f00; }
/* Modal del detalle del día (dialog nativo: Escape, fondo inerte). */
dialog.md-dialogo { width: min(640px, calc(100vw - 24px)); max-height: calc(100vh - 32px); padding: 0; border: 0; border-radius: 12px; box-shadow: 0 20px 50px rgba(15,23,42,.3); color: #0f172a; overflow: hidden; }
dialog.md-dialogo[open] { display: flex; flex-direction: column; }
dialog.md-dialogo::backdrop { background: rgba(15,23,42,.55); }
.md-dlg-cab { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 14px 16px; border-bottom: 1px solid #e2e8f0; background: #f8fafc; }
.md-dlg-cab h3 { margin: 0; font-size: 16px; color: var(--sena-verde-oscuro, #1f5f00); }
.md-dlg-cerrar { flex: none; width: 36px; height: 36px; border: 1px solid #cbd5e1; border-radius: 8px; background: #fff; font-size: 20px; line-height: 1; cursor: pointer; }
.md-dlg-cerrar:focus-visible, .md-dlg-pie .btn:focus-visible, .md-dlg-cuerpo a:focus-visible, .md-dlg-cuerpo button:focus-visible { outline: 3px solid #1f5f00; outline-offset: 2px; }
.md-dlg-cuerpo { padding: 14px 16px; overflow-y: auto; display: grid; gap: 14px; font-size: 13px; }
.md-dlg-pie { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px; border-top: 1px solid #e2e8f0; }
.md-dlg-sec { border: 1px solid #e2e8f0; border-left: 4px solid var(--md-borde, #94a3b8); border-radius: 10px; padding: 12px; background: #fff; }
.md-dlg-sec.md-ocupado { --md-borde: #dc2626; }
.md-dlg-sec.md-bloqueado { --md-borde: #64748b; }
.md-dlg-sec.md-libre { --md-borde: #16a34a; }
.md-dlg-sec.md-finalizada { --md-borde: #4f46e5; }
.md-dlg-sec h4 { margin: 0 0 10px; font-size: 14px; display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.md-dlg-etq { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; background: var(--md-c); color: var(--md-t); }
.md-dlg-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px 14px; margin: 0; }
.md-dlg-grid > div { min-width: 0; }
.md-dlg-grid .md-completo { grid-column: 1 / -1; }
.md-dlg-grid dt { font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: .02em; }
.md-dlg-grid dd { margin: 2px 0 0; overflow-wrap: anywhere; }
.md-dlg-equipo { margin: 4px 0 0; padding-left: 18px; }
.md-dlg-equipo li { margin: 2px 0; }
.md-dlg-acciones { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 12px; }
.md-dlg-aviso { margin: 8px 0 0; padding: 8px 10px; border-radius: 8px; background: #fff7ed; color: #7c2d12; border: 1px solid #fed7aa; }
.md-dlg-aviso.ok { background: #ecfdf3; color: #17582c; border-color: #cfe3c5; }
.md-dlg-aviso.error { background: #fef2f2; color: #8a2020; border-color: #e7bfbb; }
@media (max-width: 640px) {
  .md-celda { min-height: 64px; font-size: 10px; }
  .md-celda .md-chip { font-size: 9px; }
  .md-semana .md-fila { grid-template-columns: 1fr; }
  .md-dia-btn .md-ver { display: none; }
}
@media (max-width: 480px) {
  .md-dlg-grid { grid-template-columns: 1fr; }
  .md-dlg-cuerpo { padding: 12px; }
  .md-dlg-pie .btn { flex: 1 1 auto; }
}`;

    function esc(v) {
        return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    }
    function iso(d) {
        return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    }
    function hora(v) {
        const t = String(v || "");
        const m = t.match(/(\d{2}:\d{2})/);
        return m ? m[1] : "";
    }
    function horaDeFecha(v) {
        const t = String(v || "");
        return t.length >= 16 ? t.slice(11, 16) : "";
    }
    function inyectarEstilos() {
        if (document.getElementById("md-estilos")) return;
        const st = document.createElement("style");
        st.id = "md-estilos";
        st.textContent = ESTILOS;
        document.head.appendChild(st);
    }

    // ==================================================================
    // Detalle del día: textos y modal accesible (lo usan el auditor y el
    // Coordinador). <dialog> nativo + showModal(): role="dialog",
    // aria-modal, fondo inerte y Escape; aquí se añade foco inicial, Tab
    // atrapado y devolución del foco al elemento que lo abrió.
    // ==================================================================
    function fechaLarga(f) {
        const d = desdeIso(String(f).slice(0, 10));
        return `${d.getDate()} de ${MESES[d.getMonth()]} de ${d.getFullYear()}`;
    }
    function diaMes(f) {
        const d = desdeIso(String(f).slice(0, 10));
        return `${d.getDate()} de ${MESES[d.getMonth()]}`;
    }
    function fechaHoraCorta(v) {
        const t = String(v || "");
        if (t.length < 10) return "";
        const [a, m, d] = t.slice(0, 10).split("-");
        const h = horaDeFecha(t);
        return `${d}/${m}/${a}${h ? " " + h : ""}`;
    }
    function rangoFechas(ini, fin) {
        const a = String(ini || "").slice(0, 10);
        const b = String(fin || "").slice(0, 10) || a;
        if (!a) return "—";
        return a === b ? fechaLarga(a) : `Del ${fechaLarga(a)} al ${fechaLarga(b)}`;
    }
    function dato(etiqueta, valor, completo) {
        return `<div${completo ? ' class="md-completo"' : ""}><dt>${esc(etiqueta)}</dt><dd>${esc(valor || "—")}</dd></div>`;
    }
    function horarioEnDia(v, fecha) {
        const ini = String(v.fecha_inicio || "");
        const fin = String(v.fecha_fin || "");
        const fi = ini.slice(0, 10), ff = fin.slice(0, 10) || fi;
        if (fi === ff) return `${horaDeFecha(ini) || "—"} – ${horaDeFecha(fin) || "—"}`;
        const tramo = fi === fecha ? `desde las ${horaDeFecha(ini)}` : ff === fecha ? `hasta las ${horaDeFecha(fin)}` : "todo el día";
        return `${fechaHoraCorta(ini)} a ${fechaHoraCorta(fin)} (este día: ${tramo})`;
    }
    function claseEstadoVisita(estado) {
        const e = String(estado || "").trim().toUpperCase();
        if (e.startsWith("CANCELAD")) return "md-bloqueado";
        if (e.startsWith("FINALIZAD")) return "md-finalizada";
        return "md-ocupado";
    }

    /* Una visita (programación). Admite la forma del auditor
       (/{id}/disponibilidad-mensual) y la del Coordinador
       (/disponibilidad-mensual-general). op: { fecha, idPropio, conCorreo, acciones(v) } */
    function htmlVisita(v, op) {
        op = op || {};
        const estado = v.estado_programacion || v.estado || "—";
        const ciudad = v.ciudad || v.ciudad_servicio || v.sede_ciudad || v.empresa_ciudad;
        const direccion = v.direccion || v.direccion_programacion || v.sede_direccion || v.direccion_servicio;
        const equipo = Array.isArray(v.equipo) ? v.equipo : [];
        const obs = [];
        const agregar = (e, t) => { if (t && !obs.some(([, x]) => x === t)) obs.push([e, t]); };
        agregar("Observación de la programación", v.observacion_auditor || v.motivo_reprogramacion);
        // observacion_auditor (vista del auditor) ya resume la solicitud de reprogramación.
        if (v.estado_solicitud_reprogramacion && !v.observacion_auditor) {
            agregar("Solicitud de reprogramación", `${v.estado_solicitud_reprogramacion}${v.motivo_solicitud_reprogramacion ? ": " + v.motivo_solicitud_reprogramacion : ""}`);
        }
        agregar("Motivo de cancelación", v.motivo_cancelacion);
        agregar("Observaciones de cierre", v.observaciones_finalizacion);
        const equipoHtml = equipo.length
            ? `<ul class="md-dlg-equipo">${equipo.map((e) => {
                const propio = op.idPropio && String(e.id_usuario) === String(op.idPropio);
                const correo = op.conCorreo && e.correo ? ` · ${esc(e.correo)}` : "";
                return `<li><strong>${esc(e.nombre || "Auditor")}</strong>${propio ? " (usted)" : ""} — Auditor · ${e.confirmado ? "confirmó" : "sin confirmar"}${correo}</li>`;
            }).join("")}</ul>`
            : "Sin auditores registrados.";
        const acciones = typeof op.acciones === "function" ? op.acciones(v) : "";
        const clase = claseEstadoVisita(estado);
        return `<section class="md-dlg-sec ${clase}">
  <h4><span class="md-dlg-etq ${clase}">Visita</span> ${esc(v.numero_radicado || "Auditoría")} <span class="md-dlg-etq ${clase}">${esc(estado)}</span></h4>
  <dl class="md-dlg-grid">
    ${dato("Empresa", v.empresa_nombre)}
    ${dato("NIT", v.empresa_nit)}
    ${dato("Sede", v.sede_nombre || "Sin sede registrada")}
    ${dato("Ciudad / municipio", ciudad)}
    ${dato("Dirección", direccion, true)}
    ${dato("Modalidad", v.modalidad)}
    ${dato("Horario", horarioEnDia(v, op.fecha))}
    <div class="md-completo"><dt>${equipo.length > 1 ? `Auditores (${equipo.length})` : "Auditor"}</dt><dd>${equipoHtml}</dd></div>
    ${obs.length ? obs.map(([e, t]) => dato(e, t, true)).join("") : dato("Observaciones", "Sin observaciones registradas.", true)}
  </dl>
  ${acciones ? `<div class="md-dlg-acciones">${acciones}</div>` : ""}
</section>`;
    }

    /* Un bloqueo de fecha. op: { conAuditor, acciones(b) } */
    function htmlBloqueo(b, op) {
        op = op || {};
        const acciones = typeof op.acciones === "function" ? op.acciones(b) : "";
        return `<section class="md-dlg-sec md-bloqueado">
  <h4><span class="md-dlg-etq md-bloqueado">Fecha bloqueada</span>${op.conAuditor && b.auditor_nombre ? " " + esc(b.auditor_nombre) : ""}</h4>
  <dl class="md-dlg-grid">
    ${dato("Fecha(s)", rangoFechas(b.fecha_inicio, b.fecha_fin), true)}
    ${dato("Tipo de bloqueo", b.tipo_registro || "Bloqueo de fecha")}
    ${dato("Registrado el", fechaHoraCorta(b.registrado_en) || "Sin dato")}
    ${dato("Motivo", b.motivo || "Sin motivo registrado", true)}
    ${b.radicado_relacionado || b.id_programacion ? dato("Programación relacionada", b.radicado_relacionado || "Programación de visita", true) : ""}
  </dl>
  ${acciones ? `<div class="md-dlg-acciones">${acciones}</div>` : ""}
</section>`;
    }

    /* Franjas declaradas como disponibles. */
    function htmlDisponible(registros, titulo) {
        const filas = (registros || []).map((r) => {
            const franja = r.hora_inicio ? `${hora(r.hora_inicio)} – ${hora(r.hora_fin)}` : "Todo el día";
            return `<li>${esc(franja)} · ${esc(r.tipo_registro || "Disponibilidad declarada")}${r.auditor_nombre && titulo ? " · " + esc(r.auditor_nombre) : ""}</li>`;
        });
        if (!filas.length) return "";
        return `<section class="md-dlg-sec md-libre">
  <h4><span class="md-dlg-etq md-libre">Disponible</span> ${esc(titulo || "Franjas declaradas")}</h4>
  <ul class="md-dlg-equipo">${filas.join("")}</ul>
</section>`;
    }

    const FOCO = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
    let dialogo = null;
    let origenDialogo = null;
    function obtenerDialogo() {
        if (dialogo && dialogo.isConnected) return dialogo;
        inyectarEstilos();
        dialogo = document.createElement("dialog");
        dialogo.className = "md-dialogo";
        dialogo.setAttribute("role", "dialog");
        dialogo.setAttribute("aria-modal", "true");
        dialogo.setAttribute("aria-labelledby", "mdDialogoTitulo");
        dialogo.innerHTML = `
  <div class="md-dlg-cab"><h3 id="mdDialogoTitulo"></h3><button type="button" class="md-dlg-cerrar" data-md-cerrar aria-label="Cerrar detalle del día">×</button></div>
  <div class="md-dlg-cuerpo"></div>
  <div class="md-dlg-pie"><button type="button" class="btn btn-secundario btn-sm" data-md-cerrar>Cerrar</button></div>`;
        document.body.appendChild(dialogo);
        dialogo.addEventListener("click", (e) => {
            if (e.target.closest("[data-md-cerrar]") || e.target === dialogo) dialogo.close();
        });
        dialogo.addEventListener("keydown", (e) => {
            if (e.key !== "Tab") return;
            const f = [...dialogo.querySelectorAll(FOCO)].filter((el) => el.getClientRects().length);
            if (!f.length) return;
            const primero = f[0], ultimo = f[f.length - 1];
            if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo.focus(); }
            else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero.focus(); }
        });
        dialogo.addEventListener("close", () => {
            const o = origenDialogo;
            origenDialogo = null;
            if (o && o.isConnected) { try { o.focus(); } catch (_) { } }
        });
        return dialogo;
    }
    /* abrirDialogo({ titulo, html, origen, alAbrir(cuerpo, cerrar) }) */
    function abrirDialogo(op) {
        const dlg = obtenerDialogo();
        dlg.querySelector("#mdDialogoTitulo").textContent = op.titulo || "Detalle";
        const cuerpo = dlg.querySelector(".md-dlg-cuerpo");
        cuerpo.innerHTML = op.html || '<p class="md-vacio">Sin información para este día.</p>';
        cuerpo.scrollTop = 0;
        origenDialogo = op.origen || document.activeElement;
        if (!dlg.open) {
            if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
        }
        if (typeof op.alAbrir === "function") op.alAbrir(cuerpo, () => dlg.close());
        // Foco inicial: el botón de cerrar de la cabecera (el contenido se lee
        // a continuación con el lector de pantalla).
        dlg.querySelector(".md-dlg-cerrar").focus();
        return dlg;
    }

    function montar(contenedor, opciones) {
        if (!contenedor) return null;
        inyectarEstilos();
        const idUsuario = opciones.idUsuario;
        const token = opciones.token || localStorage.getItem("access_token") || "";
        const base = `/agenda-auditor/${encodeURIComponent(idUsuario)}`;
        const hoy = new Date();
        const pref = "md" + Math.random().toString(36).slice(2, 7);

        contenedor.innerHTML = `
<div class="md-bloque">
  <div>
    <h4 class="md-titulo">Horario semanal</h4>
    <p class="md-ayuda">Marca los días en los que puedes atender auditorías y la franja de cada uno. El patrón se repite
      durante la vigencia. Los días con auditorías ya programadas aparecen en rojo en el calendario: aunque los declares,
      no se ofrecerán para programar otra auditoría.</p>
    <form class="md-form" novalidate>
      <div class="md-rejilla">
        <div class="md-campo"><label for="${pref}-desde">Vigente desde</label><input type="date" id="${pref}-desde" name="desde" required></div>
        <div class="md-campo"><label for="${pref}-hasta">Vigente hasta (opcional)</label><input type="date" id="${pref}-hasta" name="hasta"></div>
        <div class="md-campo"><label for="${pref}-motivo">Motivo / observación</label><input id="${pref}-motivo" name="motivo" maxlength="255" placeholder="Disponibilidad semanal"></div>
      </div>
      <div class="md-dias">
        ${DIAS.map((d) => `
        <div class="md-dia" data-dia="${d.clave}">
          <label class="md-dia-nombre"><input type="checkbox" data-check> ${d.texto}</label>
          <div class="md-horas">
            <input type="time" data-ini value="08:00" aria-label="${d.texto}: desde" disabled>
            <input type="time" data-fin value="${d.fin}" aria-label="${d.texto}: hasta" disabled>
          </div>
        </div>`).join("")}
      </div>
      <div class="md-acciones">
        <button type="submit" class="btn btn-primario">Guardar disponibilidad semanal</button>
      </div>
      <div class="md-aviso" role="alert" aria-live="assertive" tabindex="-1"></div>
    </form>
  </div>
  <div class="md-cal-caja"></div>
</div>`;

        const form = contenedor.querySelector(".md-form");
        const aviso = contenedor.querySelector(".md-aviso");
        const desde = form.querySelector(`#${pref}-desde`);
        desde.min = iso(hoy);
        desde.value = iso(hoy);
        form.querySelector(`#${pref}-hasta`).min = iso(hoy);

        function mostrarAviso(texto, tipo, campo) {
            aviso.textContent = texto;
            aviso.className = "md-aviso " + tipo;
            form.querySelectorAll(".md-invalido").forEach((el) => { el.classList.remove("md-invalido"); el.removeAttribute("aria-invalid"); });
            if (campo) { campo.classList.add("md-invalido"); campo.setAttribute("aria-invalid", "true"); }
            const destino = campo || aviso;
            try { destino.scrollIntoView({ behavior: "smooth", block: "center" }); } catch (_) { destino.scrollIntoView(); }
            try { destino.focus({ preventScroll: true }); } catch (_) { }
        }

        form.querySelectorAll(".md-dia").forEach((caja) => {
            const check = caja.querySelector("[data-check]");
            check.addEventListener("change", () => {
                caja.classList.toggle("activo", check.checked);
                caja.querySelectorAll('input[type="time"]').forEach((el) => { el.disabled = !check.checked; });
            });
        });
        form.addEventListener("input", (e) => {
            if (e.target.classList.contains("md-invalido")) { e.target.classList.remove("md-invalido"); e.target.removeAttribute("aria-invalid"); }
        });

        let enviando = false;
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            if (enviando) return;
            const fDesde = desde.value;
            const campoHasta = form.querySelector(`#${pref}-hasta`);
            const fHasta = campoHasta.value || null;
            if (!fDesde) return mostrarAviso("Indique desde cuándo rige el horario.", "error", desde);
            if (fDesde < iso(new Date())) return mostrarAviso("La vigencia debe comenzar hoy o en una fecha futura.", "error", desde);
            if (fHasta && fHasta < fDesde) return mostrarAviso("La fecha final no puede ser anterior a la inicial.", "error", campoHasta);
            const dias = [];
            for (const caja of form.querySelectorAll(".md-dia")) {
                if (!caja.querySelector("[data-check]").checked) continue;
                const ini = caja.querySelector("[data-ini]");
                const fin = caja.querySelector("[data-fin]");
                if (!ini.value || !fin.value || fin.value <= ini.value) {
                    return mostrarAviso("En cada día marcado la hora final debe ser posterior a la inicial.", "error", fin);
                }
                dias.push({ dia_semana: caja.dataset.dia, hora_inicio: ini.value, hora_fin: fin.value });
            }
            if (!dias.length) return mostrarAviso("Marque al menos un día de la semana.", "error", form.querySelector("[data-check]"));
            const motivo = form.querySelector(`#${pref}-motivo`).value.trim() || "Disponibilidad semanal";
            const boton = form.querySelector('button[type="submit"]');
            enviando = true;
            boton.disabled = true;
            try {
                const res = await fetch(`${base}/disponibilidad-semanal`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                    body: JSON.stringify({ fecha_inicio: fDesde, fecha_fin: fHasta, dias, motivo })
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    const det = Array.isArray(data.detail)
                        ? data.detail.map((d) => String(d.msg || "").replace(/^Value error, /, "")).join(" ")
                        : (typeof data.detail === "string" ? data.detail : `Error ${res.status}`);
                    return mostrarAviso(`No se pudo guardar: ${det}`, "error");
                }
                const ocupados = Array.isArray(data.ocupados) ? data.ocupados : [];
                const detalle = ocupados.slice(0, 8).map((o) =>
                    `• ${o.fecha} ${o.hora_inicio}–${o.hora_fin}: ${o.empresa_nombre || o.numero_radicado || "auditoría"}`).join("\n");
                mostrarAviso((data.mensaje || "Disponibilidad semanal guardada.") + (detalle ? "\n" + detalle : ""), ocupados.length ? "info" : "ok");
                await calendarioAuditor.recargar();
                if (typeof opciones.alGuardar === "function") opciones.alGuardar(data);
            } catch (error) {
                mostrarAviso(`No se pudo guardar: ${error.message}`, "error");
            } finally {
                enviando = false;
                boton.disabled = false;
            }
        });

        // ------------------------------------------------ calendario
        function chips(dia, detallado) {
            if (!dia) return [];
            const partes = [];
            if (dia.bloqueado) {
                const motivo = (dia.disponibilidad || [])[0]?.motivo || "";
                partes.push(`<span class="md-chip md-bloqueado" title="${esc("Fecha bloqueada " + motivo)}">Bloqueado${detallado && motivo ? ": " + esc(motivo) : ""}</span>`);
            }
            (dia.auditorias || [])
                .filter((a) => !TERMINALES.includes(String(a.estado || "").trim().toUpperCase()))
                .forEach((a) => {
                    const ini = String(a.fecha_inicio || "").slice(0, 10) === dia.fecha ? horaDeFecha(a.fecha_inicio) : "00:00";
                    const fin = String(a.fecha_fin || "").slice(0, 10) === dia.fecha ? horaDeFecha(a.fecha_fin) : "23:59";
                    const lugar = [a.empresa_nombre, a.sede_nombre].filter(Boolean).join(" · ");
                    const info = `Ocupado ${ini}–${fin}: ${lugar || a.numero_radicado || "auditoría"}${a.modalidad ? " (" + a.modalidad + ")" : ""}`;
                    partes.push(`<span class="md-chip md-ocupado" title="${esc(info + (a.direccion_servicio ? " · " + a.direccion_servicio : ""))}">${esc(detallado ? info + (a.direccion_servicio ? " · " + a.direccion_servicio : "") : `${ini} ${a.empresa_nombre || "Auditoría"}`)}</span>`);
                });
            if (!dia.bloqueado) {
                (dia.disponibilidad || []).forEach((r) => {
                    const franja = r.hora_inicio ? `${hora(r.hora_inicio)}–${hora(r.hora_fin)}` : "Todo el día";
                    partes.push(`<span class="md-chip md-libre" title="${esc((r.tipo_registro || "Disponible") + " " + franja)}">${esc(detallado ? `Horario declarado ${franja} (${r.tipo_registro || "declarado"})` : franja)}</span>`);
                });
            }
            // Regla única (18/11/2026): un día sin bloqueos ni visitas cuenta
            // como disponible aunque no haya disponibilidad declarada.
            if (diaLibre(dia) && !(dia.disponibilidad || []).length && dia.fecha >= iso(new Date())) {
                partes.push(`<span class="md-chip md-libre" title="Sin bloqueos ni visitas">${esc(detallado ? "Disponible (sin bloqueos ni visitas)" : "Disponible")}</span>`);
            }
            return partes.length ? partes : (detallado ? ['<span class="md-vacio">Sin bloqueos ni visitas</span>'] : []);
        }
        // ------------------------------------------- detalle del día (modal)
        const visitasActivas = (dia) => (dia.auditorias || [])
            .filter((a) => !TERMINALES.includes(String(a.estado || "").trim().toUpperCase()));
        // Disponible = sin bloqueo ni visita activa (lo declarado no restringe).
        function diaLibre(dia) {
            if (!dia || dia.bloqueado) return false;
            if (typeof dia.disponible === "boolean") return dia.disponible;
            return !visitasActivas(dia).length;
        }
        function estadoDia(dia) {
            const p = [];
            if (dia.bloqueado) p.push("bloqueado");
            const n = visitasActivas(dia).length;
            if (n) p.push(n === 1 ? "ocupado con 1 visita" : `ocupado con ${n} visitas`);
            if (!p.length && diaLibre(dia)) p.push("disponible");
            return p.join(" y ");
        }
        function detalleDia(dia, f) {
            const bloqueos = dia.bloqueado ? (dia.disponibilidad || []) : [];
            // El DELETE /no-disponible?fecha= quita todos los bloqueos que cubren
            // la fecha; solo se ofrece para hoy o fechas futuras.
            const puedeQuitar = bloqueos.length && f >= iso(new Date());
            const html = [
                ...bloqueos.map((b, i) => htmlBloqueo(b, {
                    acciones: () => (puedeQuitar && i === bloqueos.length - 1
                        ? `<button type="button" class="btn btn-peligro-contorno btn-sm" data-md-desbloquear>Desbloquear</button>
                           <a class="btn btn-secundario btn-sm" href="#desbloquear-fecha" data-md-ir-desbloquear>Ir a Desbloquear fecha</a>`
                        : "")
                })),
                ...visitasActivas(dia).map((v) => htmlVisita(v, { fecha: f, idPropio: idUsuario })),
                dia.bloqueado ? "" : htmlDisponible(dia.disponibilidad, "Horario declarado (informativo)"),
                diaLibre(dia)
                    ? `<section class="md-dlg-sec md-libre"><h4><span class="md-dlg-etq md-libre">Disponible</span> Sin bloqueos ni visitas</h4><p style="margin:0">Pueden programarte una auditoría este día aunque no hayas declarado disponibilidad. Si no puedes atender, bloquea la fecha.</p></section>`
                    : ""
            ].join("");
            return {
                html,
                alAbrir: (cuerpo, cerrar) => {
                    const ir = cuerpo.querySelector("[data-md-ir-desbloquear]");
                    if (ir) ir.addEventListener("click", () => cerrar());
                    const boton = cuerpo.querySelector("[data-md-desbloquear]");
                    if (!boton) return;
                    const caja = boton.parentElement;
                    let confirmando = false;
                    boton.addEventListener("click", async () => {
                        let aviso = caja.querySelector(".md-dlg-aviso");
                        if (!aviso) {
                            aviso = document.createElement("p");
                            aviso.className = "md-dlg-aviso";
                            aviso.setAttribute("role", "status");
                            aviso.tabIndex = -1;
                            caja.after(aviso);
                        }
                        if (!confirmando) {
                            confirmando = true;
                            const b = bloqueos[0];
                            aviso.className = "md-dlg-aviso";
                            aviso.textContent = `Se quitará el bloqueo (${rangoFechas(b.fecha_inicio, b.fecha_fin)}) y la fecha volverá a estar disponible. Pulse "Confirmar desbloqueo" para continuar.`;
                            boton.textContent = "Confirmar desbloqueo";
                            return;
                        }
                        boton.disabled = true;
                        try {
                            const res = await fetch(`${base}/no-disponible?fecha=${encodeURIComponent(f)}`, {
                                method: "DELETE", headers: { Authorization: `Bearer ${token}` }
                            });
                            const data = await res.json().catch(() => ({}));
                            if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Error ${res.status}`);
                            caja.remove();
                            aviso.className = "md-dlg-aviso ok";
                            aviso.textContent = data.mensaje || "Fecha desbloqueada correctamente.";
                            aviso.focus();
                            await calendarioAuditor.recargar();
                            if (typeof opciones.alCambiar === "function") opciones.alCambiar(data);
                        } catch (error) {
                            boton.disabled = false;
                            aviso.className = "md-dlg-aviso error";
                            aviso.textContent = `No se pudo desbloquear: ${error.message}`;
                        }
                    });
                }
            };
        }
        const calendarioAuditor = montarCalendario(contenedor.querySelector(".md-cal-caja"), {
            titulo: "Mi calendario: lo ocupado y lo disponible",
            estadoDia,
            detalleDia,
            leyenda: [["md-libre", "Disponible (sin bloqueos ni visitas) u horario declarado"], ["md-ocupado", "Ocupado por auditoría"], ["md-bloqueado", "Fecha bloqueada"]],
            cargarMes: async (anio, mes) => {
                const res = await fetch(`${base}/disponibilidad-mensual?anio=${anio}&mes=${mes}`, {
                    headers: { Authorization: `Bearer ${token}` }
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Error ${res.status}`);
                const porFecha = new Map();
                (data.dias || []).forEach((d) => porFecha.set(d.fecha, d));
                return porFecha;
            },
            chips
        });
        return calendarioAuditor;
    }

    // ==================================================================
    // Calendario mes / semana reutilizable (auditor y Coordinador).
    // ==================================================================
    function lunesDe(d) {
        const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
        x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
        return x;
    }
    // "2026-11-02" -> fecha local (sin pasar por UTC: no se corre un día).
    function desdeIso(f) {
        const [a, m, d] = String(f).split("-").map(Number);
        return new Date(a, m - 1, d);
    }

    function montarCalendario(caja, op) {
        if (!caja) return null;
        inyectarEstilos();
        const hoy = new Date();
        const estado = {
            vista: op.vistaInicial === "semana" ? "semana" : "mes",
            anio: hoy.getFullYear(), mes: hoy.getMonth() + 1, semana: lunesDe(hoy),
            cache: new Map(), turno: 0
        };
        const maxPorDia = Number(op.maxPorDia) || 0;
        const leyenda = (op.leyenda || []).map(([clase, texto]) => `<span class="${esc(clase)}">${esc(texto)}</span>`).join("");
        caja.innerHTML = `
    ${op.titulo ? `<h4 class="md-titulo">${esc(op.titulo)}</h4>` : ""}
    <div class="md-cal-barra">
      <div class="md-grupo">
        <button type="button" class="btn btn-secundario btn-sm" data-nav="-1" aria-label="Periodo anterior">‹ Anterior</button>
        <button type="button" class="btn btn-secundario btn-sm" data-nav="0">Hoy</button>
        <button type="button" class="btn btn-secundario btn-sm" data-nav="1" aria-label="Periodo siguiente">Siguiente ›</button>
      </div>
      <span class="md-cal-titulo" aria-live="polite"></span>
      <div class="md-grupo" role="group" aria-label="Vista del calendario">
        <button type="button" class="btn btn-secundario btn-sm" data-vista="mes" aria-pressed="true">Mes</button>
        <button type="button" class="btn btn-secundario btn-sm" data-vista="semana" aria-pressed="false">Semana</button>
      </div>
    </div>
    ${leyenda ? `<div class="md-leyenda">${leyenda}</div>` : ""}
    <div class="md-cal"></div>`;
        const cal = caja.querySelector(".md-cal");
        const titulo = caja.querySelector(".md-cal-titulo");

        async function mesDatos(anio, mes) {
            const clave = `${anio}-${mes}`;
            if (!estado.cache.has(clave)) estado.cache.set(clave, Promise.resolve().then(() => op.cargarMes(anio, mes)));
            try { return await estado.cache.get(clave); }
            catch (error) { estado.cache.delete(clave); throw error; }
        }
        function lista(dia, detallado, f) {
            const r = dia ? op.chips(dia, detallado, f) : [];
            return Array.isArray(r) ? r : (r ? [r] : []);
        }
        // "bloqueado", "ocupado con 2 visitas"...; vacío = el día no abre detalle.
        function estadoDe(dia, f) {
            if (!dia || typeof op.estadoDia !== "function" || typeof op.detalleDia !== "function") return "";
            return String(op.estadoDia(dia, f) || "");
        }
        async function abrirDia(f, origen) {
            const d = desdeIso(f);
            let dia = null;
            try { dia = (await mesDatos(d.getFullYear(), d.getMonth() + 1)).get(f) || null; } catch (_) { dia = null; }
            const det = (dia && op.detalleDia(dia, f)) || {};
            abrirDialogo({ titulo: `Detalle del ${fechaLarga(f)}`, html: det.html, origen, alAbrir: det.alAbrir });
        }
        async function pintar() {
            // Si se navega rápido, solo se pinta la última petición.
            const turno = ++estado.turno;
            caja.querySelectorAll("[data-vista]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.vista === estado.vista)));
            cal.innerHTML = '<p class="md-vacio">Cargando calendario...</p>';
            const hoyIso = iso(new Date());
            try {
                if (estado.vista === "mes") {
                    titulo.textContent = `${MESES[estado.mes - 1]} ${estado.anio}`;
                    const datos = await mesDatos(estado.anio, estado.mes);
                    if (turno !== estado.turno) return;
                    const primero = new Date(estado.anio, estado.mes - 1, 1);
                    const inicio = lunesDe(primero);
                    let html = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"].map((d) => `<div class="md-cab">${d}</div>`).join("");
                    for (let i = 0; i < 42; i++) {
                        const d = new Date(inicio); d.setDate(inicio.getDate() + i);
                        if (i >= 35 && d.getMonth() !== primero.getMonth()) break;
                        const f = iso(d);
                        const dentro = d.getMonth() === primero.getMonth();
                        let partes = dentro ? lista(datos.get(f), false, f) : [];
                        if (maxPorDia && partes.length > maxPorDia) {
                            const resto = partes.length - (maxPorDia - 1);
                            partes = partes.slice(0, maxPorDia - 1).concat(
                                `<button type="button" class="md-chip md-mas" data-md-semana="${f}" aria-label="Ver ${resto} más del ${d.getDate()} en la vista semana">+${resto} más</button>`);
                        }
                        const est = dentro ? estadoDe(datos.get(f), f) : "";
                        const num = est
                            ? `<button type="button" class="md-dia-btn" data-md-dia="${f}" aria-haspopup="dialog" aria-label="${esc(`Ver detalle del ${diaMes(f)}: ${est}`)}">${d.getDate()}</button>`
                            : `<div class="md-num">${d.getDate()}</div>`;
                        html += `<div class="md-celda${dentro ? "" : " fuera"}${f === hoyIso ? " hoy" : ""}${est ? " md-clic" : ""}" data-fecha="${f}"${f === hoyIso ? ' aria-current="date"' : ""}>${num}${partes.join("")}</div>`;
                    }
                    cal.innerHTML = `<div class="md-mes">${html}</div>`;
                } else {
                    const dias = Array.from({ length: 7 }, (_, i) => { const d = new Date(estado.semana); d.setDate(d.getDate() + i); return d; });
                    titulo.textContent = `Semana del ${dias[0].getDate()} de ${MESES[dias[0].getMonth()]} al ${dias[6].getDate()} de ${MESES[dias[6].getMonth()]} ${dias[6].getFullYear()}`;
                    const meses = [...new Set(dias.map((d) => `${d.getFullYear()}-${d.getMonth() + 1}`))];
                    const mapas = await Promise.all(meses.map((m) => { const [a, mm] = m.split("-").map(Number); return mesDatos(a, mm); }));
                    if (turno !== estado.turno) return;
                    const buscar = (f) => { for (const m of mapas) if (m.has(f)) return m.get(f); return null; };
                    cal.innerHTML = `<div class="md-semana">${dias.map((d) => {
                        const f = iso(d);
                        const nombre = d.toLocaleDateString("es-CO", { weekday: "long", day: "numeric", month: "short" });
                        const est = estadoDe(buscar(f), f);
                        const cab = est
                            ? `<div><button type="button" class="md-dia-btn md-fecha" data-md-dia="${f}" aria-haspopup="dialog" aria-label="${esc(`Ver detalle del ${diaMes(f)}: ${est}`)}">${esc(nombre)} <span class="md-ver" aria-hidden="true">Ver detalle</span></button></div>`
                            : `<div class="md-fecha">${esc(nombre)}</div>`;
                        return `<div class="md-fila${f === hoyIso ? " hoy" : ""}${est ? " md-clic" : ""}" data-fecha="${f}"${f === hoyIso ? ' aria-current="date"' : ""}>${cab}<div>${lista(buscar(f), true, f).join("")}</div></div>`;
                    }).join("")}</div>`;
                }
            } catch (error) {
                if (turno !== estado.turno) return;
                cal.innerHTML = `<p class="md-vacio">No se pudo cargar el calendario: ${esc(error.message)}</p>`;
            }
        }
        caja.querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", () => {
            const paso = Number(b.dataset.nav);
            if (paso === 0) {
                const h = new Date();
                estado.anio = h.getFullYear(); estado.mes = h.getMonth() + 1; estado.semana = lunesDe(h);
            } else if (estado.vista === "mes") {
                const d = new Date(estado.anio, estado.mes - 1 + paso, 1);
                estado.anio = d.getFullYear(); estado.mes = d.getMonth() + 1;
            } else {
                estado.semana.setDate(estado.semana.getDate() + 7 * paso);
            }
            pintar();
        }));
        caja.querySelectorAll("[data-vista]").forEach((b) => b.addEventListener("click", () => {
            estado.vista = b.dataset.vista;
            if (estado.vista === "semana") {
                const h = new Date();
                const enMes = h.getFullYear() === estado.anio && h.getMonth() + 1 === estado.mes;
                estado.semana = lunesDe(enMes ? h : new Date(estado.anio, estado.mes - 1, 1));
            } else {
                estado.anio = estado.semana.getFullYear(); estado.mes = estado.semana.getMonth() + 1;
            }
            pintar();
        }));
        // "+N más": abre la semana de ese día con todo el detalle.
        cal.addEventListener("click", (e) => {
            const mas = e.target.closest("[data-md-semana]");
            if (!mas) {
                // Detalle del día: el botón del número/fecha o cualquier punto
                // libre de la celda (los chips con acción propia no).
                let boton = e.target.closest("[data-md-dia]");
                if (!boton) {
                    if (e.target.closest("button, a, input, select, textarea")) return;
                    const celda = e.target.closest(".md-clic");
                    boton = celda && celda.querySelector("[data-md-dia]");
                }
                if (boton) abrirDia(boton.dataset.mdDia, boton);
                return;
            }
            estado.vista = "semana";
            estado.semana = lunesDe(desdeIso(mas.dataset.mdSemana));
            pintar().then(() => {
                // El foco pasa a la primera auditoría de ese día (o a la fila).
                const fila = cal.querySelector(`[data-fecha="${mas.dataset.mdSemana}"]`);
                const destino = fila && (fila.querySelector("button:not([data-md-dia])") || fila.querySelector("button") || fila);
                if (destino) {
                    if (destino === fila) fila.setAttribute("tabindex", "-1");
                    try { destino.focus({ preventScroll: false }); } catch (_) { }
                }
            });
        });

        pintar();
        return { recargar: () => { estado.cache.clear(); return pintar(); }, pintar, abrirDia };
    }

    window.MiDisponibilidad = {
        montar,
        calendario: montarCalendario,
        dialogo: abrirDialogo,
        detalle: { visita: htmlVisita, bloqueo: htmlBloqueo, disponible: htmlDisponible, fechaLarga, fechaHoraCorta, esc }
    };
})();
