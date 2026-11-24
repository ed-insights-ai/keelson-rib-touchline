#!/usr/bin/env bun
// Sum the journal's model calls (one JSON line each, from gemini.ts) into a
// Markdown table: per build, and the run's total, in tokens and estimated USD.
//
//   bun site/journal/usage.ts <usage.jsonl>

import { existsSync, readFileSync } from "node:fs";

export interface Call {
  scope: string;
  model: string;
  tier: string;
  prompt: number;
  cached: number;
  output: number;
  thoughts: number;
  attempts: number;
  cost_usd: number | null;
}

export interface Row {
  scope: string;
  calls: number;
  prompt: number;
  cached: number;
  output: number;
  thoughts: number;
  retries: number;
  standard: number;
  cost: number;
  unpriced: number;
}

const blank = (scope: string): Row => ({
  scope,
  calls: 0,
  prompt: 0,
  cached: 0,
  output: 0,
  thoughts: 0,
  retries: 0,
  standard: 0,
  cost: 0,
  unpriced: 0,
});

function add(r: Row, c: Call): void {
  r.calls++;
  r.prompt += c.prompt;
  r.cached += c.cached;
  r.output += c.output;
  r.thoughts += c.thoughts;
  r.retries += Math.max(c.attempts - 1, 0);
  if (c.tier !== "flex") r.standard++;
  if (c.cost_usd === null) r.unpriced++;
  else r.cost += c.cost_usd;
}

export function summarize(calls: readonly Call[]): { rows: Row[]; total: Row } {
  const by = new Map<string, Row>();
  const total = blank("total");
  for (const c of calls) {
    const row = by.get(c.scope) ?? blank(c.scope);
    by.set(c.scope, row);
    add(row, c);
    add(total, c);
  }
  return { rows: [...by.values()], total };
}

const n = (x: number): string => x.toLocaleString("en-US");
export const usd = (x: number): string => `$${x.toFixed(2)}`;

export function markdown(calls: readonly Call[]): string {
  if (calls.length === 0) return "No model calls this run.\n";
  const { rows, total } = summarize(calls);
  const models = [...new Set(calls.map((c) => c.model))].join(", ");
  const line = (r: Row, bold = false): string => {
    const b = (s: string) => (bold ? `**${s}**` : s);
    return `| ${b(r.scope || "(unlabelled)")} | ${r.calls} | ${n(r.prompt)} | ${n(r.cached)} | ${n(r.output)} | ${n(r.thoughts)} | ${b(usd(r.cost))} |`;
  };
  const out = [
    `Model: ${models}. Estimated from list prices; the Google bill is the record.`,
    "",
    "| Build | Calls | Input tokens | Cached | Output tokens | Thinking tokens | Est. cost |",
    "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ...rows.map((r) => line(r)),
    line(total, true),
    "",
  ];
  if (total.retries > 0) out.push(`${total.retries} retried request(s).`);
  if (total.standard > 0) out.push(`${total.standard} call(s) fell back to the Standard tier.`);
  if (total.unpriced > 0) out.push(`${total.unpriced} call(s) on a model with no price on file.`);
  return `${out.join("\n")}\n`;
}

export function readCalls(path: string): Call[] {
  if (!existsSync(path)) return [];
  return readFileSync(path, "utf8")
    .split("\n")
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l) as Call);
}

if (import.meta.main) {
  const path = process.argv[2];
  if (!path) {
    console.error("usage: usage.ts <usage.jsonl>");
    process.exit(2);
  }
  const calls = readCalls(path);
  process.stdout.write(markdown(calls));
  const total = summarize(calls).total;
  console.error(`journal: ${total.calls} calls, est. ${usd(total.cost)}`);
}
