#!/usr/bin/env node
// Asserts packages/sdk version tracks spec/openapi.yaml info.version
// major.minor. Run in CI after codegen.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const pkgDir = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(dirname(pkgDir));

const spec = readFileSync(join(repoRoot, "spec", "openapi.yaml"), "utf8");
const specVersion = spec.match(/^info:\n(?:.*\n)*? {2}version: (\d+)\.(\d+)\.(\d+)\s*$/m);
if (!specVersion) {
  console.error("check-version: could not find info.version in spec/openapi.yaml");
  process.exit(1);
}

const pkg = JSON.parse(readFileSync(join(pkgDir, "package.json"), "utf8"));
const sdkParts = pkg.version.split(".").map(Number);
const [major, minor] = [Number(specVersion[1]), Number(specVersion[2])];

if (sdkParts[0] !== major || sdkParts[1] !== minor) {
  console.error(
    `check-version: @bazaar/sdk version ${pkg.version} does not track spec ` +
      `version ${major}.${minor}.x — bump packages/sdk/package.json.`,
  );
  process.exit(1);
}

console.log(`check-version: @bazaar/sdk ${pkg.version} tracks spec ${major}.${minor}.x`);
