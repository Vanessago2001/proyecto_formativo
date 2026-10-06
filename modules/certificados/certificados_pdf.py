from core.pdf import construir_pdf


def generar_pdf_certificado(certificado: dict, modo: str = "consulta") -> bytes:
    pendiente_firma = str(certificado.get("estado_certificado", "")).upper() == "PENDIENTE_FIRMA"
    if modo == "firma" and pendiente_firma:
        raise ValueError("El PDF destinado a firma debe tener los datos de emisión preparados.")
    if pendiente_firma:
        titulo = "BORRADOR DE CERTIFICADO - PENDIENTE DE FIRMA"
        pie = "Borrador sin firma digital. No constituye un certificado oficial."
    elif modo == "firma":
        titulo = "CERTIFICADO DE CONFORMIDAD"
        pie = "Documento firmado digitalmente por el líder asignado del Comité."
    else:
        titulo = "COPIA DE CONSULTA - FIRMA DIGITAL NO VALIDADA"
        pie = "Copia generada por CertiSENA. La firma digital no ha sido validada por esta aplicación."
    campos = [
        ("Código de verificación", certificado.get("codigo_verificacion")),
        ("Radicado", certificado.get("numero_radicado")),
        ("Empresa titular", certificado.get("empresa")),
        ("NIT", certificado.get("nit")),
        ("Norma", " ".join(filter(None, (
            certificado.get("norma_codigo"),
            certificado.get("norma"),
            certificado.get("norma_version"),
        )))),
        ("Alcance técnico", certificado.get("alcance")),
        ("Fecha de emisión", certificado.get("fecha_emision")),
        ("Fecha de vencimiento", certificado.get("fecha_vencimiento")),
        ("Estado", certificado.get("estado_certificado")),
    ]
    if modo == "firma":
        campos.append(("Firmado por", certificado.get("nombre_firmante")))
    return construir_pdf(
        titulo=titulo,
        subtitulo=str(certificado.get("empresa") or "CertiSENA"),
        campos=campos,
        pie=pie,
    )