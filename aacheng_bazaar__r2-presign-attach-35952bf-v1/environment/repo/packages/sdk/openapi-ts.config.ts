import { defineConfig } from "@hey-api/openapi-ts";

export default defineConfig({
  input: "../../spec/openapi.yaml",
  output: {
    path: "src/gen",
    indexFile: false,
  },
  plugins: [
    {
      name: "@hey-api/typescript",
      enums: "typescript",
    },
    {
      name: "@hey-api/sdk",
    },
    {
      name: "@hey-api/client-fetch",
      throwOnError: false,
    },
    {
      name: "zod",
      metadata: true,
    },
  ],
});
