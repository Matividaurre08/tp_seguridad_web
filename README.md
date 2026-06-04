# SupportDesk — Plataforma SaaS de soporte multi-tenant (laboratorio vulnerable)

Aplicación **deliberadamente vulnerable** para el TP de *Seguridad en Aplicaciones
Web* (OWASP Top 10 2025). Reproduce, de punta a punta, la cadena de explotación
descrita en el informe: una plataforma de soporte multi-tenant donde un atacante
que compromete una cuenta de un tenant termina exfiltrando documentos
confidenciales de **otros** tenants.

> ⚠️ Es un entorno de laboratorio pensado para correr **solo en localhost**. No lo
> expongas a una red. Contiene fallas de seguridad introducidas a propósito.

---

## Stack

- Backend: **Python + Flask + SQLAlchemy**
- Base de datos: **SQLite** (archivo `support.db`, se crea y siembra solo)
- Frontend: HTML/CSS/JS sin build (portal de cliente + backoffice de agentes)
- Documentos: PDFs generados localmente (sin dependencias externas)

## Instalación y ejecución

```bash
cd support-saas
python3 -m venv venv && source venv/bin/activate      # opcional
pip install -r requirements.txt
python3 app.py
```

Luego abrir:

- Portal de cliente: <http://127.0.0.1:5000/>
- Backoffice (agentes): <http://127.0.0.1:5000/backoffice>

La primera ejecución crea `support.db` y carga los datos de demo. Para resetear:
`rm support.db` y volver a correr.

### Login passwordless (OTP)

1. Ingresá un email válido y resolvé el captcha aritmético.
2. El código de 4 dígitos se "envía por email": se imprime en la **consola** del
   servidor y se guarda en `./mailbox/<email>.txt`. En el navegador, el login
   muestra un **inbox simulado (DEV)** con el código para que no tengas que mirar
   la consola (equivalente a un MailHog; desactivable con `DEV_MODE=0`).

### Envío del OTP a un correo REAL (SMTP)

El simulador es solo el fallback. Si definís `SMTP_HOST`, el OTP se manda a un
correo real por SMTP (y además se sigue dejando en el simulador local para debug).

Variables de entorno:

| Variable     | Default                         | Descripción |
|--------------|---------------------------------|-------------|
| `SMTP_HOST`  | (vacío → solo simulador)        | host SMTP del proveedor |
| `SMTP_PORT`  | `587`                           | puerto (587 STARTTLS, 465 SSL, 1025/8025 MailHog) |
| `SMTP_MODE`  | `starttls`                      | `starttls` \| `ssl` \| `plain` |
| `SMTP_USER`  | —                               | usuario / dirección de envío |
| `SMTP_PASS`  | —                               | contraseña o **app password** |
| `SMTP_FROM`  | `SMTP_USER`                     | remitente (From) |
| `SEED_REAL_EMAIL` | `alice@acme.local`         | mapea la cuenta agente de ACME a **tu** casilla |

Para que el código te llegue a **tu** inbox, sembrá la cuenta de Alice con tu
dirección (`SEED_REAL_EMAIL`) y configurá el SMTP. Ejemplo con **Gmail** (requiere
una *app password*, no la contraseña normal, con verificación en 2 pasos activada):

```bash
rm -f support.db                       # re-sembrar con tu email
export SEED_REAL_EMAIL="tucorreo@gmail.com"
export SMTP_HOST="smtp.gmail.com" SMTP_PORT=587 SMTP_MODE=starttls
export SMTP_USER="tucorreo@gmail.com" SMTP_PASS="xxxx xxxx xxxx xxxx"
export SMTP_FROM="tucorreo@gmail.com"
python3 app.py
```

Ahora en el login usás `tucorreo@gmail.com` y el OTP llega a esa casilla.
Outlook/Office365: `smtp.office365.com:587` (starttls). Para una bandeja de
captura local sin proveedor: `python3 -m aiosmtpd -n -l 127.0.0.1:8025` con
`SMTP_HOST=127.0.0.1 SMTP_PORT=8025 SMTP_MODE=plain`.

> El PoC (`exploit/exploit.py`) no necesita el email: justamente explota que el OTP
> es adivinable por fuerza bruta sin acceder a la casilla.

### Usuarios sembrados

| Email                | Tenant   | Rol      |
|----------------------|----------|----------|
| `alice@acme.local`   | acme     | agente   | ← cuenta objetivo del ataque
| `bob@acme.local`     | acme     | cliente  |
| `carol@globex.local` | globex   | cliente  |
| `dave@globex.local`  | globex   | agente   |
| `erin@initech.local` | initech  | cliente  |
| `frank@initech.local`| initech  | agente   |

Cada tenant tiene tickets y **una factura con un PDF confidencial** (facturación
y estado contable). Los `public_ref` son **aleatorios**, no incrementales: por eso
descubrirlos requiere la SQLi y no una simple enumeración de IDs.

---

## Funcionalidad legítima

- **Cliente**: crear tickets, adjuntar archivos, ver sus tickets y las facturas de
  su tenant.
- **Agente (backoffice)**: ver la cola, **buscar** tickets, **ordenar** y
  **resolver** tickets.
- Controles correctos (para contraste con las fallas): el detalle de ticket y la
  descarga de adjuntos están **scopeados por tenant**; resolver requiere rol agente.

---

## Cadena de vulnerabilidades (mapa al informe)

| # | OWASP 2025 | Dónde | Endpoint |
|---|------------|-------|----------|
| 0 | **A07** Authentication Failures — enumeración de usuarios | respuesta 200 vs 404 según exista el email | `POST /api/auth/otp/send` |
| 1 | **A06** Insecure Design + **A07** | OTP de 4 dígitos, TTL 15 min, sin rate limit ni bloqueo en la verificación | `POST /api/auth/otp/verify` |
| 2 | **A10** Mishandling of Exceptional Conditions | `sort` interpolado en `ORDER BY`; ante error se devuelve stack trace + query | `GET /api/tickets?sort=` |
| 3 | **A05** SQL Injection (UNION-based) | `q` concatenado sin sanitizar en un `LIKE` | `GET /api/tickets/search?q=` |
| 4 | **A01** Broken Access Control / IDOR | valida sesión pero **no** la pertenencia del recurso al tenant | `GET /api/invoices/<ref>` y `/file` |

### Detalle

**0 + 1 — Acceso sin la cuenta de la víctima.** El captcha protege solo el envío
del OTP. La verificación no tiene límite de intentos ni invalida el código tras
fallos, y el OTP tiene 10.000 combinaciones con 15 minutos de vigencia: se barre
por fuerza bruta. Primero se confirma un email válido por la enumeración (200 vs
404) y luego se solicita un OTP legítimo y se itera `/verify`.

**2 — Fuga de estructura interna.** Una entrada mal formada
(`GET /api/tickets?sort=id'`) provoca un error de SQLite que el backend no maneja:
responde 500 con el mensaje, la **query** completa y el **stack trace**, exponiendo
nombres de tablas y columnas.

**3 — SQLi.** Con esa estructura conocida:
`GET /api/tickets/search?q=urgente' UNION SELECT public_ref, tenant_slug FROM invoices--`
devuelve los identificadores opacos de facturas de **todos** los tenants.

**4 — IDOR.** Con esos `inv_*` se llama
`GET /api/invoices/<ref>` y `GET /api/invoices/<ref>/file`: la sesión es válida
pero no se verifica el tenant, por lo que se descarga el **PDF confidencial** de
otro tenant. Objetivo cumplido.

---

## PoC automatizado

Con el servidor corriendo, en otra terminal:

```bash
python3 exploit/exploit.py --target globex
```

Ejecuta los 5 pasos en orden, encuentra el OTP por fuerza bruta, dispara la SQLi,
explota el IDOR y guarda el documento exfiltrado como `exfil_inv_globex_*.pdf`.

```
[ Paso 0 ] A07 — Enumeración de usuarios ...
[ Paso 1 ] A06/A07 — Fuerza bruta del OTP ...
[ Paso 2 ] A10 — Stack trace en ORDER BY ...
[ Paso 3 ] A05 — SQL Injection UNION-based ...
[ Paso 4 ] A01 — IDOR cross-tenant ...
```

---

## Apéndice — cómo se remediaría cada falla (para el informe)

- **A07 enumeración**: responder siempre genérico ("si el email existe, se envió
  un código"), mismo status y tiempo.
- **A06/A07 OTP**: rate limiting + bloqueo por intentos, invalidar el OTP tras N
  fallos, subir entropía (6+ dígitos / alfanumérico), reducir TTL.
- **A10**: handler global de errores que devuelve un mensaje genérico y loguea el
  detalle del lado del servidor; nunca exponer query/stack al cliente.
- **A05**: consultas parametrizadas / ORM con binding; nunca interpolar entrada en
  SQL (ni siquiera en `ORDER BY`: validar contra una whitelist de columnas).
- **A01**: verificar autorización por tenant en cada acceso a recurso
  (`WHERE tenant_id = :session_tenant`), no solo autenticación.

## Estructura

```
support-saas/
├── app.py            # rutas + vulnerabilidades + arranque
├── auth.py           # captcha, OTP, sesiones, decorators
├── models.py         # modelos SQLAlchemy
├── db.py             # instancia de SQLAlchemy
├── seed.py           # datos de demo + PDFs confidenciales
├── pdfgen.py         # generador de PDF sin dependencias
├── requirements.txt
├── static/           # frontend (portal cliente + backoffice)
├── uploads/          # adjuntos y documentos
├── mailbox/          # OTPs "enviados" (simulador local de email)
└── exploit/exploit.py# PoC de la cadena completa
```
