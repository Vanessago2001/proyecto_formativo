/* =========================================================
   SOLICITUDES · ETAPAS (static/solicitudes.html, 18/11/2026)

   Une "Revisión de solicitudes" y "Asignación de auditores" en una
   sola pantalla que sigue cada solicitud por su ciclo:

     #radicadas      1. Radicadas          (static/solicitudes-revision.js)
     #revision       2. En revisión        (static/solicitudes-revision.js)
     #por-asignar    3. Por asignar auditor (static/solicitudes-asignacion.js)
     #con-auditores  4. Con auditores      (static/solicitudes-asignacion.js)
     #todas          Todas: buscador general

   Las etapas son botones button[data-etapa] del menú interno (nav.side),
   que static/nav.js oculta y usa como "proxy" desde el menú común. Los
   pasos visibles (con contador) llaman a la misma función.

   Direcciones anteriores: /revision-solicitudes y /asignacion-auditores
   redirigen aquí con ?etapa=...; si traían un "#" viejo, el navegador
   lo conserva y se traduce con ALIAS.
   ========================================================= */
(() => {
  "use strict";

  const token = localStorage.getItem("access_token");
  if (!token) return;

  function leerToken(valor) {
    try {
      const parte = valor.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
      return JSON.parse(decodeURIComponent(atob(parte).split("").map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2)).join("")));
    } catch (_) {
      return null;
    }
  }

  // Coordinador ("Administrador" es su nombre anterior) y Auxiliar.
  const ROLES_PERMITIDOS = ["coordinador", "administrador", "admin", "adm", "auxiliar", "aux"];
  const payload = leerToken(token);
  const rol = String((payload && payload.role_name) || "").trim().toLowerCase();
  if (!ROLES_PERMITIDOS.includes(rol)) {
    window.location.href = "/dashboard";
    return;
  }

  const ETAPAS = {
    radicadas: {
      titulo: "Radicadas",
      descripcion: "Solicitudes que la empresa envió. Al abrir una, pasa automáticamente a \"En revisión\".",
      panel: "etapaRevision"
    },
    revision: {
      titulo: "En revisión",
      descripcion: "Revise los documentos legales de la empresa, los de la solicitud y sus sedes; pida correcciones y apruebe o rechace. Al aprobarla pasa directamente a \"Por asignar auditor\".",
      panel: "etapaRevision"
    },
    "por-asignar": {
      titulo: "Por asignar auditor",
      descripcion: "Solicitudes aprobadas sin auditor. Elija uno; el sistema valida su elegibilidad antes de asignarlo.",
      panel: "etapaPorAsignar"
    },
    "con-auditores": {
      titulo: "Con auditores",
      descripcion: "Solicitudes con auditor asignado: programe la visita en Agenda o gestione la asignación.",
      panel: "etapaConAuditores"
    },
    todas: {
      titulo: "Todas las solicitudes",
      descripcion: "Buscador general: filtre por estado, fechas, ubicación, norma o texto.",
      panel: "etapaRevision"
    }
  };

  // "#..." de las pantallas anteriores (y variantes) -> etapa.
  const ALIAS = {
    radicadas: "radicadas", radicada: "radicadas",
    revision: "revision", "en-revision": "revision",
    "por-asignar": "por-asignar", porasignar: "por-asignar", asignar: "por-asignar",
    asignacion: "por-asignar", "nueva-asignacion": "por-asignar",
    "con-auditores": "con-auditores", asignados: "con-auditores", asignaciones: "con-auditores",
    "auditores-asignados": "con-auditores", cambios: "con-auditores",
    todas: "todas"
  };

  let actual = null;

  function etapaDe(texto) {
    return ALIAS[String(texto || "").replace(/^#/, "").trim().toLowerCase()] || null;
  }

  function marcar(etapa) {
    document.querySelectorAll("button[data-etapa]").forEach((boton) => {
      const activo = boton.dataset.etapa === etapa;
      boton.classList.toggle("active", activo);
      if (activo) boton.setAttribute("aria-current", "page"); else boton.removeAttribute("aria-current");
    });
    document.querySelectorAll("button[data-paso]").forEach((boton) => {
      const activo = boton.dataset.paso === etapa;
      boton.classList.toggle("activo", activo);
      if (activo) boton.setAttribute("aria-current", "step"); else boton.removeAttribute("aria-current");
    });
  }

  async function ir(etapa, opciones) {
    if (!ETAPAS[etapa]) etapa = "radicadas";
    opciones = opciones || {};
    const repetida = etapa === actual && !opciones.solicitud && !opciones.forzar;
    actual = etapa;
    const config = ETAPAS[etapa];
    marcar(etapa);
    ["etapaRevision", "etapaPorAsignar", "etapaConAuditores"].forEach((id) => {
      const panel = document.getElementById(id);
      if (panel) panel.hidden = id !== config.panel;
    });
    document.getElementById("viewTitle").textContent = config.titulo;
    document.getElementById("viewDescription").textContent = config.descripcion;
    document.title = "CertiSENA | Solicitudes · " + config.titulo;
    if (window.location.hash !== "#" + etapa || window.location.search) {
      window.history.replaceState(null, "", window.location.pathname + "#" + etapa);
    }
    if (repetida) return;
    if (config.panel === "etapaRevision") {
      if (window.SolicitudesRevision) window.SolicitudesRevision.mostrar(etapa);
    } else if (window.SolicitudesAsignacion) {
      if (opciones.solicitud && etapa === "por-asignar") {
        await window.SolicitudesAsignacion.abrirSolicitud(opciones.solicitud, opciones.radicado);
      } else {
        await window.SolicitudesAsignacion.activar(etapa);
      }
    }
  }

  // ---------------- contadores ----------------
  const CLAVES = { radicadas: "radicadas", revision: "revision", "por-asignar": "por_asignar", "con-auditores": "con_auditores", todas: "todas" };

  async function recargarContadores() {
    try {
      const respuesta = await fetch("/asignacion-auditores/conteo-etapas", { headers: { Authorization: "Bearer " + token } });
      if (!respuesta.ok) throw new Error(String(respuesta.status));
      const datos = await respuesta.json();
      Object.keys(CLAVES).forEach((etapa) => {
        const valor = Number(datos[CLAVES[etapa]] || 0);
        document.querySelectorAll('[data-contador="' + etapa + '"]').forEach((el) => {
          el.textContent = String(valor);
          el.classList.toggle("vacio", valor === 0);
          el.setAttribute("aria-label", valor + (etapa === "con-auditores"
            ? (valor === 1 ? " asignación" : " asignaciones")
            : (valor === 1 ? " solicitud" : " solicitudes")));
        });
      });
    } catch (_) {
      document.querySelectorAll("[data-contador]").forEach((el) => { el.textContent = "–"; el.removeAttribute("aria-label"); });
    }
  }

  // ---------------- eventos ----------------
  document.querySelectorAll("button[data-etapa]").forEach((boton) =>
    boton.addEventListener("click", () => ir(boton.dataset.etapa)));
  document.querySelectorAll("button[data-paso]").forEach((boton) =>
    boton.addEventListener("click", () => ir(boton.dataset.paso)));
  window.addEventListener("hashchange", () => {
    const etapa = etapaDe(window.location.hash);
    if (etapa && etapa !== actual) ir(etapa);
  });

  window.SolicitudesEtapas = { ir, recargarContadores, actual: () => actual };

  const desdeQuery = new URLSearchParams(window.location.search).get("etapa");
  ir(etapaDe(window.location.hash) || etapaDe(desdeQuery) || "radicadas");
  recargarContadores();
})();
