// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

import { z } from "zod";

// ─────────────────────────────────────────────────────────────────────────────
// The coverage manifest contract: what `data/coverage.json` may contain.
//
// The writer is pipeline/src/coverage.py, stamped by collect_board.py; the
// strict reader is the site. This is the rib's own statement of the shape it
// writes, and contracts/coverage-1.json is the sample that proves it. The two
// move together: a value the writer starts to emit lands in the fixture and
// here in the same change, or the contract test fails.
// ─────────────────────────────────────────────────────────────────────────────

export const COVERAGE_SCHEMA = "touchline.coverage/1";

/** Four states, and the difference between them is the point: `complete` was
 *  collected, `empty` was collected and the page had nothing, `unavailable`
 *  means the source refused or vanished, `no-collector` means Touchline has
 *  no way to ask. Not collected is not the same as not published. */
export const coverageStateSchema = z.enum(["complete", "empty", "unavailable", "no-collector"]);
export type CoverageState = z.infer<typeof coverageStateSchema>;

export const coverageLayerSchema = z.enum(["schedule", "roster", "stats", "matches"]);
export type CoverageLayer = z.infer<typeof coverageLayerSchema>;

export const coverageCellSchema = z
  .object({
    season: z.number().int(),
    gender: z.string().min(1),
    programme: z.string().min(1),
    layer: coverageLayerSchema,
    state: coverageStateSchema,
    collector: z.string().optional(),
    confirmed_at: z.string().optional(),
    count: z.number().int().optional(),
    reason: z.string().optional(),
    source_url: z.string().optional(),
    /** The conditional fetch's marker: a page the server said was unchanged
     *  was reused, not re-parsed, and the cell says so. A marker, not a
     *  state; `state` is still the layer's outcome. */
    verified: z.literal("unchanged").optional(),
    /** Rows the page published that the collector read and deliberately did
     *  not mint, each named ("hosted other-match skipped: 2026-08-27, A v B").
     *  A sibling of `reason` for a layer that is still complete: it says why
     *  the page's row count and the fixture count differ, and nothing else. */
    skips: z.array(z.string().min(1)).optional(),
  })
  .strict();
export type CoverageCell = z.infer<typeof coverageCellSchema>;

export const coverageFileSchema = z
  .object({
    schema: z.literal(COVERAGE_SCHEMA),
    updated_at: z.string().min(1),
    /** Keyed `{season}/{gender}/{programme}/{layer}`. */
    cells: z.record(z.string(), coverageCellSchema),
  })
  .strict();
export type CoverageFile = z.infer<typeof coverageFileSchema>;
