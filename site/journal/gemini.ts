#!/usr/bin/env bun
// The journal's model command for Gemini (touchline-ui scripts/journal/cli.ts
// runs it with --command): reads the prompt on stdin, writes the reply on
// stdout, takes the same `-p [--model <id>]` argv as `claude -p`.
//
// Each call appends one line of token use and estimated cost to the file named
// by JOURNAL_USAGE_LOG (site/journal/usage.ts sums them). Environment:
//   GEMINI_API_KEY             required
//   JOURNAL_MODEL              when --model is absent (default gemini-4-neon)
//   JOURNAL_SERVICE_TIER       flex (default) or standard
//   JOURNAL_THINKING           low, medium (default), high or xhigh
//   JOURNAL_FALLBACK_STANDARD  "true": once Flex has refused every retry, ask
//                              Standard once rather than fail (default true)
//   JOURNAL_SCOPE              a label for the usage line (the build)
//   GEMINI_API_BASE            the API root, for tests

import { appendFileSync } from "node:fs";

export type Tier = "flex" | "standard";

/** USD per million tokens, Gemini 4 Neon, from Google's Neon page (Nov 2026).
 *  Thinking tokens bill as output. Estimates: the bill is the record. */
export const PRICES: Record<
  string,
  Record<Tier, { input: number; cached: number; output: number }>
> = {
  "gemini-4-neon": {
    flex: { input: 1.5, cached: 0.075, output: 7.5 },
    standard: { input: 3, cached: 0.15, output: 15 },
  },
};

export interface Usage {
  prompt: number;
  cached: number;
  output: number;
  thoughts: number;
}

export function requestBody(prompt: string, tier: Tier, thinking: string): unknown {
  return {
    contents: [{ role: "user", parts: [{ text: prompt }] }],
    generationConfig: { thinkingConfig: { thinkingLevel: thinking }, maxOutputTokens: 65536 },
    ...(tier === "flex" ? { service_tier: "flex" } : {}),
  };
}

interface Part {
  text?: string;
  thought?: boolean;
}

interface Reply {
  candidates?: { content?: { parts?: Part[] }; finishReason?: string }[];
  usageMetadata?: Record<string, number | undefined>;
}

/** The answer's text: every part that is not a thought, in order. */
export function replyText(reply: Reply): string {
  const parts = reply.candidates?.[0]?.content?.parts ?? [];
  return parts
    .filter((p) => !p.thought && typeof p.text === "string")
    .map((p) => p.text)
    .join("");
}

export function usageOf(reply: Reply): Usage {
  const u = reply.usageMetadata ?? {};
  return {
    prompt: u.promptTokenCount ?? 0,
    cached: u.cachedContentTokenCount ?? 0,
    output: u.candidatesTokenCount ?? 0,
    thoughts: u.thoughtsTokenCount ?? 0,
  };
}

/** Estimated USD for one call. Cached prompt tokens bill at the cached rate. */
export function costOf(model: string, tier: Tier, u: Usage): number | null {
  const p = PRICES[model]?.[tier];
  if (!p) return null;
  const fresh = Math.max(u.prompt - u.cached, 0);
  return (fresh * p.input + u.cached * p.cached + (u.output + u.thoughts) * p.output) / 1e6;
}

/** Statuses worth asking again: capacity (503), rate (429), and the server's own trouble. */
export const retryable = (status: number): boolean =>
  status === 429 || status === 500 || status === 503 || status === 504;

export function modelFrom(argv: readonly string[], fallback: string): string {
  const i = argv.indexOf("--model");
  const named = i >= 0 ? argv[i + 1]?.trim() : undefined;
  return named || fallback;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

interface Asked {
  reply: Reply;
  tier: Tier;
  attempts: number;
}

async function ask(prompt: string, model: string, tier: Tier, thinking: string): Promise<Asked> {
  const key = process.env.GEMINI_API_KEY?.trim();
  if (!key) throw new Error("GEMINI_API_KEY is not set");
  const base = process.env.GEMINI_API_BASE ?? "https://generativelanguage.googleapis.com";
  const url = `${base}/v1beta/models/${model}:generateContent`;
  const waits = (process.env.JOURNAL_RETRY_WAITS ?? "10,30,90,180").split(",").map(Number);
  const fallback = (process.env.JOURNAL_FALLBACK_STANDARD ?? "true") === "true";
  let attempts = 0;
  let last = "";
  const tiers: Tier[] = tier === "flex" && fallback ? ["flex", "standard"] : [tier];
  for (const t of tiers) {
    const tries = t === tier ? waits.length + 1 : 1;
    for (let n = 0; n < tries; n++) {
      if (n > 0) await sleep((waits[n - 1] ?? 60) * 1000);
      attempts++;
      let res: Response;
      try {
        res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", "x-goog-api-key": key },
          body: JSON.stringify(requestBody(prompt, t, thinking)),
          signal: AbortSignal.timeout(15 * 60 * 1000),
        });
      } catch (err) {
        last = `request failed: ${(err as Error).message}`;
        continue;
      }
      if (res.ok) return { reply: (await res.json()) as Reply, tier: t, attempts };
      last = `HTTP ${res.status}: ${(await res.text()).slice(0, 400)}`;
      if (!retryable(res.status)) throw new Error(last);
    }
    if (t === "flex" && tiers.length > 1) {
      process.stderr.write(`flex refused every try (${last}); asking standard once\n`);
    }
  }
  throw new Error(last);
}

async function main(): Promise<number> {
  const model = modelFrom(process.argv.slice(2), process.env.JOURNAL_MODEL || "gemini-4-neon");
  const tier: Tier = process.env.JOURNAL_SERVICE_TIER === "standard" ? "standard" : "flex";
  const thinking = process.env.JOURNAL_THINKING || "medium";
  const prompt = await Bun.stdin.text();
  const started = performance.now();
  const asked = await ask(prompt, model, tier, thinking);
  const usage = usageOf(asked.reply);
  const text = replyText(asked.reply);
  const log = process.env.JOURNAL_USAGE_LOG;
  if (log) {
    const line = {
      at: new Date().toISOString(),
      scope: process.env.JOURNAL_SCOPE ?? "",
      model,
      tier: asked.tier,
      thinking,
      attempts: asked.attempts,
      ms: Math.round(performance.now() - started),
      finish: asked.reply.candidates?.[0]?.finishReason ?? null,
      ...usage,
      cost_usd: costOf(model, asked.tier, usage),
    };
    appendFileSync(log, `${JSON.stringify(line)}\n`);
  }
  if (!text.trim()) {
    process.stderr.write(
      `the model returned no text (finish ${asked.reply.candidates?.[0]?.finishReason ?? "none"})\n`,
    );
    return 1;
  }
  process.stdout.write(text);
  return 0;
}

if (import.meta.main) {
  main().then(
    (code) => process.exit(code),
    (err) => {
      process.stderr.write(`${(err as Error).message}\n`);
      process.exit(1);
    },
  );
}
