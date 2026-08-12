// BazaarClient — the facade over the generated operation functions.
// Namespaces mirror the spec's resource layout; every method routes through
// the generated client configured with the signing fetch, unwraps the result
// to plain data, and throws typed errors from the API's error envelope.

import type { BazaarAuth } from "./auth.js";
import { errorFromResponse } from "./errors.js";
import { createClient, createConfig, type Client } from "./gen/client/index.js";
import {
  attachImage,
  browseListings,
  createApp,
  createAppKey,
  createImageUpload,
  createListing,
  createReview,
  getListing,
  getReviewAggregate,
  healthz,
  listReviews,
  markListingSold,
  removeListing,
  updateListing,
} from "./gen/sdk.gen.js";
import type {
  AppCreateRequest,
  BrowseListingsData,
  ImageAttachRequest,
  ImageUploadRequest,
  ListingCreateRequest,
  ListingPatchRequest,
  ListReviewsData,
  MarkSoldRequest,
  RemoveRequest,
  ReviewCreateRequest,
  SubjectUserId,
} from "./gen/types.gen.js";
import { createSigningFetch } from "./http.js";
import { retryAfterToSeconds } from "./http.js";
import { validateResponse, type OperationName } from "./validation.js";

export interface BazaarClientOptions {
  baseUrl: string;
  auth: BazaarAuth;
  /** Underlying fetch implementation; defaults to globalThis.fetch. */
  fetch?: typeof fetch | undefined;
  /** Validate every response against the spec's zod schemas. Default true. */
  validate?: boolean | undefined;
  /** Retries on 429 / network errors. Default 2. */
  maxRetries?: number | undefined;
}

interface OpResult<T> {
  data: T | undefined;
  error: unknown;
  request?: Request | undefined;
  response?: Response | undefined;
}

export interface RequestOptions {
  /** UUID; generated when omitted on operations that require it. */
  idempotencyKey?: string | undefined;
}

export class BazaarClient {
  private readonly client: Client;
  private readonly validateResponses: boolean;

  readonly apps = {
    create: (body: AppCreateRequest, opts?: RequestOptions) =>
      this.invoke("createApp", createApp({ client: this.client, body, headers: idempotencyHeader(opts) })),
    createKey: (appId: string, opts?: RequestOptions) =>
      this.invoke(
        "createAppKey",
        createAppKey({ client: this.client, path: { app_id: appId }, headers: idempotencyHeader(opts) }),
      ),
  };

  readonly listings = {
    create: (body: ListingCreateRequest, opts?: RequestOptions) =>
      // Idempotency-Key is REQUIRED by the spec on POST /v1/listings.
      this.invoke(
        "createListing",
        createListing({
          client: this.client,
          body,
          headers: { "Idempotency-Key": opts?.idempotencyKey ?? crypto.randomUUID() },
        }),
      ),
    browse: (query?: BrowseListingsData["query"]) =>
      this.invoke("browseListings", browseListings({ client: this.client, query })),
    get: (listingId: string) =>
      this.invoke("getListing", getListing({ client: this.client, path: { listing_id: listingId } })),
    update: (listingId: string, body: ListingPatchRequest, opts?: RequestOptions) =>
      this.invoke(
        "updateListing",
        updateListing({ client: this.client, path: { listing_id: listingId }, body, headers: idempotencyHeader(opts) }),
      ),
    createImageUpload: (listingId: string, body: ImageUploadRequest, opts?: RequestOptions) =>
      this.invoke(
        "createImageUpload",
        createImageUpload({
          client: this.client,
          path: { listing_id: listingId },
          body,
          headers: idempotencyHeader(opts),
        }),
      ),
    attachImage: (listingId: string, body: ImageAttachRequest, opts?: RequestOptions) =>
      this.invoke(
        "attachImage",
        attachImage({ client: this.client, path: { listing_id: listingId }, body, headers: idempotencyHeader(opts) }),
      ),
    markSold: (listingId: string, body: MarkSoldRequest, opts?: RequestOptions) =>
      this.invoke(
        "markListingSold",
        markListingSold({
          client: this.client,
          path: { listing_id: listingId },
          body,
          headers: idempotencyHeader(opts),
        }),
      ),
    remove: (listingId: string, body: RemoveRequest, opts?: RequestOptions) =>
      this.invoke(
        "removeListing",
        removeListing({ client: this.client, path: { listing_id: listingId }, body, headers: idempotencyHeader(opts) }),
      ),
  };

  readonly reviews = {
    create: (body: ReviewCreateRequest, opts?: RequestOptions) =>
      this.invoke("createReview", createReview({ client: this.client, body, headers: idempotencyHeader(opts) })),
    list: (query: ListReviewsData["query"]) => this.invoke("listReviews", listReviews({ client: this.client, query })),
    aggregate: (subjectUserId: SubjectUserId) =>
      this.invoke("getReviewAggregate", getReviewAggregate({ client: this.client, query: { subject_user_id: subjectUserId } })),
  };

  constructor(options: BazaarClientOptions) {
    this.validateResponses = options.validate ?? true;
    this.client = createClient(
      createConfig({
        baseUrl: options.baseUrl,
        fetch: createSigningFetch(options.auth, {
          fetchImpl: options.fetch,
          maxRetries: options.maxRetries,
        }),
      }),
    );
  }

  healthz() {
    return this.invoke("healthz", healthz({ client: this.client }));
  }

  private async invoke<T>(operation: OperationName, promise: Promise<OpResult<T>>): Promise<T> {
    const result = await promise;
    if (result.error !== undefined) {
      // The fetch client always attaches the Response on an error result;
      // the fallback status only guards against a future transport that
      // doesn't (and turns the throw into a typed 500 rather than a crash).
      throw errorFromResponse(result.response?.status ?? 500, result.error, {
        retryAfterSeconds: retryAfterToSeconds(result.response?.headers.get("Retry-After") ?? null),
      });
    }
    if (this.validateResponses) {
      validateResponse(operation, result.data);
    }
    return result.data as T;
  }
}

const MAX_IDEM_KEY_LEN = 64;
const IDEM_KEY_RE = /^[A-Za-z0-9._-]+$/;

function idempotencyHeader(opts?: RequestOptions): { "Idempotency-Key"?: string } {
  if (!opts?.idempotencyKey) return {};
  const k = opts.idempotencyKey.trim();
  if (k.length === 0 || k.length > MAX_IDEM_KEY_LEN || !IDEM_KEY_RE.test(k)) {
    throw new Error(`invalid Idempotency-Key: must match ${IDEM_KEY_RE} and <= ${MAX_IDEM_KEY_LEN}`);
  }
  return { "Idempotency-Key": k };
}
