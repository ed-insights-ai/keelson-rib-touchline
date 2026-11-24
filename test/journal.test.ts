// site/journal: the Gemini model command, the changed-conference rule and the
// cost summary behind the cloud journal (.github/workflows/journal.yml).

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  costOf,
  modelFrom,
  replyText,
  requestBody,
  retryable,
  usageOf,
} from "../site/journal/gemini.ts";
import { onlyKeys, sameMoment, staleKeys } from "../site/journal/stale.ts";
import { type Call, markdown, summarize } from "../site/journal/usage.ts";

const GEMINI = join(import.meta.dir, "..", "site", "journal", "gemini.ts");

describe("gemini.ts", () => {
  test("Flex is asked for at the top of the body, beside the thinking level", () => {
    const body = requestBody("hi", "flex", "medium") as Record<string, unknown>;
    expect(body.service_tier).toBe("flex");
    expect(body.generationConfig).toEqual({
      thinkingConfig: { thinkingLevel: "medium" },
      maxOutputTokens: 65536,
    });
    expect("service_tier" in (requestBody("hi", "standard", "low") as object)).toBe(false);
  });

  test("the reply's text leaves the thoughts out", () => {
    const reply = {
      candidates: [{ content: { parts: [{ text: "pondering", thought: true }, { text: "{}" }] } }],
    };
    expect(replyText(reply)).toBe("{}");
    expect(replyText({})).toBe("");
  });

  test("thinking bills as output and cached input at the cached rate", () => {
    const u = usageOf({
      usageMetadata: {
        promptTokenCount: 1_000_000,
        cachedContentTokenCount: 200_000,
        candidatesTokenCount: 100_000,
        thoughtsTokenCount: 100_000,
      },
    });
    // 0.8M x $1.50 + 0.2M x $0.075 + 0.2M x $7.50
    expect(costOf("gemini-4-neon", "flex", u)).toBeCloseTo(1.2 + 0.015 + 1.5, 6);
    expect(costOf("gemini-4-neon", "standard", u)).toBeCloseTo(2.4 + 0.03 + 3, 6);
    expect(costOf("some-other-model", "flex", u)).toBeNull();
  });

  test("the model comes from --model, else the default", () => {
    expect(modelFrom(["-p", "--model", "gemini-4-neon"], "x")).toBe("gemini-4-neon");
    expect(modelFrom(["-p"], "gemini-4-neon")).toBe("gemini-4-neon");
    expect(modelFrom(["-p", "--model", " "], "fallback")).toBe("fallback");
  });

  test("capacity and rate answers are retried, a bad request is not", () => {
    expect([429, 500, 503, 504].every(retryable)).toBe(true);
    expect([400, 401, 403, 404].some(retryable)).toBe(false);
  });
});

describe("gemini.ts as the journal's model command", () => {
  let server: ReturnType<typeof Bun.serve>;
  let calls = 0;
  const dir = mkdtempSync(join(tmpdir(), "journal-gemini-"));
  const seen: Record<string, unknown>[] = [];

  beforeAll(() => {
    server = Bun.serve({
      port: 0,
      async fetch(req) {
        calls++;
        seen.push((await req.json()) as Record<string, unknown>);
        if (calls === 1) return new Response("at capacity", { status: 503 });
        return Response.json({
          candidates: [
            {
              content: { parts: [{ text: "x", thought: true }, { text: '{"ok":true}' }] },
              finishReason: "STOP",
            },
          ],
          usageMetadata: { promptTokenCount: 10, candidatesTokenCount: 4, thoughtsTokenCount: 6 },
        });
      },
    });
  });

  afterAll(() => {
    server.stop(true);
    rmSync(dir, { recursive: true, force: true });
  });

  test("reads stdin, retries a 503, prints the answer and logs the call", async () => {
    const log = join(dir, "usage.jsonl");
    const child = Bun.spawn([GEMINI, "-p", "--model", "gemini-4-neon"], {
      stdin: new Blob(["write the journal"]),
      stdout: "pipe",
      stderr: "pipe",
      env: {
        ...process.env,
        GEMINI_API_KEY: "test-key",
        GEMINI_API_BASE: server.url.origin,
        JOURNAL_RETRY_WAITS: "0",
        JOURNAL_USAGE_LOG: log,
        JOURNAL_SCOPE: "d2 men",
      },
    });
    const [out, code] = await Promise.all([new Response(child.stdout).text(), child.exited]);
    expect(code).toBe(0);
    expect(out).toBe('{"ok":true}');
    expect(seen[0]?.service_tier).toBe("flex");
    const line = JSON.parse(readFileSync(log, "utf8").trim());
    expect(line).toMatchObject({
      scope: "d2 men",
      model: "gemini-4-neon",
      tier: "flex",
      attempts: 2,
      prompt: 10,
      output: 4,
      thoughts: 6,
    });
    expect(line.cost_usd).toBeCloseTo((10 * 1.5 + 10 * 7.5) / 1e6, 12);
  });
});

describe("stale.ts", () => {
  const dir = mkdtempSync(join(tmpdir(), "journal-stale-"));
  afterAll(() => rmSync(dir, { recursive: true, force: true }));

  test("a conference is stale when its journal names another collect, or is missing", () => {
    writeFileSync(
      join(dir, "journal-2026-men-gac.json"),
      JSON.stringify({ data_collected_at: "2026-11-20T12:32:34+00:00" }),
    );
    writeFileSync(
      join(dir, "journal-2026-men-psac.json"),
      JSON.stringify({ data_collected_at: "2026-11-20T12:00:00Z" }),
    );
    writeFileSync(join(dir, "journal-2026-men-cc.json"), "not json");
    const seasons = [
      { key: "gac", file: "journal-2026-men-gac.json", collectedAt: "2026-11-20T12:32:34Z" },
      { key: "psac", file: "journal-2026-men-psac.json", collectedAt: "2026-11-24T14:30:00Z" },
      { key: "cc", file: "journal-2026-men-cc.json", collectedAt: "2026-11-24T14:30:00Z" },
      { key: "nsic", file: "journal-2026-men-nsic.json", collectedAt: "2026-11-24T14:30:00Z" },
    ];
    expect(staleKeys(seasons, dir)).toEqual(["psac", "cc", "nsic"]);
  });

  test("the same instant spelled two ways is the same collect", () => {
    expect(sameMoment("2026-11-20T12:32:34+00:00", "2026-11-20T12:32:34Z")).toBe(true);
    expect(sameMoment("2026-11-20T12:32:34Z", "2026-11-20T12:32:35Z")).toBe(false);
  });

  test("--only keeps the build's own conferences, in its order", () => {
    const seasons = ["gac", "psac", "cc"].map((key) => ({ key, file: "", collectedAt: "" }));
    expect(onlyKeys(seasons, "cc, GAC,a10")).toEqual(["gac", "cc"]);
    expect(onlyKeys(seasons, "")).toEqual([]);
  });
});

describe("usage.ts", () => {
  const call = (scope: string, over: Partial<Call> = {}): Call => ({
    scope,
    model: "gemini-4-neon",
    tier: "flex",
    prompt: 1000,
    cached: 0,
    output: 100,
    thoughts: 200,
    attempts: 1,
    cost_usd: 0.01,
    ...over,
  });

  test("sums per build and in total, and names retries and fallbacks", () => {
    const calls = [
      call("d2 men"),
      call("d2 men", { attempts: 3 }),
      call("d1 women", { tier: "standard", cost_usd: 0.02 }),
    ];
    const { rows, total } = summarize(calls);
    expect(rows.map((r) => [r.scope, r.calls])).toEqual([
      ["d2 men", 2],
      ["d1 women", 1],
    ]);
    expect(total.cost).toBeCloseTo(0.04, 10);
    expect(total.retries).toBe(2);
    const md = markdown(calls);
    expect(md).toContain("| **total** | 3 | 3,000 | 0 | 300 | 600 | **$0.04** |");
    expect(md).toContain("2 retried request(s).");
    expect(md).toContain("1 call(s) fell back to the Standard tier.");
  });

  test("a run with no calls says so", () => {
    expect(markdown([])).toBe("No model calls this run.\n");
  });
});
