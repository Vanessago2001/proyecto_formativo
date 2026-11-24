/*
 * Filtros de ubicación (ciudad, departamento, país) que filtran mientras se escribe.
 *
 * Uso típico:
 *   contenedor.innerHTML = FiltrosUbicacion.html({ prefijo: "emp", campos: ["ciudad", "departamento", "pais"] });
 *   const filtros = FiltrosUbicacion.ligar(contenedor, { prefijo: "emp", campos: [...], alCambiar: (valores) => pintar() });
 *   filtros.sugerir("ciudad", ["Bogotá", "Pereira"]);
 *   const visibles = lista.filter((x) => FiltrosUbicacion.cumple(filtros.valores(), { ciudad: [x.ciudad] }));
 *   filtros.anunciar(visibles.length + " empresas");
 *
 * La comparación no distingue mayúsculas ni tildes y es por coincidencia
 * parcial: "bogo" encuentra "Bogotá". Un filtro vacío no restringe nada.
 */
(function () {
  "use strict";

  var ETIQUETAS = { ciudad: "Ciudad", departamento: "Departamento", pais: "País" };
  var EJEMPLOS = { ciudad: "Ej.: Bogotá", departamento: "Ej.: Risaralda", pais: "Ej.: Colombia" };
  var SUFIJOS = { ciudad: "Ciudad", departamento: "Departamento", pais: "Pais" };
  var LUGAR = { ciudad: "esa ciudad", departamento: "ese departamento", pais: "ese país" };

  function normalizar(valor) {
    return String(valor == null ? "" : valor)
      .normalize("NFD").replace(/[̀-ͯ]/g, "")
      .toLowerCase().replace(/\s+/g, " ").trim();
  }

  // true si el filtro está vacío o alguno de los valores lo contiene.
  function coincide(valores, filtro) {
    var buscado = normalizar(filtro);
    if (!buscado) return true;
    return [].concat(valores == null ? [] : valores).some(function (v) {
      return normalizar(v).indexOf(buscado) !== -1;
    });
  }

  // `mapa` indica, por campo, de dónde sale el dato de cada elemento: { ciudad: [a, b], pais: [c] }.
  function cumple(valoresFiltro, mapa) {
    return Object.keys(valoresFiltro || {}).every(function (clave) {
      if (!normalizar(valoresFiltro[clave])) return true;
      return coincide(mapa && mapa[clave], valoresFiltro[clave]);
    });
  }

  function hayFiltros(valoresFiltro) {
    return Object.keys(valoresFiltro || {}).some(function (k) { return normalizar(valoresFiltro[k]) !== ""; });
  }

  function debounce(fn, ms) {
    var temporizador = null;
    return function () {
      var args = arguments, ctx = this;
      clearTimeout(temporizador);
      temporizador = setTimeout(function () { fn.apply(ctx, args); }, ms == null ? 300 : ms);
    };
  }

  // Valores distintos (sin repetir por mayúsculas/tildes), ordenados alfabéticamente.
  function valoresUnicos(lista) {
    var vistos = {};
    var salida = [];
    [].concat(lista || []).forEach(function (v) {
      if (Array.isArray(v)) { v.forEach(function (x) { agregar(x); }); return; }
      agregar(v);
    });
    function agregar(v) {
      var texto = String(v == null ? "" : v).trim();
      var clave = normalizar(texto);
      if (!clave || vistos[clave]) return;
      vistos[clave] = true;
      salida.push(texto);
    }
    return salida.sort(function (a, b) { return a.localeCompare(b, "es", { sensitivity: "base" }); });
  }

  function esc(valor) {
    return String(valor == null ? "" : valor)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function idCampo(prefijo, clave) { return prefijo + SUFIJOS[clave]; }

  // "No hay empresas en esa ciudad y ese departamento."
  function mensajeVacio(sustantivoPlural, valoresFiltro) {
    var lugares = Object.keys(valoresFiltro || {})
      .filter(function (k) { return normalizar(valoresFiltro[k]) && LUGAR[k]; })
      .map(function (k) { return LUGAR[k]; });
    if (!lugares.length) return "No hay " + sustantivoPlural + " para mostrar.";
    var texto = lugares.length === 1 ? lugares[0] : lugares.slice(0, -1).join(", ") + " y " + lugares[lugares.length - 1];
    return "No hay " + sustantivoPlural + " en " + texto + ".";
  }

  /*
   * Marcado de los campos. Opciones:
   *   prefijo   (obligatorio) prefijo de los id: <prefijo>Ciudad, <prefijo>Departamento, <prefijo>Pais.
   *   campos    claves a mostrar (por defecto las tres).
   *   etiquetas textos de las etiquetas por clave.
   *   ayudas    texto de ayuda por clave (se asocia con aria-describedby).
   *   valores   valores iniciales por clave.
   *   limpiar   false para no mostrar el botón "Limpiar filtros".
   *   estado    false para no incluir la región aria-live del conteo.
   *   panel     true para enmarcarlo como una barra de filtros.
   */
  function html(opciones) {
    var o = opciones || {};
    var campos = o.campos || ["ciudad", "departamento", "pais"];
    var etiquetas = o.etiquetas || {};
    var ayudas = o.ayudas || {};
    var valores = o.valores || {};
    var partes = campos.map(function (clave) {
      var id = idCampo(o.prefijo, clave);
      var idOpciones = id + "Opciones";
      var idBoton = id + "Toggle";
      var ayuda = ayudas[clave] ? '<small id="' + id + 'Ayuda" class="fu-ayuda">' + esc(ayudas[clave]) + "</small>" : "";
      return '<div class="fu-campo"><label for="' + id + '">' + esc(etiquetas[clave] || ETIQUETAS[clave]) + "</label>" +
        '<div class="fu-control"><input id="' + id + '" class="campo" type="search" autocomplete="off" maxlength="100"' +
        ' placeholder="' + esc(EJEMPLOS[clave]) + '" value="' + esc(valores[clave] || "") + '"' +
        (ayuda ? ' aria-describedby="' + id + 'Ayuda"' : "") +
        ' aria-autocomplete="list" aria-controls="' + idOpciones + '" aria-expanded="false" data-fu-clave="' + clave + '">' +
        '<button id="' + idBoton + '" class="fu-toggle" type="button" aria-label="Mostrar opciones de ' +
        esc(etiquetas[clave] || ETIQUETAS[clave]) + '" aria-controls="' + idOpciones + '" aria-expanded="false"><span aria-hidden="true">▾</span></button>' +
        '<div id="' + idOpciones + '" class="fu-opciones" role="listbox" hidden></div></div>' + ayuda + "</div>";
    });
    if (o.limpiar !== false) {
      // El espaciador ocupa el alto de una etiqueta para alinear el botón con los campos.
      partes.push('<div class="fu-acciones"><span class="fu-espaciador" aria-hidden="true">&nbsp;</span>' +
        '<button type="button" class="btn btn-secundario btn-sm" id="' + o.prefijo + 'Limpiar">Limpiar filtros</button></div>');
    }
    var bloque = '<div class="filtros-ubicacion" role="group" aria-label="' + esc(o.titulo || "Filtrar por ubicación") + '">' + partes.join("") + "</div>" +
      (o.estado === false ? "" : '<p id="' + o.prefijo + 'Estado" class="fu-estado" role="status" aria-live="polite"></p>');
    // `panel: true` lo enmarca como las barras de filtros (comite-toolbar).
    return o.panel ? '<div class="fu-panel">' + bloque + "</div>" : bloque;
  }

  /*
   * Liga los campos ya pintados. `alCambiar(valores)` se llama 300 ms después
   * de dejar de escribir (o al instante con "Limpiar filtros").
   * `botonLimpiar` permite usar un botón propio de la página.
   */
  function ligar(raiz, opciones) {
    var o = opciones || {};
    var base = raiz || document;
    var campos = o.campos || ["ciudad", "departamento", "pais"];
    var buscar = function (id) { return (base.querySelector ? base.querySelector("#" + id) : null) || document.getElementById(id); };
    var entradas = {};
    var sugerencias = {};
    campos.forEach(function (clave) { entradas[clave] = buscar(idCampo(o.prefijo, clave)); });
    var estado = buscar(o.prefijo + "Estado");
    var botonLimpiar = o.botonLimpiar || buscar(o.prefijo + "Limpiar");

    function listaDe(clave) { return buscar(idCampo(o.prefijo, clave) + "Opciones"); }
    function botonDe(clave) { return buscar(idCampo(o.prefijo, clave) + "Toggle"); }

    function cerrarLista(clave) {
      var lista = listaDe(clave);
      var entrada = entradas[clave];
      var boton = botonDe(clave);
      if (lista) lista.hidden = true;
      if (entrada) entrada.setAttribute("aria-expanded", "false");
      if (boton) boton.setAttribute("aria-expanded", "false");
    }

    function mostrarLista(clave, filtro) {
      var lista = listaDe(clave);
      var entrada = entradas[clave];
      var boton = botonDe(clave);
      if (!lista || !entrada) return;

      var buscado = normalizar(filtro == null ? entrada.value : filtro);
      var coincidencias = (sugerencias[clave] || []).filter(function (valor) {
        return !buscado || normalizar(valor).indexOf(buscado) !== -1;
      });
      lista.textContent = "";
      coincidencias.forEach(function (valor) {
        var opcion = document.createElement("button");
        opcion.type = "button";
        opcion.className = "fu-opcion";
        opcion.setAttribute("role", "option");
        opcion.setAttribute("aria-selected", "false");
        opcion.textContent = valor;
        opcion.addEventListener("mousedown", function (evento) { evento.preventDefault(); });
        opcion.addEventListener("click", function () {
          entrada.value = valor;
          cerrarLista(clave);
          entrada.focus();
          avisarLuego();
        });
        lista.appendChild(opcion);
      });
      lista.hidden = coincidencias.length === 0;
      entrada.setAttribute("aria-expanded", coincidencias.length ? "true" : "false");
      if (boton) boton.setAttribute("aria-expanded", coincidencias.length ? "true" : "false");
    }

    function valores() {
      var salida = {};
      campos.forEach(function (clave) { salida[clave] = entradas[clave] ? entradas[clave].value.trim() : ""; });
      return salida;
    }
    var avisar = function () { if (typeof o.alCambiar === "function") o.alCambiar(valores()); };
    var avisarLuego = debounce(avisar, o.retardo == null ? 300 : o.retardo);

    campos.forEach(function (clave) {
      var entrada = entradas[clave];
      if (!entrada) return;
      var contenedor = entrada.parentElement;
      var boton = botonDe(clave);
      var lista = listaDe(clave);
      entrada.addEventListener("focus", function () { mostrarLista(clave); });
      entrada.addEventListener("input", function () {
        mostrarLista(clave);
        avisarLuego();
      });
      // Enter dentro de un formulario no debe recargar la página.
      entrada.addEventListener("keydown", function (evento) {
        if (evento.key === "ArrowDown" && lista && !lista.hidden) {
          var primeraOpcion = lista.querySelector(".fu-opcion");
          if (primeraOpcion) {
            evento.preventDefault();
            primeraOpcion.focus();
          }
        } else if (evento.key === "Escape") {
          cerrarLista(clave);
        } else if (evento.key === "Enter" && !o.permitirEnvio) {
          evento.preventDefault();
          avisar();
        }
      });
      if (boton) {
        boton.addEventListener("mousedown", function (evento) { evento.preventDefault(); });
        boton.addEventListener("click", function () {
          if (lista && !lista.hidden) cerrarLista(clave);
          else mostrarLista(clave, "");
        });
      }
      if (lista) {
        lista.addEventListener("keydown", function (evento) {
          var opciones = Array.prototype.slice.call(lista.querySelectorAll(".fu-opcion"));
          var indice = opciones.indexOf(document.activeElement);
          if (evento.key === "ArrowDown" && opciones[indice + 1]) {
            evento.preventDefault();
            opciones[indice + 1].focus();
          } else if (evento.key === "ArrowUp") {
            evento.preventDefault();
            if (opciones[indice - 1]) opciones[indice - 1].focus();
            else entrada.focus();
          } else if (evento.key === "Escape") {
            evento.preventDefault();
            cerrarLista(clave);
            entrada.focus();
          }
        });
      }
      if (contenedor) {
        contenedor.addEventListener("focusout", function () {
          setTimeout(function () {
            if (!contenedor.contains(document.activeElement)) cerrarLista(clave);
          }, 0);
        });
      }
    });
    if (base.addEventListener) {
      base.addEventListener("click", function (evento) {
        campos.forEach(function (clave) {
          var contenedor = entradas[clave] && entradas[clave].parentElement;
          if (contenedor && !contenedor.contains(evento.target)) cerrarLista(clave);
        });
      });
    }

    function limpiar(silencioso) {
      campos.forEach(function (clave) { if (entradas[clave]) entradas[clave].value = ""; });
      if (!silencioso) avisar();
    }
    if (botonLimpiar) {
      botonLimpiar.addEventListener("click", function () {
        limpiar();
        var primero = entradas[campos[0]];
        if (primero) primero.focus();
      });
    }

    return {
      valores: valores,
      hayFiltros: function () { return hayFiltros(valores()); },
      limpiar: limpiar,
      entradas: entradas,
      sugerir: function (clave, lista) {
        if (!entradas[clave]) return;
        sugerencias[clave] = valoresUnicos(lista);
        if (document.activeElement === entradas[clave]) mostrarLista(clave);
      },
      anunciar: function (texto) { if (estado) estado.textContent = texto || ""; }
    };
  }

  // Atributos data-fu-* para filtrar filas ya pintadas: varios valores se separan con "|".
  function atributos(mapa) {
    return Object.keys(mapa || {}).map(function (clave) {
      var lista = [].concat(mapa[clave] == null ? [] : mapa[clave]).filter(function (v) { return v != null && v !== ""; });
      return " data-fu-" + clave + '="' + esc(lista.join("|")) + '"';
    }).join("");
  }

  // Oculta los elementos (filas, tarjetas) que no cumplen; devuelve cuántos quedan visibles.
  function filtrarElementos(elementos, valoresFiltro) {
    var visibles = 0;
    Array.prototype.forEach.call(elementos || [], function (el) {
      var mapa = {};
      Object.keys(valoresFiltro || {}).forEach(function (clave) {
        mapa[clave] = String(el.getAttribute("data-fu-" + clave) || "").split("|");
      });
      var ok = cumple(valoresFiltro, mapa);
      el.hidden = !ok;
      if (ok) visibles += 1;
    });
    return visibles;
  }

  /*
   * Para listas que ya están pintadas completas (sin paginar): liga los campos
   * y oculta las filas con data-fu-* que no cumplen. Opciones extra:
   *   filas      selector de los elementos a filtrar (dentro de `raiz`).
   *   vacio      id del elemento que se muestra cuando no queda ninguno.
   *   singular / plural  para el anuncio ("1 sede" / "3 sedes").
   *   valores    valores iniciales; alCambiar(valores) opcional para recordarlos.
   */
  function ligarFilas(raiz, opciones) {
    var o = opciones || {};
    var campos = o.campos || ["ciudad", "departamento", "pais"];
    var filas = function () { return raiz.querySelectorAll(o.filas); };
    var control;
    function aplicar(valores) {
      var total = filas().length;
      var visibles = filtrarElementos(filas(), valores);
      var vacio = o.vacio ? document.getElementById(o.vacio) : null;
      var mensaje = mensajeVacio(o.plural, valores);
      if (vacio) {
        vacio.hidden = visibles !== 0 || total === 0;
        vacio.textContent = mensaje;
      }
      if (!hayFiltros(valores)) control.anunciar("");
      else control.anunciar(visibles ? visibles + " de " + total + " " + (total === 1 ? o.singular : o.plural) + "." : mensaje);
      if (typeof o.alCambiar === "function") o.alCambiar(valores);
    }
    control = ligar(raiz, { prefijo: o.prefijo, campos: campos, retardo: o.retardo, alCambiar: aplicar, botonLimpiar: o.botonLimpiar });
    campos.forEach(function (clave) {
      control.sugerir(clave, Array.prototype.map.call(filas(), function (el) {
        return String(el.getAttribute("data-fu-" + clave) || "").split("|");
      }));
    });
    if (hayFiltros(control.valores())) aplicar(control.valores());
    control.aplicar = function () { aplicar(control.valores()); };
    return control;
  }

  // Estilos propios (no se tocan los CSS compartidos).
  if (!document.getElementById("filtros-ubicacion-estilos")) {
    var estilo = document.createElement("style");
    estilo.id = "filtros-ubicacion-estilos";
    estilo.textContent =
      ".filtros-ubicacion{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px 12px;align-items:start;margin:0 0 6px}" +
      ".fu-panel{margin:0 0 18px;padding:14px 16px 6px;border:1px solid #e4f1dc;border-radius:8px;background:#f8fafc}" +
      ".fu-panel .fu-estado{margin-bottom:6px}" +
      ".filtros-ubicacion .fu-campo{display:flex;flex-direction:column;gap:4px;min-width:0}" +
      ".filtros-ubicacion .fu-campo:focus-within{position:relative;z-index:20}" +
      ".filtros-ubicacion .fu-campo label{font-weight:600;font-size:.85rem;line-height:1.2;margin:0}" +
      ".filtros-ubicacion .fu-control{position:relative;width:100%;min-width:0}" +
      ".filtros-ubicacion .fu-campo input{width:100%;min-width:0;box-sizing:border-box;padding-right:40px}" +
      ".fu-toggle{position:absolute;top:2px;right:2px;width:34px;height:calc(100% - 4px);padding:0;border:0;border-radius:4px;background:transparent;color:#475569;font-size:16px;cursor:pointer}" +
      ".fu-toggle:hover,.fu-toggle:focus-visible{background:#f1f5f9;color:#256d00;outline:2px solid rgba(59,170,1,.25);outline-offset:-2px}" +
      ".fu-opciones{position:absolute;top:calc(100% + 4px);left:0;right:0;z-index:30;max-height:240px;overflow-y:auto;padding:4px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;box-shadow:0 8px 20px rgba(15,23,42,.16)}" +
      ".fu-opciones[hidden]{display:none}" +
      ".fu-opcion{display:block;width:100%;padding:8px 10px;border:0;border-radius:4px;background:#fff;color:#334155;text-align:left;font:inherit;font-size:.9rem;cursor:pointer}" +
      ".fu-opcion:hover,.fu-opcion:focus-visible{background:#f1f5f9;color:#256d00;outline:none}" +
      ".filtros-ubicacion .fu-ayuda{color:var(--gris-500,#5f6b7a);font-size:.75rem}" +
      ".filtros-ubicacion .fu-acciones{display:flex;flex-direction:column;align-items:flex-start;gap:4px}" +
      ".filtros-ubicacion .fu-espaciador{font-size:.85rem;line-height:1.2}" +
      ".filtros-ubicacion .fu-acciones .btn{min-height:40px}" +
      ".filtros-ubicacion .fu-acciones .btn{white-space:nowrap}" +
      ".fu-estado{margin:4px 0 10px;font-size:.85rem;color:var(--gris-500,#5f6b7a);min-height:1em}" +
      // Región que solo leen los lectores de pantalla (cuando el conteo ya se ve en otro lugar).
      ".fu-solo-lector{position:absolute!important;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}" +
      "@media (max-width:420px){.filtros-ubicacion{grid-template-columns:1fr 1fr}.filtros-ubicacion .fu-acciones{grid-column:1/-1}.filtros-ubicacion .fu-espaciador{display:none}}";
    (document.head || document.documentElement).appendChild(estilo);
  }

  window.FiltrosUbicacion = {
    normalizar: normalizar,
    coincide: coincide,
    cumple: cumple,
    hayFiltros: hayFiltros,
    debounce: debounce,
    valoresUnicos: valoresUnicos,
    mensajeVacio: mensajeVacio,
    atributos: atributos,
    filtrarElementos: filtrarElementos,
    html: html,
    ligar: ligar,
    ligarFilas: ligarFilas
  };
})();
