import { describe, expect, it } from "vitest";

import { signHeaders, signRequest } from "../../src/auth.js";

const encoder = new TextEncoder();

// Generated from the API's reference implementation
// (apps/api/src/bazaar_api/middleware/auth_hmac.py canonical_request +
// hmac.new(secret, …, sha256).hexdigest()) with secret "bzs_dev_secret".
// Regenerate with the Python snippet in the commit message / plan if the
// canonical form ever changes — these vectors are the byte-level compat proof.
const SECRET = "bzs_dev_secret";

const VECTORS: Array<{
  name: string;
  method: string;
  path: string;
  query: string;
  timestamp: string;
  body: string;
  expectedSignature: string;
}> = [
  {
    name: "GET with multi-param raw query, empty body",
    method: "GET",
    path: "/v1/listings",
    query: "category=baby-gear&condition=like-new&limit=20&offset=0",
    timestamp: "1785960000",
    body: "",
    expectedSignature: "106dc25ee6746f4617085bbaa50ff18920285ff725ac88dfa0bb622c3a27fadd",
  },
  {
    name: "POST createListing with JSON body",
    method: "POST",
    path: "/v1/listings",
    query: "",
    timestamp: "1785960001",
    body: '{"title":"Stroller","price_cents":4500,"currency":"USD","category":"baby-gear","condition":"like-new","seller_id":"u_1","lat":37.44,"lng":-122.14}',
    expectedSignature: "b7febdfe3f029c10844589b3bd7b987e71d38bd31317e6b8c1058d32b43fa3dc",
  },
  {
    name: "PATCH with body, no query",
    method: "PATCH",
    path: "/v1/listings/lst_123",
    query: "",
    timestamp: "1785960002",
    body: '{"price_cents":3900}',
    expectedSignature: "63d46a194948d09cb796123afc0e919817dc751b086cc0cbef90fbee58586e05",
  },
  {
    name: "POST action path, empty body",
    method: "POST",
    path: "/v1/listings/lst_123/mark_sold",
    query: "",
    timestamp: "1785960003",
    body: "",
    expectedSignature: "a96662738dadd173fbfdcadaad99efac5350ba19d73f3c5a3c6b8a00a8f881c8",
  },
  {
    name: "query with reserved chars signed exactly as sent",
    method: "GET",
    path: "/v1/listings",
    query: "q=kid%27s+bike&offset=40",
    timestamp: "1785960004",
    body: "",
    expectedSignature: "771ff1444a9d2035bc29f6fda56e4353f577f1102a8f890d8187332bbcfb18b3",
  },
];

describe("signRequest (golden vectors from the Python middleware)", () => {
  for (const v of VECTORS) {
    it(v.name, async () => {
      const signature = await signRequest(SECRET, v.method, v.path, v.query, v.timestamp, encoder.encode(v.body));
      expect(signature).toBe(v.expectedSignature);
    });
  }
});

describe("signHeaders", () => {
  const auth = { type: "hmac" as const, keyId: "bzk_dev", secret: SECRET };

  it("produces the three auth headers with the given timestamp", async () => {
    const headers = await signHeaders(auth, {
      method: "get",
      path: "/v1/listings",
      rawQuery: "limit=20",
      body: new Uint8Array(),
      timestamp: "1785960000",
    });
    expect(headers["X-Bazaar-Key"]).toBe("bzk_dev");
    expect(headers["X-Bazaar-Timestamp"]).toBe("1785960000");
    expect(headers["X-Bazaar-Signature"]).toMatch(/^[0-9a-f]{64}$/);
  });

  it("uppercases the method before signing", async () => {
    const lower = await signRequest(SECRET, "get", "/v1/listings", "", "1785960000", new Uint8Array());
    const upper = await signRequest(SECRET, "GET", "/v1/listings", "", "1785960000", new Uint8Array());
    const viaHeaders = await signHeaders(auth, {
      method: "get",
      path: "/v1/listings",
      rawQuery: "",
      body: new Uint8Array(),
      timestamp: "1785960000",
    });
    expect(viaHeaders["X-Bazaar-Signature"]).toBe(upper);
    expect(viaHeaders["X-Bazaar-Signature"]).not.toBe(lower);
  });

  it("defaults the timestamp to the current unix time", async () => {
    const before = Math.floor(Date.now() / 1000);
    const headers = await signHeaders(auth, {
      method: "GET",
      path: "/healthz",
      rawQuery: "",
      body: new Uint8Array(),
    });
    const ts = Number(headers["X-Bazaar-Timestamp"]);
    expect(ts).toBeGreaterThanOrEqual(before);
    expect(ts).toBeLessThanOrEqual(Math.floor(Date.now() / 1000));
  });
});
