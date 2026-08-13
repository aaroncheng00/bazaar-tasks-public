// Shared helpers for the contract suite. The suite runs against a live API
// (docker compose postgres + redis, alembic migrated, uvicorn up) with the
// seeded dev key; CI's `contract` job provides that environment.

import { BazaarClient, type BazaarClientOptions } from "../../src/index.js";

export const BASE_URL = process.env.BAZAAR_BASE_URL ?? "http://localhost:8000";
export const KEY_ID = process.env.BAZAAR_KEY_ID ?? "bzk_dev";
export const SECRET = process.env.BAZAAR_SECRET ?? "bzs_dev_secret";

export function makeClient(opts?: Partial<BazaarClientOptions> & { secret?: string }): BazaarClient {
  const { secret, ...rest } = opts ?? {};
  return new BazaarClient({
    baseUrl: BASE_URL,
    auth: { type: "hmac", keyId: KEY_ID, secret: secret ?? SECRET },
    // No retries in the contract suite: a 429 would otherwise sleep for the
    // full Retry-After window.
    maxRetries: 0,
    ...rest,
  });
}
