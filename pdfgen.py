"""
Generador minimalista de PDF (sin dependencias externas).
Produce un PDF de una página con líneas de texto. Suficiente para que las
facturas/documentos "confidenciales" sembrados sean archivos .pdf reales.
"""


def _escape(s: str) -> str:
    return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_pdf(lines, title="Documento") -> bytes:
    # Construye el content stream con una línea por renglón.
    y = 770
    parts = ["BT", "/F1 11 Tf", "12 TL", f"50 {y} Td"]
    parts.append(f"/F1 16 Tf ({_escape(title)}) Tj")
    parts.append("0 -28 Td /F1 11 Tf")
    for ln in lines:
        parts.append(f"({_escape(ln)}) Tj 0 -16 Td")
    parts.append("ET")
    content = "\n".join(parts).encode("latin-1", "replace")

    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    objects.append(b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_pos = len(out)
    n = len(objects) + 1
    out += f"xref\n0 {n}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode()
    return bytes(out)
