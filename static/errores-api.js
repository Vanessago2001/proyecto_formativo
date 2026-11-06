/*
 * Mensajes de error legibles a partir de la respuesta JSON de la API.
 *
 * FastAPI devuelve `detail` de tres formas:
 *   - texto:   {"detail": "Credenciales inválidas."}
 *   - objeto:  {"detail": {"accion": "codigo", "mensaje": "..."}}
 *   - lista:   {"detail": [{"loc": ["body", "nombre"], "type": "string_too_short", ...}]}
 *              (errores 422 de validación de Pydantic)
 *
 * Asignar `data.detail` directamente a textContent mostraba "[object Object]"
 * en los dos últimos casos. `mensajeErrorApi(data, respaldo)` devuelve siempre
 * texto en español.
 */
(function () {
    const CAMPOS = {
        nombre: "Nombre",
        correo: "Correo electrónico",
        email: "Correo electrónico",
        contrasena: "Contraseña",
        password: "Contraseña",
        password_actual: "Contraseña actual",
        password_nueva: "Nueva contraseña",
        nueva_password: "Nueva contraseña",
        tipo_doc: "Tipo de documento",
        num_doc: "Número de documento",
        rol: "Rol",
        codigo: "Código",
        nit: "NIT",
        token: "Enlace de restablecimiento",
    };

    function etiqueta(loc) {
        const partes = Array.isArray(loc) ? loc.filter(p => !["body", "query", "path"].includes(p)) : [];
        const campo = partes.length ? String(partes[partes.length - 1]) : "";
        return CAMPOS[campo] || campo;
    }

    function traducir(error) {
        if (!error || typeof error !== "object") return String(error ?? "");
        const campo = etiqueta(error.loc);
        const ctx = error.ctx || {};
        const msg = String(error.msg || "").replace(/^Value error,\s*/i, "");
        let texto;
        switch (error.type) {
            case "missing":
                texto = "es obligatorio.";
                break;
            case "string_too_short":
                texto = `debe tener al menos ${ctx.min_length} caracteres.`;
                break;
            case "string_too_long":
                texto = `debe tener como máximo ${ctx.max_length} caracteres.`;
                break;
            case "string_pattern_mismatch":
                texto = "tiene un formato no válido.";
                break;
            case "string_type":
                texto = "debe ser texto.";
                break;
            default:
                if (/email/i.test(msg) || /email/i.test(error.type || "")) {
                    texto = "no es un correo electrónico válido.";
                } else {
                    texto = msg || "valor no válido.";
                }
        }
        return campo ? `${campo}: ${texto}` : texto.charAt(0).toUpperCase() + texto.slice(1);
    }

    /*
     * Valida el NIT antes de consultar. Mismo criterio que el servidor
     * (modules/consultas_p/consultas_service.normalizar_nit): se ignoran
     * puntos y espacios; quedan 6 a 12 dígitos y, opcional, "-DV".
     * Devuelve el mensaje de error o null si el NIT es válido.
     */
    window.validarNit = function (nit) {
        const limpio = String(nit || "").replace(/[‐-—−]/g, "-").replace(/[\s.,]/g, "");
        if (!limpio) return "Ingrese el NIT de la empresa.";
        if (/^\d{6,12}(-\d)?$/.test(limpio)) return null;
        return "NIT no válido. Escriba el NIT completo, solo con números (6 a 12 dígitos) " +
            "y, si quiere, el dígito de verificación separado por guion. Ejemplo: 900123456-7.";
    };

    window.mensajeErrorApi = function (data, respaldo) {
        const detalle = data && typeof data === "object" && "detail" in data ? data.detail : data;
        if (typeof detalle === "string" && detalle.trim()) return detalle;
        if (Array.isArray(detalle)) {
            const mensajes = [...new Set(detalle.map(traducir).filter(Boolean))];
            if (mensajes.length) return mensajes.join(" ");
        }
        if (detalle && typeof detalle === "object") {
            const texto = detalle.mensaje || detalle.message || detalle.msg;
            if (typeof texto === "string" && texto.trim()) return texto;
        }
        return respaldo || "No se pudo completar la solicitud.";
    };
})();
