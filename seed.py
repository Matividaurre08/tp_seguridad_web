"""
Carga de datos de demostración.

Tenants: acme, globex, initech
El atacante compromete una cuenta de ACME (alice@acme.local, agente) y a través
de la cadena de vulnerabilidades termina accediendo a documentos de globex/initech.
"""
import os
import random

from db import db
from models import Tenant, User, Ticket, Invoice
from pdfgen import make_pdf

UPLOADS = os.path.join(os.path.dirname(__file__), "uploads")
B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"

def _rnd(n=6):
    return "".join(random.choice(B32) for _ in range(n))


def ref(prefix, slug):
    return f"{prefix}_{slug}_{_rnd()}"

def seed():
    os.makedirs(UPLOADS, exist_ok=True)

    ATTACK_USER_EMAIL = os.getenv("ATTACK_USER_EMAIL","matiasvidaurre2a@gmail.com")
    ATTACK_USER_NAME = os.getenv("ATTACK_USER_NAME", "Matias Vidaurre")

    TENANTS = [ ("acme", "Acme Inc."),
                ("globex", "Globex Corporation"),
                ("initech", "Initech LLC"),
            ]
    
    tenants = {}
    for slug, name in TENANTS:
        t = Tenant(slug=slug, name=name)
        db.session.add(t)
        tenants[slug] = t
    db.session.commit()

    users_data = [
        (ATTACK_USER_EMAIL, ATTACK_USER_NAME, "acme", "agent"),
        ("bob@acme.local", "Bob Núñez", "acme", "customer"),
        ("carol@globex.local", "Carol Díaz", "globex", "customer"),
        ("dave@globex.local", "Dave Romero", "globex", "agent"),
        ("erin@initech.local", "Erin Vega", "initech", "customer"),
        ("frank@initech.local", "Frank Soto", "initech", "agent"),
    ]
    for email, name, slug, role in users_data:
        db.session.add(User(email=email, name=name, tenant_id=tenants[slug].id, role=role))
    db.session.commit()

    # ---- Tickets por tenant ----
    tickets_seed = {
        "acme": [
            ("No puedo exportar el reporte mensual", "El botón de exportar tira error 500.", "high"),
            ("Solicitud urgente de acceso", "Necesito acceso al panel de facturación.", "high"),
            ("Consulta sobre integración API", "¿Cómo roto las API keys?", "normal"),
        ],
        "globex": [
            ("urgente: caída del servicio", "El portal no carga desde esta mañana.", "high"),
            ("Cambio de datos fiscales", "Actualizar CUIT en las próximas facturas.", "normal"),
        ],
        "initech": [
            ("Error al adjuntar archivos", "Los PDF mayores a 2MB fallan.", "normal"),
            ("urgente revisión de contrato", "Revisar cláusula de renovación.", "high"),
        ],
    }
    for slug, items in tickets_seed.items():
        t = tenants[slug]
        for subject, body, prio in items:
            tk = Ticket(
                tenant_id=t.id,
                tenant_slug=slug,
                public_ref=ref("tkt", slug),
                subject=subject,
                body=body,
                priority=prio,
                status=random.choice(["open", "pending", "open"]),
                created_by=f"user@{slug}.local",
            )
            db.session.add(tk)
    db.session.commit()

    # ---- Una factura "confidencial" por tenant (documento PDF real) ----
    invoices_seed = {
        "acme":    ("0001", "2026-03", 1840.00, "issued"),
        "globex":  ("0007", "2026-03", 92250.50, "overdue"),
        "initech": ("0003", "2026-03", 15300.00, "paid"),
    }
    for slug, (num, period, amount, status) in invoices_seed.items():
        t = tenants[slug]
        public_ref = ref("inv", slug)
        pdf_lines = [
            f"FACTURA CONFIDENCIAL  -  {t.name}",
            "",
            f"Tenant slug      : {slug}",
            f"Numero           : INV-{num}",
            f"Periodo          : {period}",
            f"Importe          : USD {amount:,.2f}",
            f"Estado           : {status}",
            "",
            "ESTADO CONTABLE (extracto)",
            f"  Ingresos netos        : USD {amount*9:,.2f}",
            f"  Saldo de cuenta       : USD {amount*1.7:,.2f}",
            f"  CBU/Cuenta            : 0170{random.randint(10**9,10**10-1)}",
            "",
            "Documento de uso interno. No distribuir.",
        ]
        pdf_bytes = make_pdf(pdf_lines, title=f"Factura INV-{num} - {t.name}")
        doc_name = f"{public_ref}.pdf"
        doc_path = os.path.join(UPLOADS, doc_name)
        with open(doc_path, "wb") as fh:
            fh.write(pdf_bytes)

        db.session.add(Invoice(
            tenant_id=t.id, tenant_slug=slug, public_ref=public_ref,
            number=f"INV-{num}", period=period, amount=amount, status=status,
            currency="USD", document_path=doc_path,
        ))
    db.session.commit()

    print("Seed completo:")
    for slug in tenants:
        invs = Invoice.query.filter_by(tenant_slug=slug).all()
        print(f"  tenant {slug:8s} -> facturas: " + ", ".join(i.public_ref for i in invs))
