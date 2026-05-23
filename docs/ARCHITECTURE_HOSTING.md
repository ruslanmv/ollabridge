# OllaBridge — Hosting Architecture

Status: target state. This describes where every public surface lives,
how the DNS resolves, how auth flows across subdomains, and what each
repo owns. The companion document
[`ARCHITECTURE.md`](./ARCHITECTURE.md) describes the system at a
component level; this one is about *deployment*.

## Domain topology

```
                          Internet (users)
                                 │
       ┌─────────────────────────┼─────────────────────────────┐
       │                         │                             │
       ▼                         ▼                             ▼
┌─────────────────┐   ┌─────────────────────┐   ┌──────────────────────┐
│  ollabridge.com │   │  app.ollabridge.com │   │  api.ollabridge.com  │
│   (and www.)    │   │                     │   │                      │
│                 │   │                     │   │                      │
│   Vercel        │   │   HF Space          │   │   HF Space           │
│   static +      │   │   (same app as api) │   │   (same app as app)  │
│   edge fns      │   │                     │   │                      │
│                 │   │                     │   │                      │
│   Marketing     │   │   Admin dashboard   │   │   REST + WebSocket   │
│   Login modal   │   │   (Jinja templates) │   │   /auth /relay /v1   │
│   Lead capture  │   │                     │   │                      │
└────────┬────────┘   └──────────┬──────────┘   └──────────┬───────────┘
         │                       │                         ▲
         │ POST /auth/login      │ shared session cookie   │ WS dial-out
         │ (CORS, withCreds)     │ on .ollabridge.com      │ (no NAT pain)
         └───────────────────────┴─────────────────────────┤
                                                           │
                                                ┌──────────┴──────────┐
                                                │  localhost:11435    │
                                                │  ollabridge local   │
                                                │  (pip install)      │
                                                │  Gateway + admin SPA│
                                                └─────────────────────┘
```

## Surfaces, hosts, repos

| Surface | URL | Host | Repo | Stack | Why this host |
|---|---|---|---|---|---|
| Marketing landing | `ollabridge.com`, `www.ollabridge.com` | **Vercel** | `ollabridge` (`docs/`) | Static HTML + Tailwind CDN | Commercial-friendly TOS, edge functions for forms/A-B, preview deploys per PR, env vars per env, built-in Web Vitals. |
| Cloud admin UI | `app.ollabridge.com` | **HF Space** | `ollabridge-cloud` | FastAPI + Jinja | Stateful sessions, DB-backed views, OAuth callbacks. Cannot be serverless. |
| Cloud API + relay | `api.ollabridge.com` | **HF Space** | `ollabridge-cloud` | FastAPI, WebSockets, Alembic | Same process as the admin UI; long-lived WS relay (`/relay/connect`) needs a real long-running server. |
| Local gateway + admin SPA | `localhost:11435` | User's machine | `ollabridge` (bundled `frontend/`) | Python + React/Vite | Per-machine, not hosted. Talks to `api.ollabridge.com` over WS. |
| (Optional) Dev docs | `docs.ollabridge.com` | GitHub Pages | `ollabridge-cloud` (`docs/`) | Static markdown | Reuse the freed Pages slot for developer-facing docs. Pages' free-hosting TOS is fine for dev docs. |

## DNS records (Cloudflare)

Apex + 4 sub-records. All proxy modes start **DNS-only (gray cloud)** — flip to
Proxied (orange) per record after the origin is verified, otherwise SSL
negotiation against Vercel / HF can be flaky.

| Type | Name | Content | Proxy | TTL | Purpose |
|---|---|---|---|---|---|
| A    | `@`    | `76.76.21.21`              | DNS only | Auto | Vercel apex (anycast) |
| CNAME| `www`  | `cname.vercel-dns.com`     | DNS only | Auto | Vercel www |
| CNAME| `app`  | `ruslanmv-ollabridge-cloud.hf.space` | DNS only | Auto | Cloud admin UI |
| CNAME| `api`  | `ruslanmv-ollabridge-cloud.hf.space` | DNS only | Auto | Cloud API + relay |
| CNAME| `docs` | `ruslanmv.github.io`       | DNS only | Auto | (Optional) dev docs |

> **HF Space caveat:** free HF Spaces don't natively present a custom-domain
> certificate for `app.ollabridge.com` / `api.ollabridge.com`. Three options
> to resolve it, cheapest first:
> 1. **Upgrade to HF Spaces Pro** — custom domain + auto SSL included.
> 2. **Cloudflare proxy with Full(strict)** — enable orange cloud on the
>    `app` and `api` CNAMEs; Cloudflare terminates TLS and re-encrypts to
>    HF's `*.hf.space` cert (which is valid for that hostname). This works
>    in practice but the `Host` header reaching HF will be the proxied
>    one — set HF Space's `SPACE_HOST` allowlist accordingly if it has one.
> 3. **Cloudflare Worker proxy** — a 10-line Worker on `api.ollabridge.com`
>    forwards every request to the HF Space and rewrites the `Host` header.
>    Bulletproof but adds a small CPU/ms cost.

For email (recommended by Cloudflare on the empty-zone page):

| Type | Name | Content | Purpose |
|---|---|---|---|
| MX   | `@` | (your email provider's mailservers) | Receive mail at `hello@ollabridge.com` etc. |
| TXT  | `@` | `v=spf1 include:_spf.mx.cloudflare.net ~all` | SPF (if using Cloudflare Email Routing) |
| TXT  | `_dmarc` | `v=DMARC1; p=quarantine; rua=mailto:dmarc@ollabridge.com` | DMARC |

For DKIM, follow the provider's wizard (Cloudflare Email Routing generates
the records automatically).

## Authentication & session flow

Single sign-in. One cookie, scoped to `.ollabridge.com`, valid on every
sibling subdomain (`app.`, `api.`, `docs.`).

```
sequenceDiagram
    actor User
    participant Land as ollabridge.com (Vercel)
    participant API  as api.ollabridge.com (HF Space)
    participant App  as app.ollabridge.com (HF Space)

    User->>Land: Click "Log in"
    Land-->>User: Modal opens

    alt Email + password
        User->>Land: Submit form
        Land->>API: POST /login (CORS, credentials: include)
        API-->>Land: 200 + Set-Cookie: session=...; Domain=.ollabridge.com; Secure; HttpOnly; SameSite=Lax
        Land-->>User: window.location = app.ollabridge.com
    else Google OAuth
        Land-->>User: redirect → api.ollabridge.com/auth/google/login
        User->>API: (Google handshake)
        API-->>User: 302 → app.ollabridge.com + Set-Cookie (same as above)
    end

    User->>App: GET / (cookie auto-sent — sibling subdomain)
    App-->>User: Render dashboard
```

### Cookie attributes (set by the cloud)

| Attribute | Value | Why |
|---|---|---|
| `Domain` | `.ollabridge.com` | Shared across `app.`, `api.`, and the apex Vercel domain. |
| `SameSite` | `Lax` | Allows the Google OAuth top-level navigation; blocks third-party fetch. |
| `Secure` | `true` | Required for `SameSite=None` and a safety belt for `Lax`. |
| `HttpOnly` | `true` | JS on the marketing site can't read it. SPA calls `/me` to introspect. |
| `Path` | `/` | Whole-app scope. |

### CORS on `api.ollabridge.com`

Credentialed CORS forbids wildcards. The allow-list is concrete:

```
https://ollabridge.com
https://www.ollabridge.com
https://app.ollabridge.com
https://*.vercel.app          # Vercel preview deploys
http://localhost:11435        # local gateway during dev
http://localhost:3000          # local Vite dev
```

`Access-Control-Allow-Credentials: true`. Same allow-list applied to
the SessionMiddleware for cross-subdomain sessions.

## Per-repo responsibilities

### `ollabridge`

| File | Responsibility |
|---|---|
| `docs/index.html` | Marketing landing. `window.OBRIDGE` config block holds all downstream URLs. |
| `docs/vercel.json` | Vercel build / headers / cache config. |
| `docs/CNAME` | Pages fallback (kept for instant rollback). |
| `frontend/src/lib/api.ts` (future) | Read `import.meta.env.VITE_CLOUD_URL` (defaults to `https://api.ollabridge.com`). |

### `ollabridge-cloud`

| File | Responsibility |
|---|---|
| `src/.../config.py` | Owns `CORS_ORIGINS`, `SESSION_COOKIE_DOMAIN`, `POST_LOGIN_URL`. All env-driven. |
| `src/.../main.py` | Wires `SessionMiddleware(domain=…)` and `CORSMiddleware` from settings. |
| `src/.../auth/__init__.py` | Google callback redirects to `POST_LOGIN_URL` (default `/dashboard`). |
| `src/.../web/routes.py` | Email login + signup redirect to `POST_LOGIN_URL`. |
| `.github/workflows/sync-hf-space.yml` | Push to HF Space on every master push (already exists). |

## Migration sequence

```
T+0   Merge claude/elegant-ptolemy-7Jqfu to master.
      ollabridge.com keeps working via GitHub Pages (rollback path).

T+1   Add the 4 DNS records above in Cloudflare (proxy = DNS only).

T+2   Connect ollabridge repo to Vercel.
        Root directory : docs/
        Framework      : Other
        Build command  : (none)
        Output         : .
      Bind ollabridge.com + www.ollabridge.com as custom domains in Vercel.
      Verify the *.vercel.app preview, then the apex.

T+3   In HF Space settings, bind app.ollabridge.com and api.ollabridge.com
      as custom domains. Wait for cert issuance.

T+4   Deploy cloud with:
        SESSION_COOKIE_DOMAIN=.ollabridge.com
        POST_LOGIN_URL=https://app.ollabridge.com/dashboard
        CORS_ORIGINS=https://ollabridge.com,https://www.ollabridge.com,https://app.ollabridge.com

T+5   Set Pages "Source" to None (or keep as fallback). Vercel is canonical.

T+6   Smoke-test login end-to-end:
        - apex → modal → email/pw → app
        - apex → modal → Google → app
        - app → log-out → apex
```

Every step is reversible.

## Out-of-scope (deliberately)

- **Cloud on Vercel.** Vercel's Python runtime is serverless — no long-lived
  WebSocket relay, cold starts on every chat completion. Stay on HF Space.
- **Splitting `app` and `api` into two HF Spaces.** They share DB, session
  store, auth, and provider config. Splitting doubles the deploy cost for
  no win.
- **Rebuilding the cloud dashboard as a Vercel SPA.** The Jinja UI works
  today. Defer until the dashboard needs richer client-side interactions
  (live charts, drag-and-drop), then carve out `app.ollabridge.com` as a
  separate Vite project.
- **Two CNAMEs at the apex.** Pick one canonical host (Vercel). The other
  can be a 301 redirect on a sibling domain during cut-over.
