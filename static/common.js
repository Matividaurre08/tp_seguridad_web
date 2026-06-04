// ----- Helpers compartidos: API, sesión y login OTP -----
const TOKEN_KEY = "sd_token";

function token() { return localStorage.getItem(TOKEN_KEY); }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

async function api(path, opts = {}) {
  const headers = opts.headers || {};
  if (token()) headers["Authorization"] = "Bearer " + token();
  if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const res = await fetch(path, { ...opts, headers });
  let data = null;
  try { data = await res.json(); } catch (e) {}
  return { status: res.status, data };
}

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Widget de login passwordless (etapa 1: email+captcha, etapa 2: OTP)
function renderLogin(container, subtitle, onSuccess) {
  let captcha = null;

  async function loadCaptcha() {
    const { data } = await api("/api/auth/captcha");
    captcha = data;
    document.getElementById("captchaQ").textContent = data.question;
  }

  container.innerHTML = `
    <div class="login-shell"><div class="login card">
      <h2>Acceso</h2>
      <div class="hint">${subtitle}</div>

      <div id="stage1">
        <label>Email corporativo</label>
        <input id="email" placeholder="alice@acme.local" autocomplete="off">
        <label>Verificación: <span id="captchaQ" class="mono"></span></label>
        <input id="captcha" placeholder="resultado" autocomplete="off">
        <div class="spacer"></div>
        <button class="btn" id="sendBtn" style="width:100%">Enviar código</button>
      </div>

      <div id="stage2" style="display:none">
        <label>Código de un solo uso (enviado por email)</label>
        <input id="otp" placeholder="Ingresá tu código" inputmode="numeric" autocomplete="one-time-code">
        <div class="spacer"></div>
        <button class="btn" id="verifyBtn" style="width:100%">Ingresar</button>
        <div class="note">Te enviamos un código a tu email. Revisá tu casilla.</div>
      </div>

      <div class="error" id="loginErr"></div>
    </div></div>`;

  const err = (m) => (document.getElementById("loginErr").textContent = m || "");

  loadCaptcha();

  document.getElementById("sendBtn").onclick = async () => {
    err("");
    const email = document.getElementById("email").value.trim().toLowerCase();
    const { status } = await api("/api/auth/otp/send", {
      method: "POST",
      json: { email, captcha_id: captcha.captcha_id, captcha: document.getElementById("captcha").value.trim() },
    });
    if (status === 200) {
      document.getElementById("stage1").style.display = "none";
      document.getElementById("stage2").style.display = "block";
      document.getElementById("otp").focus();
      window.__loginEmail = email;
    } else if (status === 404) {
      err("No existe una cuenta con ese email.");
      loadCaptcha();
    } else {
      err("Verificación incorrecta. Probá de nuevo.");
      loadCaptcha();
    }
  };

  container.addEventListener("click", (e) => {
    if (e.target && e.target.id === "verifyBtn") doVerify();
  });

  async function doVerify() {
    err("");
    const otp = document.getElementById("otp").value.trim();
    // Validación del lado del cliente (revela que el OTP es de 4 dígitos)
    if (!/^\d{4}$/.test(otp)) {
      err("Ingresá un código de 4 dígitos");
      return;
    }
    const { status, data } = await api("/api/auth/otp/verify", {
      method: "POST",
      json: { email: window.__loginEmail, otp },
    });
    if (status === 200) {
      setToken(data.session_token);
      onSuccess(data.user);
    } else {
      err("Código inválido.");
    }
  }
}
