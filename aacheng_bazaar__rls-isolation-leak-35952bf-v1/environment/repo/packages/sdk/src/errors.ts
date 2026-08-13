// Typed error hierarchy mirroring the API's error code registry
// (apps/api/src/bazaar_api/errors.py). The `code` field is the public
// contract — integrators branch on it, never on message prose.

export class BazaarError extends Error {
  readonly code: string;
  readonly status: number;
  readonly requestId: string | undefined;

  constructor(code: string, message: string, status: number, requestId?: string | undefined) {
    super(message);
    this.name = new.target.name;
    this.code = code;
    this.status = status;
    this.requestId = requestId;
  }
}

// 401 family — the six granular auth codes plus the status fallback.
export class BazaarAuthError extends BazaarError {}
export class InvalidSignatureError extends BazaarAuthError {}

// 403 family.
export class ForbiddenError extends BazaarError {}
export class SellerOnlyError extends ForbiddenError {}

export class NotFoundError extends BazaarError {}
export class ConflictError extends BazaarError {}
export class ValidationFailedError extends BazaarError {}

export class RateLimitedError extends BazaarError {
  /** Seconds from the Retry-After header, when the server sent it. */
  readonly retryAfter: number | undefined;

  constructor(code: string, message: string, status: number, requestId?: string | undefined, retryAfter?: number | undefined) {
    super(code, message, status, requestId);
    this.retryAfter = retryAfter;
  }
}

// Fetch-level failure after retries were exhausted — no envelope exists.
export class BazaarNetworkError extends BazaarError {
  constructor(message: string, options?: { cause?: unknown }) {
    super("network_error", message, 0);
    if (options && "cause" in options) {
      this.cause = options.cause;
    }
  }
}

const CODE_TO_CLASS: Record<string, typeof BazaarError> = {
  missing_auth_headers: BazaarAuthError,
  unknown_key: BazaarAuthError,
  malformed_timestamp: BazaarAuthError,
  stale_timestamp: BazaarAuthError,
  replay_detected: BazaarAuthError,
  unauthenticated: BazaarAuthError,
  invalid_signature: InvalidSignatureError,
  forbidden: ForbiddenError,
  review_not_eligible: ForbiddenError,
  seller_only: SellerOnlyError,
  not_found: NotFoundError,
  listing_not_found: NotFoundError,
  conflict: ConflictError,
  review_exists: ConflictError,
  listing_already_sold: ConflictError,
  idempotency_mismatch: ConflictError,
  request_in_flight: ConflictError,
  validation_failed: ValidationFailedError,
};

interface EnvelopeShape {
  error?: { code?: unknown; message?: unknown; request_id?: unknown };
}

// Maps a response to a typed error. Unknown codes and malformed bodies
// degrade to the base class rather than throwing a parse error.
export function errorFromResponse(
  status: number,
  body: unknown,
  opts?: { retryAfterSeconds?: number | undefined },
): BazaarError {
  const envelope = (body as EnvelopeShape | null)?.error;
  const code = typeof envelope?.code === "string" && envelope.code ? envelope.code : "error";
  const message = typeof envelope?.message === "string" && envelope.message ? envelope.message : `HTTP ${status}`;
  const requestId = typeof envelope?.request_id === "string" ? envelope.request_id : undefined;

  if (code === "rate_limited") {
    return new RateLimitedError(code, message, status, requestId, opts?.retryAfterSeconds);
  }
  const Klass = CODE_TO_CLASS[code] ?? BazaarError;
  return new Klass(code, message, status, requestId);
}
