"""
Helpers de autenticación.

Diseño del producto (passwordless):
  Etapa 1  POST /api/auth/otp/send    -> protegido con CAPTCHA, genera OTP de 4 dígitos
  Etapa 2  POST /api/auth/otp/verify  -> valida OTP y emite session_token

Nota de seguridad (intencional para el TP): el control fuerte (CAPTCHA) está
únicamente en el endpoint de envío. La verificación NO tiene rate limiting ni
bloqueo, y el OTP es numérico de 4 dígitos con TTL de 15 minutos.
"""
import datetime as dt
import functools
import os
import random
import secrets
import smtplib
import ssl
import string
from email.message import EmailMessage

from flask import request, jsonify

from db import db
from models import OtpCode, Captcha, Session, User, utcnow

OTP_TTL_MINUTES = 30
OTP_DIGITS = 4
CAPTCHA_TTL_MINUTES = 5

# CONFIGURACION SMTP
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "no-reply@supportdesk.local")
SMTP_MODE = os.environ.get("SMTP_MODE", "starttls").lower()  # starttls | ssl | plain
SMTP_TIMEOUT = int(os.environ.get("SMTP_TIMEOUT", "15"))

def new_captcha():
    a, b = random.randint(1, 9), random.randint(1, 9)
    cid = secrets.token_hex(8)
    c = Captcha(
        id=cid,
        answer=str(a + b),
        expires_at=utcnow() + dt.timedelta(minutes=CAPTCHA_TTL_MINUTES),
    )
    db.session.add(c)
    db.session.commit()
    return {"captcha_id": cid, "question": f"{a} + {b} = ?"}

def check_captcha(captcha_id, answer):
    if not captcha_id or answer is None:
        return False
    c = db.session.get(Captcha, captcha_id)
    if not c or c.consumed:
        return False
    expires = c.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=dt.timezone.utc)
    if expires < utcnow():
        return False
    ok = str(answer).strip() == c.answer
    c.consumed = True       # single-use, como un captcha real
    db.session.commit()
    return ok

def generate_and_send_otp(email):
    '''Genera un OTP, lo guarda en la base de datos y lo envia por mail'''
    code = "".join(random.choice(string.digits) for _ in range(OTP_DIGITS))
    otp = OtpCode(
        email=email,
        code=code,
        expires_at=utcnow() + dt.timedelta(minutes=OTP_TTL_MINUTES),
    )
    db.session.add(otp)
    db.session.commit()
    _deliver_email(email, code)
    return code


def _deliver_email(email, code):
    '''Envia el OTP por email'''
    
    # GENERO EL MAIL
    with open("./static/email.html", "r", encoding="utf-8") as f:
        email_template = f.read()
    body = email_template.replace("{{CODE}}", code).replace("{{TTL}}", str(OTP_TTL_MINUTES))
    
    # ENVIO POR SMTP
    if not SMTP_HOST:
        return
    try:
        msg = EmailMessage()
        msg["Subject"] = "Tu codigo de acceso - SupportDesk"
        msg["From"] = SMTP_FROM
        msg["To"] = email
        msg.set_content(body, subtype="html")

        if SMTP_MODE == "ssl":
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT, context=ctx) as srv:
                if SMTP_USER:
                    srv.login(SMTP_USER, SMTP_PASS or "")
                srv.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as srv:
                srv.ehlo()
                if SMTP_MODE == "starttls":
                    srv.starttls(context=ssl.create_default_context())
                    srv.ehlo()
                if SMTP_USER:
                    srv.login(SMTP_USER, SMTP_PASS or "")
                srv.send_message(msg)
        print(f"[EMAIL-SMTP] OTP enviado a {email} via {SMTP_HOST}:{SMTP_PORT}")
    except Exception as exc:  # no romper el login si el SMTP falla
        print(f"[EMAIL-SMTP][ERROR] no se pudo enviar a {email}: {exc}")


def verify_otp(email, code):
    now = utcnow()
    otps = (
        OtpCode.query.filter_by(email=email)
        .order_by(OtpCode.id.desc())
        .all()
    )
    for otp in otps:
        expires = otp.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=dt.timezone.utc)
        if expires < now:
            continue
        if otp.code == code:
            db.session.commit()
            return True
    return False


# ---------------------------------------------------------------- Sesiones
def issue_session(user):
    token = "sess_" + secrets.token_urlsafe(24)
    db.session.add(Session(token=token, user_id=user.id))
    db.session.commit()
    return token


def current_user():
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.args.get("token")
    if not token:
        return None
    s = Session.query.filter_by(token=token).first()
    return s.user if s else None


def login_required(fn):
    """
    Exige SOLO autenticación (sesión válida).

    OJO: NO valida autorización por tenant. Los endpoints que confían
    únicamente en este decorator quedan expuestos a IDOR cross-tenant (A01).
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "no autenticado"}), 401
        request.user = user
        return fn(*args, **kwargs)
    return wrapper


def agent_required(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "no autenticado"}), 401
        if user.role != "agent":
            return jsonify({"error": "se requiere rol de agente"}), 403
        request.user = user
        return fn(*args, **kwargs)
    return wrapper
