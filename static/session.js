// ======================================================
// Cierre automático de sesión por inactividad
// 30 minutos
// ======================================================

const TIEMPO_INACTIVIDAD = 30 * 60 * 1000;
// const TIEMPO_INACTIVIDAD = 15000;
let temporizadorInactividad = null;

// ===========================================
// Cerrar sesión
// ===========================================

function cerrarSesionPorInactividad() {

    localStorage.removeItem("access_token");
    localStorage.removeItem("token_type");

    alert(
        "La sesión se cerró automáticamente por 30 minutos de inactividad."
    );

    window.location.href = "/login";

}

// ===========================================
// Reiniciar temporizador
// ===========================================

function reiniciarTemporizador() {

    clearTimeout(temporizadorInactividad);

    temporizadorInactividad = setTimeout(

        cerrarSesionPorInactividad,

        TIEMPO_INACTIVIDAD

    );

}

// ===========================================
// Eventos que indican actividad
// ===========================================

[
    "mousemove",
    "mousedown",
    "click",
    "keydown",
    "scroll",
    "touchstart"
].forEach(evento => {

    document.addEventListener(

        evento,

        reiniciarTemporizador,

        true

    );

});

// ===========================================
// Iniciar temporizador al cargar la página
// ===========================================

reiniciarTemporizador();