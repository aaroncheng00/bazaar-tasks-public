import { describe, expect, it } from "vitest";

import {
  BazaarAuthError,
  BazaarError,
  ConflictError,
  errorFromResponse,
  ForbiddenError,
  InvalidSignatureError,
  NotFoundError,
  RateLimitedError,
  SellerOnlyError,
  ValidationFailedError,
} from "../../src/errors.js";

describe("errorFromResponse", () => {
  it("maps known codes to their subclass with envelope fields", () => {
    const err = errorFromResponse(404, {
      error: { code: "listing_not_found", message: "no such listing", request_id: "req_1" },
    });
    expect(err).toBeInstanceOf(NotFoundError);
    expect(err).toBeInstanceOf(BazaarError);
    expect(err.code).toBe("listing_not_found");
    expect(err.message).toBe("no such listing");
    expect(err.status).toBe(404);
    expect(err.requestId).toBe("req_1");
  });

  it("maps the granular auth codes to BazaarAuthError", () => {
    for (const code of [
      "missing_auth_headers",
      "unknown_key",
      "malformed_timestamp",
      "stale_timestamp",
      "replay_detected",
      "unauthenticated",
    ]) {
      const err = errorFromResponse(401, { error: { code, message: code, request_id: "req_2" } });
      expect(err).toBeInstanceOf(BazaarAuthError);
      expect(err).not.toBeInstanceOf(InvalidSignatureError);
      expect(err.code).toBe(code);
    }
  });

  it("maps invalid_signature to InvalidSignatureError, an auth error", () => {
    const err = errorFromResponse(401, {
      error: { code: "invalid_signature", message: "invalid signature", request_id: "req_3" },
    });
    expect(err).toBeInstanceOf(InvalidSignatureError);
    expect(err).toBeInstanceOf(BazaarAuthError);
  });

  it("maps seller_only to SellerOnlyError, a forbidden error", () => {
    const err = errorFromResponse(403, {
      error: { code: "seller_only", message: "only the seller may do that", request_id: "req_4" },
    });
    expect(err).toBeInstanceOf(SellerOnlyError);
    expect(err).toBeInstanceOf(ForbiddenError);
  });

  it("maps all split 409 codes to ConflictError", () => {
    for (const code of ["conflict", "review_exists", "listing_already_sold", "idempotency_mismatch", "request_in_flight"]) {
      const err = errorFromResponse(409, { error: { code, message: code, request_id: "req_5" } });
      expect(err).toBeInstanceOf(ConflictError);
      expect(err.code).toBe(code);
    }
  });

  it("maps validation_failed to ValidationFailedError", () => {
    const err = errorFromResponse(422, {
      error: { code: "validation_failed", message: "price_cents: must be an integer", request_id: "req_6" },
    });
    expect(err).toBeInstanceOf(ValidationFailedError);
  });

  it("carries Retry-After seconds on RateLimitedError", () => {
    const err = errorFromResponse(
      429,
      { error: { code: "rate_limited", message: "slow down", request_id: "req_7" } },
      { retryAfterSeconds: 42 },
    );
    expect(err).toBeInstanceOf(RateLimitedError);
    expect((err as RateLimitedError).retryAfter).toBe(42);
  });

  it("unknown codes degrade to the base class", () => {
    const err = errorFromResponse(500, {
      error: { code: "internal_error", message: "boom", request_id: "req_8" },
    });
    expect(err).toBeInstanceOf(BazaarError);
    expect(err.constructor).toBe(BazaarError);
    expect(err.code).toBe("internal_error");
  });

  it("malformed bodies degrade to the base class with a status fallback", () => {
    for (const body of [null, undefined, {}, { error: {} }, "not json", { error: { code: 7 } }]) {
      const err = errorFromResponse(502, body);
      expect(err).toBeInstanceOf(BazaarError);
      expect(err.code).toBe("error");
      expect(err.status).toBe(502);
      expect(err.message).toBe("HTTP 502");
      expect(err.requestId).toBeUndefined();
    }
  });
});
