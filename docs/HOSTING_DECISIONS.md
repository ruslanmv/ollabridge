# Hosting Decisions — Why this shape

> Companion to [`ARCHITECTURE_HOSTING.md`](./ARCHITECTURE_HOSTING.md). That
> document describes *what* the topology is. This one explains *why* — the
> trade-offs considered and the reasons each choice landed where it did.
> Treat this as a lightweight ADR (Architecture Decision Record).

---

## Decision 1 — Why introduce `api.ollabridge.com` and `app.ollabridge.com` at all

We could have served everything from the bare HF Space URL
(`https://ruslanmv-ollabridge.hf.space`) and skipped DNS work entirely.
That option is real and works, but loses on five fronts that matter for
a commercial product.

### 1.1 The cross-subdomain session cookie

The single biggest reason. We want a user who logs in once on the
marketing site to stay logged in on the dashboard, and to keep that
session even if the cloud backend later moves off the HF Space.

A cookie with `Domain=.ollabridge.com` is shared by every host under
that domain — apex, `api`, `app`, anything future. A cookie set on
`ruslanmv-ollabridge.hf.space` is shared by **nothing outside that
exact hostname**, and the browser will never send it to `ollabridge.com`
or any sibling.

| Without subdomains | With subdomains |
|---|---|
| Log in on HF Space → cookie scoped to `*.hf.space`. | Log in via `api.ollabridge.com` → cookie scoped to `.ollabridge.com`. |
| Visit `ollabridge.com` → no cookie → "log in" button appears even though you're logged in. | Visit `ollabridge.com` → cookie sent → "Welcome back" state. |
| Move the backend later → all sessions die. | Move the backend later → CNAME flip; sessions survive. |

That last row is the killer feature. The cookie is decoupled from where
the backend actually runs.

### 1.2 Branding and trust

Users see URLs in:
- Browser address bars during OAuth handoff.
- "Continue with Google" consent screens that read "OllaBridge wants
  to access your basic info" — Google extracts the brand name from the
  Authorized Domains, which must match the OAuth redirect URI's host.
- Phishing-detection heuristics in browsers and email clients (Gmail's
  "this link goes to hf.space, are you sure?" warning bar).
- Status pages, support replies, technical blog posts.

Every one of those reads better as `api.ollabridge.com` than
`ruslanmv-ollabridge.hf.space`. The marketing-landing → cloud-API → admin
flow looks like a coherent product, not a cobbled-together stack.

### 1.3 Separation of concerns at the URL level

`api.` and `app.` aren't decoration — they're a contract:

| Subdomain | Surfaces | Audience |
|---|---|---|
| `ollabridge.com` | Marketing landing, login modal | Anonymous visitors |
| `app.ollabridge.com` | Dashboard, account management (Jinja UI) | Logged-in humans |
| `api.ollabridge.com` | `/v1/chat/completions`, `/relay/connect`, `/auth/*` | SDKs, agents, the local gateway |

A program that wants to call the OpenAI-compatible endpoint hard-codes
`api.ollabridge.com`. A human bookmarking the dashboard saves
`app.ollabridge.com/dashboard`. If we ever split the API into its own
container (e.g. for autoscaling) we re-point one CNAME; client code
doesn't change. Bundling everything onto the apex would couple all
three audiences to the same host and the same scaling fate.

### 1.4 CORS and OAuth get simpler, not harder

A common worry: "Won't subdomains create CORS pain?" In practice the
opposite — explicit subdomains make the allow-list crisp:

```
CORS_ORIGINS=https://ollabridge.com,https://www.ollabridge.com,https://app.ollabridge.com
```

Concrete, auditable, no wildcards. The OAuth Authorized Domains list
on Google is also tidier: `ollabridge.com` covers every sub-host.

Without subdomains we'd be allowlisting `*.hf.space` (CORS reluctantly
permits this but it's a much wider blast radius — every HF Space could
theoretically post to your API), or we'd never have CORS at all because
the marketing site couldn't talk to the backend.

### 1.5 Future-proofing the move off HF

The single most expensive migration in any SaaS is "we have to change
URLs because we moved providers." When the cloud outgrows the free HF
Space tier (and it will — cold starts, no autoscaling, no
multi-region), we want to move it without invalidating sessions,
breaking SDK integrations, or telling every user to update bookmarks.

With subdomains: re-point `api.ollabridge.com` CNAME. Done.
Without subdomains: every reference to `ruslanmv-ollabridge.hf.space`
in user code, scripts, agent configs, screenshots, and tutorials becomes
a broken link.

---

## Decision 2 — Why a CNAME alone isn't enough

This is the surprising bit. Once we decided on subdomains, the obvious
move is:

```
CNAME  api  →  ruslanmv-ollabridge.hf.space
CNAME  app  →  ruslanmv-ollabridge.hf.space
```

Doesn't work. Two reasons, both rooted in how TLS and HTTP layer
interact:

### 2.1 The TLS certificate problem

When a browser connects to `https://api.ollabridge.com`, the *first*
thing that happens — before HTTP, before headers, before the URL is
even parsed — is a TLS handshake. The browser sends the hostname it
wants (`api.ollabridge.com`) inside the **SNI** (Server Name
Indication) field. The server must respond with a certificate that
covers that hostname.

The HF Space presents a certificate for `*.hf.space`. The browser sees
"I asked for api.ollabridge.com, you gave me a cert for *.hf.space →
mismatch" and aborts with `NET::ERR_CERT_COMMON_NAME_INVALID`. There
is no way for HF (or anyone other than the domain owner) to issue a
cert for `api.ollabridge.com`.

A naive CNAME just rewrites DNS resolution — it doesn't change what
TLS cert the destination presents.

### 2.2 The Host header routing problem

Even if the TLS issue were solved, HF Space's edge router has thousands
of Spaces behind it and decides which one to forward the request to
**based entirely on the `Host:` header**. A request with
`Host: api.ollabridge.com` matches *no Space*, so HF returns its
generic "Space not found" 404 page.

So two layers need fixing, not one:
- The TLS layer (cert that the browser accepts).
- The HTTP layer (Host header that HF recognises).

---

## Decision 3 — The four ways to bridge the gap

We surveyed every realistic option. Here's the full landscape with the
honest reasons each was accepted or rejected:

### 3.1 Hugging Face Spaces Pro custom domain ($9/mo per user) — REJECTED for now

How it works: HF Pro tier lets you bind a custom domain on the Space.
HF issues a real Let's Encrypt cert for `api.ollabridge.com` and
handles Host routing internally. Cleanest possible solution.

**Pros**
- Zero infrastructure, zero code. Just a DNS record and a checkbox.
- Native cert issuance; no proxy layer; no headers to forward.
- Best for production reliability — fewest moving parts.

**Cons**
- Costs money — modest ($9/mo) but ongoing.
- One more vendor with a billing relationship.
- Doesn't give you anything else useful for the price.

**Verdict:** This is the right answer eventually. For early-stage when
the goal is to ship without a credit card, we use Path 3.3 (Workers)
and migrate to this when revenue justifies a $108/year line item.

### 3.2 Cloudflare Origin Rule with SNI Override — REJECTED (Pro paywall)

How it should have worked: Cloudflare's Origin Rules feature lets you
rewrite the `Host` header and the SNI value before forwarding to an
origin. The browser hits Cloudflare (which presents *its* universal
SSL cert for `*.ollabridge.com`), Cloudflare rewrites Host + SNI to
`ruslanmv-ollabridge.hf.space`, opens a fresh TLS leg to HF, HF
accepts. Same effect as Workers but configured declaratively in the
dashboard.

**Pros**
- No code. Two fields in a UI form.
- Single rule covers both `api` and `app` subdomains.
- Cloudflare manages everything; nothing to deploy or maintain.

**Cons**
- **SNI override is gated to the Cloudflare Pro plan ($20/mo).** Host
  header override on its own is free, but without SNI rewrite the
  inner TLS handshake fails in Full (strict) mode because Cloudflare
  sends `SNI=api.ollabridge.com` and HF can't produce a matching cert.

**Verdict:** Rejected solely because of the $20/mo paywall. If we ever
buy Cloudflare Pro for the WAF / advanced analytics features anyway,
the Origin Rule becomes preferable to the Worker (less code surface).

### 3.3 Cloudflare Worker as reverse proxy — CHOSEN

How it works: Cloudflare lets us bind a small JavaScript function
("Worker") to a URL pattern. When a request matches
`api.ollabridge.com/*` or `app.ollabridge.com/*`, the Worker
intercepts it, rewrites the URL to point at HF, and uses `fetch()` to
forward the request. The fetch happens *from* Cloudflare's edge,
which opens a fresh TLS connection with `SNI=ruslanmv-ollabridge.hf.space`,
so HF's cert validates correctly. The Host header is set automatically
from the new URL hostname.

**Pros**
- Free. The Workers free tier is **100,000 requests/day** with
  unlimited bandwidth and 10 ms CPU per request. We use <1 ms per
  request. At our scale, this will outlast the runway.
- Solves both the TLS and Host header problems in one place.
- Programmable: if we ever need to add rate limiting, inject custom
  headers, A/B route requests, or strip sensitive cookies before they
  hit HF, it's a few lines of code.
- Single Worker covers both subdomains via two Route bindings.
- Logs and observability built in (Cloudflare's Workers dashboard
  shows live request streams).

**Cons**
- Code is now a thing we maintain — about 20 lines of JavaScript.
- One more deployment surface to think about during incidents.
- Subtle gotcha with WebSocket upgrades — must use the
  `new Request(url, sourceRequest)` clone form for `fetch()`, not the
  options-bag form. Documented in the Worker source comments so the
  next person doesn't re-discover it.

**Verdict:** The right answer for the current stage. Zero cost,
trivial code, real flexibility. The 20 lines of JS are stable — no
expected reason to touch them again.

### 3.4 Skip the subdomains entirely — REJECTED

How it would have worked: keep the cloud at
`ruslanmv-ollabridge.hf.space`. The marketing landing's OAuth modal,
SDK base URLs, dashboard links — all point at the HF URL.

**Pros**
- Truly zero infrastructure.
- Nothing to maintain.

**Cons**
- All five problems from Decision 1 reappear. Most importantly:
  no cross-subdomain SSO and no portability if we leave HF.
- Brand bleeds. Every URL anyone sees has "hf.space" in it.
- OAuth Authorized Domain has to be `hf.space` (a domain we don't
  own), which Google will flag during the consent-screen
  verification stage of "Publishing" the OAuth app.

**Verdict:** Rejected. The portability concern alone outweighs the
~30 minutes of infrastructure work.

---

## Decision summary in one paragraph

We split the public surface into `ollabridge.com` (marketing on
Vercel) + `app.ollabridge.com` (dashboard) + `api.ollabridge.com`
(API) because it gives us cross-subdomain single sign-on, a portable
backend, a credible brand on every URL the user sees, and a clean
separation of audiences. A bare CNAME to HF Space doesn't work
because of TLS cert and HTTP Host header mismatches that span two
layers of the stack. Cloudflare's declarative Origin Rule would solve
both but the SNI half is paywalled at $20/mo. So we use a 20-line
Cloudflare Worker as a free reverse proxy, sitting on Cloudflare's
free tier (100k req/day) with room for orders of magnitude more
traffic than we currently see. When revenue justifies it, the cleanest
migration is to HF Spaces Pro custom domain ($9/mo) — flip the CNAME
target, retire the Worker, done.

---

## What we'd reconsider when

| Trigger | Switch to |
|---|---|
| Real production traffic (10k+ DAU sustained) | Either HF Pro custom domain or move the backend off HF Space entirely to Fly.io/Render |
| Need WAF for compliance, or bot protection beyond Cloudflare free | Cloudflare Pro — Origin Rule replaces the Worker as a side effect |
| Need preview environments per branch for the cloud backend | Move backend to Fly.io/Render (HF Spaces has only one branch) |
| Need to add request-level customisation (rate limiting per tier, header injection, response caching) | Expand the existing Worker — it's already in the request path; this is cheap |

None of these triggers are close. The current shape is durable for
the foreseeable future.
