/* =========================================================
   MODALES ACCESIBLES (comun a todas las pantallas internas)

   Lo carga static/nav.js. Muchas pantallas arman sus ventanas
   modales con un <div> que se muestra cambiando una clase
   (.show, .active, .open, quitando .hidden...) o el estilo
   display. Este archivo NO cambia esa logica: solo observa
   cuando una de esas ventanas aparece o desaparece y entonces:

   - le pone role="dialog", aria-modal="true" y aria-labelledby
     (con su titulo) si la pantalla no los trae;
   - mueve el foco al primer control de la ventana;
   - mantiene el Tab dentro de la ventana mientras este abierta;
   - con Escape pulsa el boton de cerrar/cancelar de la propia
     pantalla (asi se respeta lo que ese boton haga);
   - bloquea el desplazamiento de la pagina de fondo;
   - al cerrarse devuelve el foco al elemento que la abrio.

   Los <dialog> nativos no se tocan: el navegador ya hace todo esto.
   ========================================================= */
(function () {
  "use strict";
  if (window.__modalesAccesibles) return;
  window.__modalesAccesibles = true;

  var SELECTOR_MODAL = ".modal-overlay, .modal, [data-modal], .audit-modal, .notif-modal";
  var SELECTOR_FOCO = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), ' +
    'select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';
  var SELECTOR_TITULO = "h1, h2, h3, h4, .modal-title, .modal-titulo";
  var SELECTOR_CERRAR = '[data-close], [data-cerrar], .modal-close, .btn-close, .close, .cerrar, .modal-cancel, ' +
    'button[aria-label^="Cerrar"], button[aria-label^="cerrar"]';

  var abiertos = [];            // pila: el ultimo es el que esta encima
  var estado = new WeakMap();   // modal -> { abierto, opener }
  var contador = 0;
  var pendiente = false;

  function esRaiz(el) {
    if (!el || el.tagName === "DIALOG" || el.closest("dialog")) return false;
    var padre = el.parentElement && el.parentElement.closest(SELECTOR_MODAL);
    return !padre;
  }

  function estaVisible(el) {
    if (!el.isConnected || el.hidden) return false;
    var cs = window.getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return false;
    if (parseFloat(cs.opacity) === 0 && cs.pointerEvents === "none") return false;
    return el.getClientRects().length > 0;
  }

  function enfocables(modal) {
    return Array.prototype.filter.call(modal.querySelectorAll(SELECTOR_FOCO), function (el) {
      return el.offsetParent !== null || el.getClientRects().length > 0;
    });
  }

  function prepararAria(modal) {
    var dialogo = modal;
    if (!modal.getAttribute("role")) modal.setAttribute("role", "dialog");
    if (!modal.hasAttribute("aria-modal")) modal.setAttribute("aria-modal", "true");
    if (!dialogo.hasAttribute("aria-labelledby") && !dialogo.hasAttribute("aria-label")) {
      var titulo = modal.querySelector(SELECTOR_TITULO);
      if (titulo) {
        if (!titulo.id) titulo.id = "modal-titulo-" + (++contador);
        dialogo.setAttribute("aria-labelledby", titulo.id);
      }
    }
  }

  function bloquearScroll() {
    document.body.classList.toggle("modal-abierto", abiertos.length > 0);
  }

  function alAbrir(modal, info) {
    info.opener = document.activeElement && document.activeElement !== document.body ? document.activeElement : null;
    if (info.opener && modal.contains(info.opener)) info.opener = null;
    abiertos.push(modal);
    prepararAria(modal);
    bloquearScroll();
    // Si la pantalla ya puso el foco dentro (p. ej. en un campo), se respeta.
    if (!modal.contains(document.activeElement)) {
      var lista = enfocables(modal);
      var destino = lista[0];
      if (destino) {
        destino.focus({ preventScroll: true });
      } else {
        if (!modal.hasAttribute("tabindex")) modal.setAttribute("tabindex", "-1");
        modal.focus({ preventScroll: true });
      }
    }
  }

  function alCerrar(modal, info) {
    var i = abiertos.indexOf(modal);
    if (i >= 0) abiertos.splice(i, 1);
    bloquearScroll();
    var activo = document.activeElement;
    var focoPerdido = !activo || activo === document.body || modal.contains(activo);
    var opener = info.opener;
    info.opener = null;
    if (focoPerdido && opener && opener.isConnected && estaVisible(opener)) {
      opener.focus({ preventScroll: true });
    } else if (focoPerdido && abiertos.length) {
      var lista = enfocables(abiertos[abiertos.length - 1]);
      if (lista[0]) lista[0].focus({ preventScroll: true });
    }
  }

  function revisar(inicial) {
    pendiente = false;
    var candidatos = document.querySelectorAll(SELECTOR_MODAL);
    var vistos = [];
    Array.prototype.forEach.call(candidatos, function (modal) {
      if (!esRaiz(modal)) return;
      vistos.push(modal);
      var info = estado.get(modal);
      if (!info) { info = { abierto: false, opener: null }; estado.set(modal, info); }
      var visible = estaVisible(modal);
      if (visible === info.abierto) return;
      info.abierto = visible;
      if (inicial) {
        // Lo que ya estaba visible al cargar no se trata como modal abierto
        // (no se atrapa el foco ni se bloquea la pagina): solo se observa.
        return;
      }
      if (visible) alAbrir(modal, info); else alCerrar(modal, info);
    });
    // Modales que salieron del DOM estando abiertos.
    abiertos.slice().forEach(function (modal) {
      if (vistos.indexOf(modal) === -1) {
        var info = estado.get(modal) || { opener: null };
        info.abierto = false;
        alCerrar(modal, info);
      }
    });
  }

  function programar() {
    if (pendiente) return;
    pendiente = true;
    // Microtarea: corre despues del codigo de la pantalla que abrio el modal.
    Promise.resolve().then(function () { revisar(false); });
    // Segunda pasada por si el modal aparece con una transicion.
    setTimeout(function () { revisar(false); }, 350);
  }

  function botonCerrar(modal) {
    var botones = modal.querySelectorAll(SELECTOR_CERRAR);
    for (var i = 0; i < botones.length; i++) {
      if (estaVisible(botones[i]) && !botones[i].disabled) return botones[i];
    }
    var todos = modal.querySelectorAll("button");
    for (var j = 0; j < todos.length; j++) {
      var b = todos[j];
      var texto = (b.textContent || "").trim();
      var onclick = b.getAttribute("onclick") || "";
      if (b.disabled || !estaVisible(b)) continue;
      if (/^(×|✕|x|cerrar|cancelar|volver)$/i.test(texto) || /cerrar|close/i.test(onclick)) return b;
    }
    return null;
  }

  function modalActivo() {
    // Si hay un <dialog> nativo abierto encima, el navegador manda.
    if (document.querySelector("dialog[open]")) return null;
    for (var i = abiertos.length - 1; i >= 0; i--) {
      if (estaVisible(abiertos[i])) return abiertos[i];
    }
    return null;
  }

  document.addEventListener("keydown", function (ev) {
    var modal = modalActivo();
    if (!modal) return;
    if (ev.key === "Escape" || ev.key === "Esc") {
      if (ev.defaultPrevented) return;
      var cerrar = botonCerrar(modal);
      if (cerrar) {
        ev.preventDefault();
        cerrar.click();
      }
      return;
    }
    if (ev.key !== "Tab") return;
    var lista = enfocables(modal);
    if (!lista.length) { ev.preventDefault(); modal.focus(); return; }
    var primero = lista[0];
    var ultimo = lista[lista.length - 1];
    var activo = document.activeElement;
    if (!modal.contains(activo)) {
      ev.preventDefault();
      (ev.shiftKey ? ultimo : primero).focus();
    } else if (ev.shiftKey && (activo === primero || activo === modal)) {
      ev.preventDefault();
      ultimo.focus();
    } else if (!ev.shiftKey && activo === ultimo) {
      ev.preventDefault();
      primero.focus();
    }
  });

  // Si el foco se escapa (clic fuera, script), vuelve al modal de encima.
  document.addEventListener("focusin", function (ev) {
    var modal = modalActivo();
    if (!modal || modal.contains(ev.target)) return;
    if (ev.target.closest && ev.target.closest("dialog")) return;
    var lista = enfocables(modal);
    (lista[0] || modal).focus({ preventScroll: true });
  });

  function iniciar() {
    revisar(true);
    new MutationObserver(programar).observe(document.body, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["class", "style", "hidden", "open"]
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else {
    iniciar();
  }
})();
