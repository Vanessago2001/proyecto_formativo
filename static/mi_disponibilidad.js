/*
 * Mi disponibilidad (auditor)
 * ---------------------------------------------------------------
 * Bloque común para que el auditor configure su horario semanal mientras
 * ve, en un calendario (mes o semana), las auditorías que ya tiene
 * programadas y sus fechas bloqueadas. Lo usan:
 *   - static/perfil_auditor.html     (sección #disponibilidad)
 *   - static/disponibilidad_auditor.html (sección "Horario semanal")
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
 *     chips: (dia, detallado, fechaIso) => [html, ...]
 *   })  ->  { recargar(), pintar() }
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
.md-dias { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-top: 14px; }
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
@media (max-width: 640px) {
  .md-celda { min-height: 64px; font-size: 10px; }
  .md-celda .md-chip { font-size: 9px; }
  .md-semana .md-fila { grid-template-columns: 1fr; }
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
                    partes.push(`<span class="md-chip md-libre" title="${esc((r.tipo_registro || "Disponible") + " " + franja)}">${esc(detallado ? `Disponible ${franja} (${r.tipo_registro || "declarado"})` : franja)}</span>`);
                });
            }
            return partes.length ? partes : (detallado ? ['<span class="md-vacio">Sin disponibilidad declarada</span>'] : []);
        }
        const calendarioAuditor = montarCalendario(contenedor.querySelector(".md-cal-caja"), {
            titulo: "Mi calendario: lo ocupado y lo disponible",
            leyenda: [["md-libre", "Disponible (declarado)"], ["md-ocupado", "Ocupado por auditoría"], ["md-bloqueado", "Fecha bloqueada"]],
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
                        html += `<div class="md-celda${dentro ? "" : " fuera"}${f === hoyIso ? " hoy" : ""}" data-fecha="${f}"${f === hoyIso ? ' aria-current="date"' : ""}><div class="md-num">${d.getDate()}</div>${partes.join("")}</div>`;
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
                        return `<div class="md-fila${f === hoyIso ? " hoy" : ""}" data-fecha="${f}"${f === hoyIso ? ' aria-current="date"' : ""}><div class="md-fecha">${esc(nombre)}</div><div>${lista(buscar(f), true, f).join("")}</div></div>`;
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
            if (!mas) return;
            estado.vista = "semana";
            estado.semana = lunesDe(desdeIso(mas.dataset.mdSemana));
            pintar().then(() => {
                // El foco pasa a la primera auditoría de ese día (o a la fila).
                const fila = cal.querySelector(`[data-fecha="${mas.dataset.mdSemana}"]`);
                const destino = fila && (fila.querySelector("button") || fila);
                if (destino) {
                    if (destino === fila) fila.setAttribute("tabindex", "-1");
                    try { destino.focus({ preventScroll: false }); } catch (_) { }
                }
            });
        });

        pintar();
        return { recargar: () => { estado.cache.clear(); return pintar(); }, pintar };
    }

    window.MiDisponibilidad = { montar, calendario: montarCalendario };
})();
