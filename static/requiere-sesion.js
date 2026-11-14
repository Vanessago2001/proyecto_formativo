/* Guardia de las páginas internas (retest 13/11).
 *
 * Las páginas internas se sirven con este script al inicio del <head>
 * (main.py, pagina_interna). Sin sesión en este navegador, la página no se
 * muestra: se va directo a /login. Los datos ya los protege el backend
 * (responden 401); esto evita además ver la interfaz vacía.
 */
(function () {
  "use strict";
  var token = null;
  try { token = localStorage.getItem("access_token"); } catch (_) { token = null; }
  if (token) return;
  try { document.documentElement.style.visibility = "hidden"; } catch (_) {}
  window.location.replace("/login");
})();
