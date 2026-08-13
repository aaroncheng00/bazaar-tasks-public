# Bazaar — The Embeddable P2P Marketplace Primitive

> A lightweight, embeddable commerce layer that lets any app become a peer-to-peer marketplace — built entirely on open / standard technology.

**One-liner:** Stripe made every app a store. **Bazaar makes every app a marketplace.**

Bazaar provides the heavy lifting for peer-to-peer commerce — inventory, discovery, trust & reputation, contact routing, and media — while the integrator retains full control over UX, auth, and messaging. Integrators can go from zero to first live listing in **< 60 minutes**.

> **Repo:** `https://github.com/metainternal-aai/aai_labs_bazaar`  
> **Design doc:** Internal proposal (Google Doc `1eEzBmMOqZHm-bqdG-8dPwnaFdpNwcL7klP8cVU9JeGk`)  
> **Status:** MVP in active development — headless API + TS SDK + reference demo

---

## Why Bazaar?

### The problem

P2P commerce today is fragmented:

* **Siloed marketplaces** (Mercari, OfferUp, Craigslist) — standalone apps with cold-start problems, no way for other communities to tap in.
* **Unstructured social surfaces** (Instagram notes, WhatsApp statuses, FB Groups, Discord) — where most local resale actually happens today, but with zero structure, price discovery, or buyer/seller protection.
* **Community apps** (neighborhood, hobby, campus, fandom) — where commerce is a natural extension, but building marketplace infra takes 6+ months and requires expertise in inventory, trust, moderation, payments, and fraud.

Result: massive demand transacts informally. Accenture projects social commerce reaching **$1.2T by 2026**, Facebook Marketplace sees **1B monthly visitors / 50M sellers**, yet there is no `Stripe for marketplaces`.

### The solution

Bazaar is a **full-stack, embeddable marketplace primitive**:

| Layer | Bazaar provides | Integrator owns |
|-------|-----------------|-----------------|
| **Inventory** | Listing CRUD, categories, condition, geohashing, image upload via presigned R2, full-text search | UI rendering |
| **Discovery** | Browse by category / proximity / text, cursor pagination, GIN-indexed search | Ranking / personalization |
| **Trust** | Reviews (1-5 + body), aggregate reputation counters, unique-review constraints | Identity, moderation UX |
| **Contact / Offers** | Threaded offer flow (`open → accepted / declined / withdrawn`), callback handoff | Real messaging (WhatsApp, IG DM, etc.) |
| **Media** | Direct-to-R2 uploads, no large blobs in DB | Image optimization in client |

**Principles (MVP contracts):**

* **Integrator-owned identity** — Bazaar never sees PII as an identity key. Integrators pass opaque `user_id` (e.g. hashed WA ID). Contact handles (phone, IG handle) are only returned on `accepted`.
* **Tenant isolation by `app_id`** — every row is scoped to `app_id` + Row Level Security (RLS). Separate API key + HMAC per tenant.
* **Integer money** — `price_cents` + `currency` (char 3), no floats.
* **Cursor pagination** — `?cursor=&limit=` everywhere, consistent for infinite scroll.
* **Error envelope** — `{ error: { code, message, request_id } }`
* **Idempotency** — `Idempotency-Key` header on POSTs.
* **No message routing in MVP** — Bazaar does *not* store or proxy chat. On accept, it hands back the seller's contact handle and the host app's native chat takes over.

Non-goals for MVP: authentication, transaction rails (Stripe Connect → v1), advanced trust scoring / ID verification.

---

## Architecture

```
┌─────────────┐        ┌─────────────────────────────────────────────────┐
│ Integrator  │        │                 Bazaar API (FastAPI)            │
│ App         │ ─────▶ │  /v1/listings  /v1/reviews  /v1/contacts       │
│ (owns auth, │        │  • RLS by app_id  • cursor pagination           │
│  UX, chat)  │ ◀───── │  • integer cents  • error envelope + req_id     │
└─────────────┘        └──────────┬──────────┬───────────┬──────────────┘
                                  │          │           │
                       ┌──────────▼──┐ ┌────▼─────┐ ┌───▼─────┐
                       │ Postgres    │ │ Redis    │ │ R2 / S3 │
                       │ + pg_trgm   │ │ counters │ │ media   │
                       │ + tsvector  │ │ + rate-  │ │ (presig-│
                       │ + RLS + GIN │ │ limiting │ │ ned URL)│
                       └─────────────┘ └──────────┘ └─────────┘

Hosted SDKs: TypeScript (MVP) → Swift / Kotlin (v1)
Demo: Next.js reference app showing time-to-first-listing
Docs: Docusaurus site with OpenAPI rendering
```

**Open stack (no Meta-internal deps):**

* API: Python / FastAPI / REST / OpenAPI, Pydantic v2, SQLAlchemy / Alembic
* DB: Managed Postgres (Render / Supabase) + pg_extensions for full-text & geohash
* Media: Cloudflare R2 / S3 with presigned POST/PUT
* Cache/counters: Redis (upstash) for `avg_rating`, `review_count`, idempotency
* Infra: Terraform, Docker, Render pre-deploy migrations (not startup — safe for >1 replica)
* Docs: Docusaurus + OpenAPI plugin
* SDK: TypeScript, `fetch` based, typed from spec

---

## Monorepo Layout

```
.
├── apps/
│   ├── api/                # FastAPI headless API
│   │   ├── src/bazaar_api/
│   │   │   ├── db/models/  # listing, review, contact + Alembic migrations
│   │   │   ├── modules/    # listings / reviews / contacts domain logic
│   │   │   ├── search/     # tsvector generation, geohash, ranking
│   │   │   ├── media/      # R2 presigned URL issuer
│   │   │   └── middleware/ # request_id, RLS, auth (app_id HMAC), rate-limit
│   │   └── tests/
│   │       ├── unit/       # domain logic
│   │       ├── integration/# endpoint + DB tests
│   │       └── rls/        # tenant isolation negative tests
│   ├── demo/               # Reference marketplace (Next.js)
│   │   └── src/            # Browse, list, offer, review flow — <60min onboarding target
│   └── docs/               # Docusaurus site (OpenAPI rendered from /spec)
├── packages/
│   ├── sdk/                # @bazaar/sdk — typed TS client
│   │   └── src/client/
│   └── tsconfig/           # Shared TS configs
├── spec/                   # OpenAPI + JSON Schema source of truth
│   ├── components/
│   │   ├── schemas/
│   │   ├── parameters/
│   │   └── responses/
│   └── examples/
│       └── whatsapp-accept.json
├── infra/
│   ├── postgres/init/      # Extensions, RLS policies
│   ├── seed/               # Faker seed for demo categories
│   └── terraform/          # Render + R2 + Redis, secrets management
└── .github/workflows/      # lint, test, typecheck, render deploy
```

---

## Quick Start — Time to First Listing (< 60 min)

### 1. Prereqs

```bash
# core
node >= 20
pnpm >= 9
python >= 3.12
docker # for local postgres + redis

# recommended
uv # python fast runner
```

### 2. Clone + install

```bash
git clone https://github.com/metainternal-aai/aai_labs_bazaar.git
cd aai_labs_bazaar

# JS workspaces (demo, docs, sdk)
pnpm install

# Python API
cd apps/api
uv sync   # or: pip install -e ".[dev]"
```

### 3. Local infra

```bash
# from repo root — brings up postgres (with pg_trgm), redis, fake R2 via minio
docker compose up -d

# init DB: extensions + RLS + migrations
cd apps/api
alembic upgrade head
python -m bazaar_api.db.seed --categories furniture,electronics,apparel,baby-gear
```

Environment (`apps/api/.env`) — all API settings are prefixed `BAZAAR_`:

```
BAZAAR_DATABASE_URL=postgresql+asyncpg://bazaar:bazaar@localhost:5432/bazaar
BAZAAR_APP_DATABASE_URL=postgresql+asyncpg://bazaar_app:bazaar_app@localhost:5432/bazaar
BAZAAR_KEYS={"bzk_dev": {"secret": "bzs_dev_secret", "app_id": "app-a"}}
BAZAAR_REDIS_URL=redis://localhost:6379/0
R2_ENDPOINT=http://localhost:9000
R2_BUCKET=bazaar-media
R2_ACCESS_KEY_ID=minio
R2_SECRET_ACCESS_KEY=minio123
```

### 4. Run API

```bash
# auto-reload, request_id logging
uvicorn bazaar_api.main:app --reload --port 8080

# → http://localhost:8080/docs (OpenAPI Swagger)
# → http://localhost:8080/healthz
```

### 5. Run demo + SDK

```bash
# in repo root
pnpm -F @bazaar/demo dev        # http://localhost:3000 — full listing→browse→offer flow

pnpm -F @bazaar/sdk build       # builds typed client from ../spec
pnpm -F @bazaar/docs dev        # Docusaurus with live OpenAPI
```

---

## API Design — MVP

Versioned by path: `/v1/listings`, `/v1/reviews`, `/v1/contacts`. Breaking changes → `/v2` with deprecation header.

### Listings

```
POST   /v1/listings              # create + idempotency-key
GET    /v1/listings              # browse: ?category=&q=&lat=&lng=&radius_km=&cursor=&limit=20
GET    /v1/listings/:id
PATCH  /v1/listings/:id          # seller only (via opaque seller_user_id check in service layer + RLS)
DELETE /v1/listings/:id
POST   /v1/listings/:id/images   # returns presigned R2 URL, client PUTs directly to R2
```

Example:

```bash
curl -X POST http://localhost:8080/v1/listings \
  -H "X-Bazaar-Key: $KEY_ID" \
  -H "X-Bazaar-Timestamp: $TS" \
  -H "X-Bazaar-Signature: $HMAC" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/json" \
  -d '{
    "seller_user_id": "wa_usr_88f2a1",
    "title": "Uppababy stroller - like new",
    "description": "Used 3 months, smoke-free, pickup in Noe Valley",
    "price_cents": 35000,
    "currency": "USD",
    "category": "baby-gear",
    "condition": "like-new",
    "lat": 37.7508,
    "lng": -122.4342,
    "contact": {"type": "whatsapp", "handle": "+14150000001"}
  }'
```

### Reviews

```
POST   /v1/reviews   # UNIQUE(app_id, author_user_id, listing_id) — one review per author per listing
GET    /v1/reviews?subject_user_id=&cursor=&limit=
GET    /v1/users/:id/reputation  # reads Redis counter {avg_rating, review_count}
```

### Contacts / Offers

Bazaar does not store real messages in MVP. `contact` is an integrator-supplied handle returned only on `accepted`.

```
POST   /v1/contacts           # buyer initiates: {listing_id, buyer_user_id, message, offer_price_cents?}
GET    /v1/contacts?role=buyer|seller&status=open
PATCH  /v1/contacts/:id       # {status: accepted|declined|withdrawn}
GET    /v1/contacts/:id       # on accepted → includes resolved contact handle
```

Response on accept (`spec/examples/whatsapp-accept.json`):

```json
{
  "contact": { "type": "whatsapp", "handle": "+1415xxxxxx88" }
}
```

Once accepted, the integrator's native chat (WhatsApp, IG DM, etc.) takes over.

### Conventions

* Cursor pagination: `?cursor=opaque&limit=20` → `{ data: [...], next_cursor: "...", has_more: true }`
* Error shape:
  ```json
  { "error": { "code": "listing_not_found", "message": "...", "request_id": "req_9f1c..." } }
  ```
* Auth: `X-Bazaar-Key` (key_id) + `X-Bazaar-Timestamp` + `X-Bazaar-Signature` = HMAC-SHA256 over method + path + query + sha256(body) + timestamp, with a Redis nonce (single-use per signature, 300s window). Tenant isolation enforced by RLS `app_id = current_setting('bazaar.app_id')`.
* Idempotency: `Idempotency-Key: uuid` on all POSTs — stored in Redis with TTL.

---

## Data Model (MVP wedge)

Focused on high-velocity consumer categories: `furniture`, `electronics`, `apparel`, `baby-gear`. Excludes `real-estate`, `auto`, `ticketing` (regulatory complexity).

**listings**

| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | gen_random_uuid() |
| app_id | uuid | tenant, RLS key |
| seller_user_id | text | opaque, integrator-owned |
| title, description | text | full-text indexed |
| price_cents, currency | int, char(3) | integer money, no floats |
| category | enum | wedge above |
| condition | enum | `new / like-new / good / fair` |
| status | enum | `active / pending / sold / removed` |
| lat, lng, geohash | numeric, text | proximity search |
| image_keys | text[] | R2 object keys |
| search_vector | tsvector | generated, GIN |

**reviews**

| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| app_id | uuid | tenant |
| subject_user_id | text | who is reviewed (seller) |
| author_user_id | text | who wrote it |
| listing_id | uuid FK nullable | optional context |
| rating | int 1-5 | |
| body | text | |
| UNIQUE(app_id, author_user_id, listing_id) | | one review per author per listing |

Aggregate reputation `avg_rating`, `review_count` lives in Redis, updated on write — reads never scan the table.

**contacts (offer thread)**

| Column | Type | Notes |
|--------|------|-------|
| id | uuid PK | |
| app_id | uuid | |
| listing_id | uuid FK | |
| buyer_user_id, seller_user_id | text | opaque |
| offer_price_cents | int nullable | contact-only vs offer |
| status | enum | `open / accepted / declined / withdrawn` |
| message | text | initial contact message only |
| contact | jsonb | integrator callback (type + handle), returned only on accepted |

Indexes: `(app_id, category, status)`, `(app_id, geohash)`, `GIN(search_vector)`, `(app_id, subject_user_id)`.

---

## TypeScript SDK

Published as `@bazaar/sdk` (MVP). Generated from `/spec` — types, fetch client,
and zod validators all come from `pnpm -F @bazaar/sdk codegen`; only auth,
errors, retry, and the facade are hand-written.

```ts
import { BazaarClient } from '@bazaar/sdk';

const bazaar = new BazaarClient({
  baseUrl: 'https://api.usebazaar.dev',
  auth: {
    type: 'hmac',
    keyId: process.env.BAZAAR_KEY_ID!,
    secret: process.env.BAZAAR_SECRET!,
  },
});

// Seller lists — Idempotency-Key is generated if you don't pass one
const listing = await bazaar.listings.create({
  seller_user_id: 'wa_usr_88f2a1',
  title: 'Vitamix, barely used',
  price_cents: 18000,
  currency: 'USD',
  category: 'electronics',
  condition: 'like-new',
  lat: 37.75, lng: -122.43,
});

// Upload image — presign, PUT bytes, then attach (verified server-side)
const upload = await bazaar.listings.createImageUpload(listing.id, {
  acting_user_id: 'wa_usr_88f2a1',
  content_type: 'image/jpeg',
  content_length: imageFile.size,
});
await fetch(upload.upload_url, { method: 'PUT', body: imageFile });
await bazaar.listings.attachImage(listing.id, {
  acting_user_id: 'wa_usr_88f2a1',
  image_key: upload.image_key,
});

// Buyer browses — offset pagination
const { data, pagination } = await bazaar.listings.browse({
  category: 'baby-gear',
  q: 'stroller',
  lat: 37.75, lng: -122.43, radius_km: 5,
  limit: 20, offset: 0,
});

// Seller marks sold — creates the verified-interaction record
await bazaar.listings.markSold(listing.id, {
  acting_user_id: 'wa_usr_88f2a1',
  buyer_user_id: 'wa_usr_4b90cd',
});

// Buyer reviews the seller
await bazaar.reviews.create({
  author_user_id: 'wa_usr_4b90cd',
  listing_id: listing.id,
  rating: 5,
  body: 'Smooth handoff',
});

const aggregate = await bazaar.reviews.aggregate('wa_usr_88f2a1');
```

Every response is validated against the spec's zod schemas by default
(`validate: false` opts out). Errors are typed: `BazaarError` carries
`code`/`status`/`requestId`, with subclasses like `RateLimitedError`
(with `retryAfter`), `NotFoundError`, and `ConflictError`. Retries re-sign
with a fresh timestamp and keep `Idempotency-Key` stable, per the API's
single-use-signature contract.

Cold-start validation: SDK includes `examples/nextjs` that reaches first listing in < 60 minutes from `npm install`.

---

## Example: WhatsApp as Integrator

Why WhatsApp is a natural example:

* **Integrator owns identity** — WhatsApp authenticates users, passes Bazaar hashed opaque `user_id` (`wa_usr_...`). Bazaar never uses phone number as identity key.
* **WhatsApp owns messaging** — Bazaar routes no messages. On offer accept, Bazaar returns the seller's WhatsApp handle and WhatsApp's native chat takes over — matching the `contact` callback model.

**Flow: WhatsApp Local Marketplace tab in Communities**

1. **Maya lists**: `POST /v1/listings` with opaque `seller_user_id=wa_usr_88f2a1`.
2. **Maya uploads**: `POST /v1/listings/:id/images` → presigned R2 URL → direct upload.
3. **Leo browses**: `GET /v1/listings?lat=&lng=&radius_km=2&category=baby-gear` — location-first feed.
4. **Leo taps "Message seller"**: `POST /v1/contacts {buyer_user_id: wa_usr_4b90cd, ...}`.
5. **Maya accepts**: `PATCH /v1/contacts/:id {status: accepted}` → response includes `contact: {type: whatsapp, handle: +1...}`.
6. **Handoff**: WhatsApp opens native chat `wa.me/<handle>`. Trust via `GET /v1/users/wa_usr_88f2a1/reputation`.

See `spec/examples/whatsapp-accept.json` for exact accept payload.

---

## Trust & Safety (MVP → v1)

MVP: reviews + unique reviewer constraint + Redis aggregate reputation. No PII stored, no message content.

v1 adds:
* Stripe Connect for escrow / payouts
* Composite trust scoring (review + tenure + verification signals)
* Identity verification via integrator callbacks
* Opt-in cross-app inventory syndication
* Content scanning on upload (R2 + Lambda)
* Report / block API (`POST /v1/reports`)

---

## Testing

```bash
cd apps/api
pytest tests/unit -v
pytest tests/integration -v --db-url $BAZAAR_DATABASE_URL
pytest tests/rls -v  # verifies tenant isolation — app_id A cannot read B

# SDK + demo
pnpm -r test
pnpm -r typecheck
```

Negative tests that must stay green:
* RLS: cannot read listing from other `app_id`
* Money: float in `price_cents` rejected
* Review uniqueness: second review same (app_id, author, listing) → 409
* Contact: handle not exposed until `accepted`
* Pagination: cursor tampering → 400, not 500

---

## Roadmap

| Phase | Duration | Key Milestones |
|-------|----------|---------------|
| **Planning + Infra** | 1 week | Arch finalized, repo + CI live, Postgres + R2 + Redis, OpenAPI draft, first partner |
| **MVP** | ~1 month | Headless API (Listing/Review/Contact), TS SDK published, reference demo live, **<60 min onboarding validated** with cold tester |
| **v1** | ~2 months | Stripe Connect, composite trust + ID verification, cross-app syndication (opt-in), Swift/Kotlin SDKs, first paying integrator |

Out-of-scope for MVP: auth, payments, advanced search ranking, moderation dashboard (CLI + docs only).

---

## Competitive Positioning

| Product | Scale | Limitation |
|---------|-------|------------|
| Craigslist | Pioneer | No inventory, trust, or SDK |
| Shopify | 4.6M merchants, $236B GMV | B2C storefronts, not P2P; no social trust; not embeddable |
| OfferUp / Mercari | ~50M downloads each | Standalone apps, cold-start; no SDK to embed elsewhere |
| **Bazaar** | **Primitive** | **Embeddable full-stack P2P — inventory, search, trust, offers, media** |

---

## Contributing

This repo is currently internal but will be public under `metainternal-aai`. Until then:

1. Read `/spec` — it's the source of truth. Generate clients from it: `pnpm -F @bazaar/sdk codegen`.
2. API changes require migration file + RLS test.
3. Run `pnpm lint && pnpm typecheck && pytest` before PR.
4. Idempotency and RLS are not optional — PRs without tests are not merged.

---

## Training Data Flywheel (internal note)

Every integration generates:

* SDK integration patterns across frameworks (Next.js, Expo, etc.)
* API usage patterns & debugging sessions
* Trust calibration data (which signals predict safe transaction)
* Full-stack traces from real-world commerce scenarios
* Dev support Q&A that trains coding assistants

This flywheel is what lets us build better developer tools, docs, and eventually AI-assisted marketplace builders.

---

## License

TBD — target MIT / Apache-2.0 for SDK, BSL or AGPL for API (to be confirmed with OSPO). Internal fork until launch.

---

## Acknowledgements

Inspired by Stripe's primitive-led design, Supabase's RLS pattern, and the informal commerce already happening in every community app — WhatsApp, Discord, Telegram, Nextdoor. Bazaar is the layer those apps should have had.

`Go build something people want to trade.`
