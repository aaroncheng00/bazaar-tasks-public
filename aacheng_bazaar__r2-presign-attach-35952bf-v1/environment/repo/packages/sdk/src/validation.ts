// Opt-in response validation against the spec-derived zod schemas
// (src/gen/zod.gen.ts). On by default: a response that no longer matches the
// spec is drift, and it should fail loudly at the SDK boundary instead of
// surfacing as a downstream undefined-field bug.

import { z } from "zod";

import { BazaarError } from "./errors.js";
import {
  zAttachImageResponse,
  zBrowseListingsResponse,
  zCreateAppKeyResponse,
  zCreateAppResponse,
  zCreateImageUploadResponse,
  zCreateListingResponse,
  zCreateReviewResponse,
  zGetListingResponse,
  zGetReviewAggregateResponse,
  zHealthzResponse,
  zListReviewsResponse,
  zMarkListingSoldResponse,
  zRemoveListingResponse,
  zUpdateListingResponse,
} from "./gen/zod.gen.js";

export class BazaarValidationError extends BazaarError {
  readonly operation: string;
  readonly issues: z.ZodIssue[];

  constructor(operation: string, error: z.ZodError) {
    super(
      "response_validation_failed",
      `response from ${operation} does not match the spec: ${error.issues
        .map((issue) => `${issue.path.join(".") || "(root)"}: ${issue.message}`)
        .join("; ")}`,
      0,
    );
    this.operation = operation;
    this.issues = error.issues;
  }
}

const RESPONSE_SCHEMAS = {
  healthz: zHealthzResponse,
  createApp: zCreateAppResponse,
  createAppKey: zCreateAppKeyResponse,
  browseListings: zBrowseListingsResponse,
  createListing: zCreateListingResponse,
  getListing: zGetListingResponse,
  updateListing: zUpdateListingResponse,
  createImageUpload: zCreateImageUploadResponse,
  attachImage: zAttachImageResponse,
  markListingSold: zMarkListingSoldResponse,
  removeListing: zRemoveListingResponse,
  listReviews: zListReviewsResponse,
  createReview: zCreateReviewResponse,
  getReviewAggregate: zGetReviewAggregateResponse,
} as const;

export type OperationName = keyof typeof RESPONSE_SCHEMAS;

export function validateResponse(operation: OperationName, data: unknown): void {
  const schema = RESPONSE_SCHEMAS[operation];
  const result = schema.safeParse(data);
  if (!result.success) {
    throw new BazaarValidationError(operation, result.error);
  }
}
