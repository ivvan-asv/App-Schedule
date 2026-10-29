# Conectar Google Calendar y Outlook

Guía para obtener las credenciales OAuth y conectarlas al backend. Una vez
configuradas, cada usuario conecta su cuenta desde la app
(**Ajustes › Calendarios conectados**) y las capturas evitan las horas ocupadas
de esos calendarios.

## Cómo funciona

```text
App iOS ──(1) POST /calendar-accounts/{google|microsoft}/authorize──▶ Backend
App iOS ◀─(2) authorization_url ─────────────────────────────────────┘
App iOS ──(3) abre la página de Google/Microsoft (ASWebAuthenticationSession)
Google/Microsoft ──(4) redirige a {OAUTH_REDIRECT_BASE_URL}/api/v1/oauth/{proveedor}/callback ──▶ Backend
Backend ──(5) canjea el código con el client secret, guarda los tokens cifrados (AES-256-GCM)
Backend ──(6) redirige a smartscheduler://calendar-connected?status=ok ──▶ App iOS
```

- El *client secret* vive solo en el `.env` del backend, nunca en el iPhone.
- Se usa PKCE y un `state` de un solo uso guardado 10 minutos en **Redis**.
- Los tokens se guardan en `cuentas_calendario` cifrados con `TOKEN_ENCRYPTION_KEY`.
- Por ahora solo se **leen horas ocupadas** (inicio y fin). Ya se pide el permiso
  de escritura para que, cuando la app escriba eventos en Google/Outlook, no haya
  que volver a conectar.

## Variables en `.env` (raíz del repo)

| Variable | Qué es |
| :--- | :--- |
| `TOKEN_ENCRYPTION_KEY` | Clave para cifrar los tokens. Obligatoria. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | Cliente OAuth de Google (paso 2). |
| `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET` | Registro de app de Microsoft (paso 3). |
| `MICROSOFT_TENANT` | `common` (cuentas personales y de trabajo), `consumers` (solo personales) u `organizations`. |
| `OAUTH_REDIRECT_BASE_URL` | URL del backend tal como la ve el navegador. `http://localhost:8000` en el simulador; un túnel HTTPS en el iPhone (paso 4). |
| `APP_OAUTH_CALLBACK_URL` | Déjalo en `smartscheduler://calendar-connected`. |

Los nombres antiguos `GOOGLE_CALENDAR_CLIENT_ID/SECRET` y
`MICROSOFT_GRAPH_CLIENT_ID/SECRET` también se aceptan.

Después de editar `.env`, **reinicia uvicorn**.

## 1. Clave de cifrado

```bash
python3 -c "import base64,secrets;print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Pega el resultado en `TOKEN_ENCRYPTION_KEY`. No la cambies después: los tokens
guardados con otra clave dejan de poder leerse y habría que reconectar.

## 2. Google Calendar

1. Entra en <https://console.cloud.google.com> y crea un proyecto
   (por ejemplo «Smart Scheduler»).
2. **APIs y servicios › Biblioteca**: busca **Google Calendar API** y pulsa
   **Habilitar**.
3. **Google Auth Platform** (antes «Pantalla de consentimiento de OAuth») ›
   **Comenzar**:
   - Nombre de la app y correo de asistencia.
   - Público: **Externo**.
4. **Público › Usuarios de prueba**: añade los Gmail que van a probar la app.
   Mientras la app esté en modo «Prueba» solo esas cuentas pueden conectarse.
5. **Acceso a los datos › Agregar o quitar permisos**: añade
   - `openid`
   - `.../auth/userinfo.email`
   - `https://www.googleapis.com/auth/calendar.freebusy`
   - `https://www.googleapis.com/auth/calendar.events`
6. **Clientes › Crear cliente**:
   - Tipo de aplicación: **Aplicación web**.
   - **URI de redireccionamiento autorizados**: el `redirect_uri` que muestra
     `GET /api/v1/calendar-providers` (paso 5). Por defecto
     `http://localhost:8000/api/v1/oauth/google/callback`. Si usas túnel, añade
     también la de su URL.
7. Copia el **ID de cliente** y el **Secreto del cliente** a `GOOGLE_CLIENT_ID`
   y `GOOGLE_CLIENT_SECRET`.

> En modo «Prueba», Google invalida el *refresh token* a los 7 días. La app
> mostrará «Reconectar». Para evitarlo, publica la app en **Público › Publicar
> app** (los permisos de calendario requieren verificación de Google para
> usuarios fuera de la lista de prueba).

## 3. Outlook (Microsoft Graph)

1. Entra en <https://entra.microsoft.com> › **Identidad › Aplicaciones ›
   Registros de aplicaciones › Nuevo registro**.
2. Nombre: «Smart Scheduler». Tipos de cuenta admitidos:
   **Cuentas en cualquier directorio organizativo y cuentas personales de
   Microsoft** (corresponde a `MICROSOFT_TENANT=common`).
3. **URI de redirección**: plataforma **Web**, valor
   `http://localhost:8000/api/v1/oauth/microsoft/callback` (o la del túnel).
4. En **Información general**, copia el **Id. de aplicación (cliente)** a
   `MICROSOFT_CLIENT_ID`.
5. **Certificados y secretos › Nuevo secreto de cliente**. Copia la columna
   **Valor** (no el «Id. de secreto») a `MICROSOFT_CLIENT_SECRET`. Anota la
   fecha de expiración: al vencer hay que crear otro.
6. **Permisos de API › Agregar un permiso › Microsoft Graph › Permisos
   delegados**: `openid`, `email`, `offline_access`, `User.Read`,
   `Calendars.ReadWrite`. No hace falta consentimiento de administrador para
   cuentas personales.

## 4. Probar desde el iPhone (túnel HTTPS)

Google y Microsoft solo aceptan redirecciones `http://` hacia `localhost`, y el
navegador del iPhone no llega al `localhost` del Mac. Para el iPhone, expón el
backend con un túnel HTTPS:

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
# → https://algo-aleatorio.trycloudflare.com
```

1. Pon esa URL en `OAUTH_REDIRECT_BASE_URL` y reinicia uvicorn.
2. Registra `https://algo-aleatorio.trycloudflare.com/api/v1/oauth/google/callback`
   en Google y la de `/microsoft/callback` en Microsoft.
3. En la app, **Ajustes › Servidor**: usa también esa URL `https://`. Así el
   iPhone no necesita la excepción de red local.

La URL de `trycloudflare.com` cambia cada vez que arrancas el túnel. Si te
cansa volver a registrarla, usa un túnel con nombre fijo (Cloudflare Tunnel con
tu dominio, o un dominio estático de ngrok).

En el **simulador** no hace falta túnel: `http://localhost:8000` funciona tal cual.

## 5. Comprobar la configuración

Con Redis y PostgreSQL levantados (`docker compose up -d db redis`) y uvicorn
corriendo:

```bash
curl http://localhost:8000/api/v1/calendar-providers
```

```json
[
  {"provider": "google", "configured": true, "missing_settings": [],
   "redirect_uri": "http://localhost:8000/api/v1/oauth/google/callback"},
  {"provider": "microsoft", "configured": false,
   "missing_settings": ["MICROSOFT_CLIENT_SECRET"], "redirect_uri": "..."}
]
```

`missing_settings` dice qué falta, y `redirect_uri` es exactamente lo que hay
que registrar en cada consola. La app muestra lo mismo en **Ajustes ›
Calendarios conectados** mientras falte algo.

## Problemas frecuentes

| Síntoma | Causa |
| :--- | :--- |
| Google: `redirect_uri_mismatch` | La URI registrada no es idéntica al `redirect_uri` de `/calendar-providers` (mira `http`/`https`, puerto y barra final). |
| Google: `access_denied` o «app no verificada» bloqueante | Tu Gmail no está en **Usuarios de prueba**. |
| Microsoft: `AADSTS50011` | La URI de redirección no coincide con la registrada. |
| Microsoft: `AADSTS700016` / `AADSTS50020` | `MICROSOFT_TENANT` no corresponde a los tipos de cuenta del registro. |
| La app vuelve con «La conexión caducó» | Pasaron más de 10 minutos, o Redis no está corriendo. |
| La cuenta aparece con «Reconectar» | El usuario revocó el acceso, el secreto de Microsoft venció o (Google en modo prueba) pasaron 7 días. |
