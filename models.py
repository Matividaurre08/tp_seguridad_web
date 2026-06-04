"""
Modelo de datos de la plataforma SaaS de soporte multi-tenant.

Entidades:
  - Tenant      : empresa cliente de la plataforma (acme, globex, initech...)
  - User        : usuario perteneciente a un tenant (rol customer | agent)
  - Ticket      : ticket de soporte, scopeado a un tenant
  - Attachment  : archivo adjunto a un ticket
  - Invoice     : factura emitida por la plataforma a un tenant, con documento
  - OtpCode     : código OTP temporal para el login passwordless
  - Session     : token de sesión emitido tras validar el OTP
"""
import datetime as dt
from db import db


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


class Tenant(db.Model):
    __tablename__ = "tenants"
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(64), unique=True, nullable=False)   # ej: "globex"
    name = db.Column(db.String(128), nullable=False)               # ej: "Globex Corporation"
    created_at = db.Column(db.DateTime, default=utcnow)

    users = db.relationship("User", backref="tenant", lazy=True)
    tickets = db.relationship("Ticket", backref="tenant", lazy=True)
    invoices = db.relationship("Invoice", backref="tenant", lazy=True)


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    email = db.Column(db.String(190), unique=True, nullable=False)
    name = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(16), nullable=False, default="customer")  # customer | agent
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "tenant": self.tenant.slug,
            "tenant_name": self.tenant.name,
        }


class Ticket(db.Model):
    __tablename__ = "tickets"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    tenant_slug = db.Column(db.String(64), nullable=False)         # desnormalizado (aparece en el UNION)
    public_ref = db.Column(db.String(64), unique=True, nullable=False)  # tkt_<slug>_<rnd>
    subject = db.Column(db.String(255), nullable=False)
    body = db.Column(db.Text, default="")
    status = db.Column(db.String(16), default="open")             # open | pending | resolved
    priority = db.Column(db.String(16), default="normal")
    created_by = db.Column(db.String(190))
    created_at = db.Column(db.DateTime, default=utcnow)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolution = db.Column(db.Text, default="")

    attachments = db.relationship("Attachment", backref="ticket", lazy=True)

    def to_dict(self, include_attachments=False):
        d = {
            "id": self.public_ref,
            "subject": self.subject,
            "body": self.body,
            "status": self.status,
            "priority": self.priority,
            "tenant": self.tenant_slug,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution": self.resolution,
        }
        if include_attachments:
            d["attachments"] = [a.to_dict() for a in self.attachments]
        return d


class Attachment(db.Model):
    __tablename__ = "attachments"
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False)
    tenant_id = db.Column(db.Integer, nullable=False)
    public_ref = db.Column(db.String(64), unique=True, nullable=False)  # att_<rnd>
    filename = db.Column(db.String(255), nullable=False)
    stored_path = db.Column(db.String(512), nullable=False)
    content_type = db.Column(db.String(128), default="application/octet-stream")
    size = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.public_ref,
            "filename": self.filename,
            "content_type": self.content_type,
            "size": self.size,
        }


class Invoice(db.Model):
    __tablename__ = "invoices"
    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)
    tenant_slug = db.Column(db.String(64), nullable=False)        # aparece en el UNION SELECT
    public_ref = db.Column(db.String(64), unique=True, nullable=False)  # inv_<slug>_<rnd>
    number = db.Column(db.String(32), nullable=False)
    period = db.Column(db.String(16))
    amount = db.Column(db.Float, default=0.0)
    currency = db.Column(db.String(8), default="USD")
    status = db.Column(db.String(16), default="issued")          # issued | paid | overdue
    document_path = db.Column(db.String(512))                    # PDF "confidencial"
    created_at = db.Column(db.DateTime, default=utcnow)

    def to_dict(self):
        return {
            "id": self.public_ref,
            "tenant": self.tenant_slug,
            "number": self.number,
            "period": self.period,
            "amount": self.amount,
            "currency": self.currency,
            "status": self.status,
            "document": f"/api/invoices/{self.public_ref}/file" if self.document_path else None,
        }


class OtpCode(db.Model):
    __tablename__ = "otp_codes"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(190), nullable=False, index=True)
    code = db.Column(db.String(8), nullable=False)               # 4 dígitos
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utcnow)


class Captcha(db.Model):
    __tablename__ = "captchas"
    id = db.Column(db.String(40), primary_key=True)
    answer = db.Column(db.String(16), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    consumed = db.Column(db.Boolean, default=False)


class Session(db.Model):
    __tablename__ = "sessions"
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(120), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)

    user = db.relationship("User")
