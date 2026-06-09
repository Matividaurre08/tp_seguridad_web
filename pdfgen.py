import random
from datetime import datetime
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_RIGHT, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import ParagraphStyle

ITBIS_RATE = 0.18
AZUL = colors.HexColor('#1F4E79')
GRIS = colors.HexColor('#7F8C8D')
GRIS_CLARO = colors.HexColor('#F2F4F7')

_PRODUCTOS = [
    ("Licencia de software anual", "UND"),
    ("Servicio de soporte premium", "MES"),
    ("Horas de consultoría técnica", "HRA"),
    ("Implementación de módulo", "UND"),
    ("Capacitación de usuarios", "HRA"),
    ("Mantenimiento preventivo", "MES"),
    ("Integración API", "UND"),
    ("Almacenamiento adicional", "GB"),
]

_CLIENTES = [
    ("Distribuidora del Sur, SRL", "131-22456-7"),
    ("Comercial Andina, SA", "130-99812-3"),
    ("Servicios Globales, EIRL", "132-44781-5"),
    ("Importadora Delta, SRL", "131-77520-9"),
]

_VENDEDORES = ["Ana Gómez", "Luis Pérez", "Marta Reyes", "Jorge Castillo"]


def _empresa(slug):
    return {
        "acme":    ("Acme Inc., SRL",            "RNC 101-00001-1", "Av. Central #45, Piantini"),
        "globex":  ("Globex Corporation, SA",    "RNC 102-55872-4", "Calle Comercio #12, Naco"),
        "initech": ("Initech LLC, SRL",          "RNC 103-31947-8", "Av. Industrial #8, Herrera"),
    }.get(slug, (f"{slug.title()}, SRL", "RNC 100-00000-0", "Dirección no especificada"))


def _fechas(period):
    try:
        y, m = period.split("-")
        emision = datetime(int(y), int(m), 1)
    except Exception:
        emision = datetime.today()
    venc_mes = emision.month % 12 + 1
    venc_anio = emision.year + (1 if emision.month == 12 else 0)
    vencimiento = datetime(venc_anio, venc_mes, 1)
    return emision.strftime("%d-%m-%Y"), vencimiento.strftime("%d-%m-%Y")


def _line_items(invoice):
    """Genera ítems determinísticos que suman exactamente invoice.amount (con ITBIS)."""
    rng = random.Random(invoice.public_ref)
    subtotal = round(invoice.amount / (1 + ITBIS_RATE), 2)
    n = rng.randint(3, 5)
    productos = rng.sample(_PRODUCTOS, n)
    pesos = [rng.uniform(1, 6) for _ in range(n)]
    total_peso = sum(pesos)
    valores = [round(subtotal * p / total_peso, 2) for p in pesos]

    items = []
    acumulado = 0.0
    for i, ((desc, unidad), valor) in enumerate(zip(productos, valores)):
        if i == n - 1:                      # el último absorbe el resto -> suma exacta
            valor = round(subtotal - acumulado, 2)
            cantidad = 1
            precio = valor
        else:
            cantidad = rng.randint(2, 60)
            precio = round(valor / cantidad, 2)
            valor = round(precio * cantidad, 2)
        acumulado = round(acumulado + valor, 2)
        itbis = round(valor * ITBIS_RATE, 2)
        items.append((cantidad, desc, unidad, precio, itbis, valor))
    return items, acumulado


def _money(x):
    return f"{x:,.2f}"


def make_pdf(invoice) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=2*cm, leftMargin=2*cm,
                            topMargin=1.5*cm, bottomMargin=2*cm)
    story = []

    emp_nombre, emp_rnc, emp_dir = _empresa(invoice.tenant_slug)
    emision, vencimiento = _fechas(invoice.period)
    rng = random.Random(invoice.public_ref + "_meta")
    cliente_nombre, cliente_rnc = rng.choice(_CLIENTES)
    vendedor = rng.choice(_VENDEDORES)
    num_digits = "".join(filter(str.isdigit, invoice.number)) or "0"
    encf = f"E31{num_digits.zfill(10)}"
    cod_seguridad = "".join(rng.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
    estado_map = {"issued": "EMITIDA", "overdue": "VENCIDA", "paid": "PAGADA", "pending": "PENDIENTE"}
    estado = estado_map.get(invoice.status, invoice.status.upper())

    # ---- Estilos ----
    st_emp = ParagraphStyle('emp', fontName='Helvetica-Bold', fontSize=16, textColor=AZUL, leading=18)
    st_emp_info = ParagraphStyle('empinfo', fontName='Helvetica', fontSize=8.5, textColor=colors.black, leading=11)
    st_doc = ParagraphStyle('doc', fontName='Helvetica-Bold', fontSize=13, textColor=AZUL, alignment=TA_RIGHT, leading=16)
    st_doc_info = ParagraphStyle('docinfo', fontName='Helvetica', fontSize=9, alignment=TA_RIGHT, leading=13)
    st_label = ParagraphStyle('label', fontName='Helvetica', fontSize=9, leading=13)

    # ---- Encabezado: emisor (izq) / comprobante (der) ----
    emisor = Paragraph(
        f"{emp_nombre}<br/>"
        f"<font size=8.5 color='#000000'>{emp_dir}<br/>{emp_rnc}</font>",
        st_emp)
    comprobante = Paragraph(
        "Factura de Crédito Fiscal Electrónica<br/>"
        f"<font size=9 color='#000000'>e-NCF: {encf}<br/>"
        f"Fecha Emisión: {emision}<br/>"
        f"Fecha Vencimiento: {vencimiento}</font>",
        st_doc)
    header = Table([[emisor, comprobante]], colWidths=[9*cm, 8*cm])
    header.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(header)
    story.append(Spacer(1, 0.3*cm))
    story.append(Table([['']], colWidths=[17*cm],
                       style=[('LINEABOVE', (0,0), (-1,-1), 1.2, AZUL)]))
    story.append(Spacer(1, 0.4*cm))

    # ---- Datos del cliente / carga ----
    cli = Paragraph(
        f"<b>Razón Social Cliente:</b> {cliente_nombre}<br/>"
        f"<b>RNC Cliente:</b> {cliente_rnc}", st_label)
    meta = Paragraph(
        f"<b>Comprobante N°:</b> {invoice.number}<br/>"
        f"<b>Cargado por:</b> {vendedor}<br/>"
        f"<b>Estado:</b> {estado}", st_label)
    cli_table = Table([[cli, meta]], colWidths=[9*cm, 8*cm])
    cli_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(cli_table)
    story.append(Spacer(1, 0.5*cm))

    # ---- Tabla de ítems ----
    items, subtotal = _line_items(invoice)
    encabezados = ["Cantidad", "Descripción", "Unidad", "Precio", "ITBIS", "Valor"]
    data = [encabezados]
    for cant, desc, unidad, precio, itbis, valor in items:
        data.append([str(cant), desc, unidad, _money(precio), _money(itbis), _money(valor)])

    tabla = Table(data, colWidths=[1.8*cm, 6.2*cm, 1.8*cm, 2.4*cm, 2.4*cm, 2.4*cm])
    tabla.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), AZUL),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8.5),
        ('ALIGN', (0,0), (0,-1), 'CENTER'),
        ('ALIGN', (2,0), (2,-1), 'CENTER'),
        ('ALIGN', (3,0), (-1,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, GRIS_CLARO]),
        ('LINEBELOW', (0,0), (-1,0), 0.5, AZUL),
        ('GRID', (0,1), (-1,-1), 0.25, colors.HexColor('#D5DBDB')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(tabla)
    story.append(Spacer(1, 0.4*cm))

    # ---- Totales (alineados a la derecha) ----
    itbis_total = round(invoice.amount - subtotal, 2)
    tot_data = [
        ["Subtotal Gravado:", _money(subtotal)],
        ["Total ITBIS:", _money(itbis_total)],
        ["Total:", f"{_money(invoice.amount)} {invoice.currency}"],
    ]
    totales = Table(tot_data, colWidths=[4*cm, 4*cm], hAlign='RIGHT')
    totales.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9.5),
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('TEXTCOLOR', (0,0), (-1,1), colors.black),
        ('BACKGROUND', (0,2), (-1,2), AZUL),
        ('TEXTCOLOR', (0,2), (-1,2), colors.white),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(totales)
    story.append(Spacer(1, 1*cm))

    # ---- Pie: firma digital / confidencial ----
    st_foot = ParagraphStyle('foot', fontName='Helvetica', fontSize=8, textColor=GRIS, leading=11)
    story.append(Table([['']], colWidths=[17*cm],
                       style=[('LINEABOVE', (0,0), (-1,-1), 0.5, GRIS)]))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        f"Código de Seguridad: {cod_seguridad} &nbsp;·&nbsp; Fecha de Firma Digital: {emision}<br/>"
        f"Ref: {invoice.public_ref} &nbsp;·&nbsp; Documento de uso interno · No distribuir",
        st_foot))

    doc.build(story)
    return buffer.getvalue()