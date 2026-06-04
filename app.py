import os
import secrets
import traceback

from flask import Flask, request, jsonify, send_file, send_from_directory
from sqlalchemy import text

from db import db
from models import User, Ticket, Attachment, Invoice
import auth
from auth import login_required, agent_required

BASE_DIR = os.path.dirname(__file__)
UPLOADS = os.path.join(BASE_DIR, "uploads")
STATIC = os.path.join(BASE_DIR, "static")
DB_PATH = os.path.join(BASE_DIR, "support.db")

B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def rnd_ref(prefix):
    return prefix + "_" + "".join(secrets.choice(B32) for _ in range(8))

def create_app():
    app = Flask(__name__, static_folder=None)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
    db.init_app(app)

    # =====================================================================
    #  FRONTEND ESTÁTICO
    # =====================================================================
    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/backoffice")
    def backoffice():
        return send_from_directory(STATIC, "backoffice.html")

    @app.get("/static/<path:fname>")
    def static_files(fname):
        return send_from_directory(STATIC, fname)

    # =====================================================================
    #  AUTENTICACIÓN  (passwordless OTP)
    # =====================================================================
    @app.get("/api/auth/captcha")
    def get_captcha():
        return jsonify(auth.new_captcha())

    @app.post("/api/auth/otp/send")
    def otp_send():
        """Si existe el mail, envia el OTP al usuario. Si no existe, responde 404."""
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        if not auth.check_captcha(data.get("captcha_id"), data.get("captcha")):
            return jsonify({"error": "captcha inválido"}), 400

        user = User.query.filter_by(email=email).first()
        if not user:
            return jsonify({"error": "usuario no encontrado"}), 404

        auth.generate_and_send_otp(email)
        return jsonify({"message": "OTP enviado"}), 200

    @app.post("/api/auth/otp/verify")
    def otp_verify():
        """
        Etapa 2: validación del OTP.

        VULN A06/A07 (insecure design): SIN rate limiting, SIN bloqueo por
        intentos fallidos y SIN invalidación del OTP. Con 4 dígitos (10.000
        combinaciones) y TTL de 15 min, el espacio es barrible por fuerza bruta.
        """
        data = request.get_json(silent=True) or {}
        email = (data.get("email") or "").strip().lower()
        code = (data.get("otp") or "").strip()

        if auth.verify_otp(email, code):
            user = User.query.filter_by(email=email).first()
            token = auth.issue_session(user)
            return jsonify({"session_token": token, "user": user.to_dict()})
        return jsonify({"error": "OTP inválido"}), 401

    @app.get("/api/me")
    @login_required
    def me():
        return jsonify({"user": request.user.to_dict()})

    # =====================================================================
    #  TICKETS
    # =====================================================================
    @app.get("/api/tickets")
    @login_required
    def list_tickets():
        """
        Listado de tickets del tenant del usuario, con orden configurable.

        VULN A10 (manejo de excepciones): el parámetro `sort` se interpola
        directamente en ORDER BY. Si está mal formado (ej. sort=id'), la
        excepción de base de datos NO se maneja correctamente y se devuelve
        el stack trace + la query al cliente, filtrando estructura interna.
        """
        sort = request.args.get("sort", "created_at")
        tenant_id = request.user.tenant_id
        # tenant_id va parametrizado (no es el vector); el vector es `sort`.
        raw_sql = (
            "SELECT id, public_ref, tenant_slug FROM tickets "
            f"WHERE tenant_id = {tenant_id} ORDER BY {sort} ASC LIMIT 50"
        )
        try:
            rows = db.session.execute(text(raw_sql)).fetchall()
        except Exception as exc:
            # A10: respuesta de error verbosa
            return jsonify({
                "error": str(getattr(exc, "orig", exc)),
                "query": raw_sql,
                "stack": traceback.format_exc(),
            }), 500

        refs = [r[1] for r in rows]
        tickets = Ticket.query.filter(Ticket.public_ref.in_(refs)).all() if refs else []
        order = {ref: i for i, ref in enumerate(refs)}
        tickets.sort(key=lambda t: order.get(t.public_ref, 0))
        return jsonify({"tickets": [t.to_dict() for t in tickets]})

    @app.get("/api/tickets/search")
    @login_required
    def search_tickets():
        """
        Búsqueda de tickets por texto en el asunto.

        VULN A05 (SQL Injection UNION-based): el parámetro `q` se concatena sin
        sanitizar dentro de un LIKE. Permite, por ejemplo:
          q = urgente' UNION SELECT public_ref, tenant_slug FROM invoices--
        devolviendo identificadores de recursos de OTROS tenants.
        """
        q = request.args.get("q", "")
        tenant_id = request.user.tenant_id
        raw_sql = (
            "SELECT public_ref, subject FROM tickets "
            f"WHERE tenant_id = {tenant_id} AND subject LIKE '%{q}%' LIMIT 50"
        )
        try:
            rows = db.session.execute(text(raw_sql)).fetchall()
        except Exception as exc:
            return jsonify({
                "error": str(getattr(exc, "orig", exc)),
                "query": raw_sql,
                "stack": traceback.format_exc(),
            }), 500
        return jsonify({"results": [{"id": r[0], "title": r[1]} for r in rows]})

    @app.post("/api/tickets")
    @login_required
    def create_ticket():
        data = request.get_json(silent=True) or {}
        subject = (data.get("subject") or "").strip()
        if not subject:
            return jsonify({"error": "subject requerido"}), 400
        u = request.user
        tk = Ticket(
            tenant_id=u.tenant_id,
            tenant_slug=u.tenant.slug,
            public_ref=rnd_ref("tkt"),
            subject=subject,
            body=(data.get("body") or "").strip(),
            priority=(data.get("priority") or "normal"),
            status="open",
            created_by=u.email,
        )
        db.session.add(tk)
        db.session.commit()
        return jsonify({"ticket": tk.to_dict()}), 201

    @app.get("/api/tickets/<ref>")
    @login_required
    def get_ticket(ref):
        # Endpoint CORRECTO: scopeado al tenant del usuario (contraste con el IDOR).
        tk = Ticket.query.filter_by(public_ref=ref, tenant_id=request.user.tenant_id).first()
        if not tk:
            return jsonify({"error": "ticket no encontrado"}), 404
        return jsonify({"ticket": tk.to_dict(include_attachments=True)})

    @app.post("/api/tickets/<ref>/attachments")
    @login_required
    def upload_attachment(ref):
        tk = Ticket.query.filter_by(public_ref=ref, tenant_id=request.user.tenant_id).first()
        if not tk:
            return jsonify({"error": "ticket no encontrado"}), 404
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "archivo requerido"}), 400
        att_ref = rnd_ref("att")
        safe = att_ref + "_" + os.path.basename(f.filename)
        path = os.path.join(UPLOADS, safe)
        f.save(path)
        att = Attachment(
            ticket_id=tk.id, tenant_id=tk.tenant_id, public_ref=att_ref,
            filename=f.filename, stored_path=path,
            content_type=f.mimetype or "application/octet-stream",
            size=os.path.getsize(path),
        )
        db.session.add(att)
        db.session.commit()
        return jsonify({"attachment": att.to_dict()}), 201

    @app.get("/api/attachments/<ref>/file")
    @login_required
    def download_attachment(ref):
        # Correcto: valida pertenencia al tenant.
        att = Attachment.query.filter_by(public_ref=ref, tenant_id=request.user.tenant_id).first()
        if not att:
            return jsonify({"error": "adjunto no encontrado"}), 404
        return send_file(att.stored_path, download_name=att.filename, as_attachment=True)

    @app.post("/api/tickets/<ref>/resolve")
    @agent_required
    def resolve_ticket(ref):
        # Resolver tickets: capacidad del backoffice (rol agente), dentro del tenant.
        tk = Ticket.query.filter_by(public_ref=ref, tenant_id=request.user.tenant_id).first()
        if not tk:
            return jsonify({"error": "ticket no encontrado"}), 404
        data = request.get_json(silent=True) or {}
        tk.status = "resolved"
        tk.resolution = (data.get("resolution") or "Resuelto por el agente.").strip()
        from models import utcnow
        tk.resolved_at = utcnow()
        db.session.commit()
        return jsonify({"ticket": tk.to_dict()})

    # =====================================================================
    #  FACTURAS
    # =====================================================================
    @app.get("/api/invoices")
    @login_required
    def list_invoices():
        # Listado correcto: solo facturas del propio tenant.
        invs = Invoice.query.filter_by(tenant_id=request.user.tenant_id).all()
        return jsonify({"invoices": [i.to_dict() for i in invs]})

    @app.get("/api/invoices/<ref>")
    @login_required
    def get_invoice(ref):
        """
        VULN A01 (Broken Access Control / IDOR): valida autenticación pero NO
        verifica que la factura pertenezca al tenant del usuario. Cualquier
        sesión válida puede leer una factura de otro tenant conociendo su ref.
        """
        inv = Invoice.query.filter_by(public_ref=ref).first()   # <-- sin filtro de tenant
        if not inv:
            return jsonify({"error": "factura no encontrada"}), 404
        return jsonify({"invoice": inv.to_dict()})

    @app.get("/api/invoices/<ref>/file")
    @login_required
    def download_invoice(ref):
        """
        VULN A01 (IDOR): descarga del documento confidencial sin chequeo de tenant.
        Este es el objetivo final del atacante: el archivo de otro tenant.
        """
        inv = Invoice.query.filter_by(public_ref=ref).first()   # <-- sin filtro de tenant
        if not inv or not inv.document_path:
            return jsonify({"error": "documento no encontrado"}), 404
        return send_file(inv.document_path,
                         download_name=f"{inv.number}.pdf", as_attachment=True)

    return app


def init_db(app):
    fresh = not os.path.exists(DB_PATH)
    with app.app_context():
        # CREO LAS TABLAS SI NO EXISTEN        
        db.create_all()
        if fresh:
            import seed
            seed.seed()
    return fresh

if __name__ == "__main__":
    app = create_app()
    init_db(app)
    print("\n  Portal cliente : http://127.0.0.1:5000/")
    print("  Backoffice     : http://127.0.0.1:5000/backoffice")
    print("  (los OTP se imprimen en esta consola y en ./mailbox/)\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
