import { describe, expect, test } from "bun:test";
import rib from "../src/index";

// Activation is fail-hard in the harness: a malformed id or shape costs the
// whole server boot. Pin the contract here so a refactor can't drift it.
describe("rib shape", () => {
  test("default-exports the touchline rib", () => {
    expect(rib.id).toBe("touchline");
    expect(rib.displayName).toBe("Touchline");
  });

  test("id is lowercase kebab-case and matches the package suffix", async () => {
    expect(rib.id).toMatch(/^[a-z][a-z0-9-]*$/);
    const pkg = await Bun.file(new URL("../package.json", import.meta.url)).json();
    expect(pkg.name).toBe(`@keelson/rib-${rib.id}`);
  });

  test("every implemented hook is a function", () => {
    const hooks = [
      "registerTools",
      "composeBundle",
      "contributeWorkflows",
      "contributeDocs",
      "contributePolicies",
      "onAction",
      "onRunEvent",
      "authStatus",
      "dispose",
    ] as const;
    for (const hook of hooks) {
      const value = (rib as unknown as Record<string, unknown>)[hook];
      if (value !== undefined) expect(typeof value).toBe("function");
    }
  });
});
