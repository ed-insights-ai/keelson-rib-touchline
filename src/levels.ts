// Copyright 2026, Daniel Scholl
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0

/** The NCAA levels a conference plays at, and a data home collects at. The
 *  word is "level" on purpose: "division" already means a conference's own
 *  East/West split on a membership window (and a gender in the cadence
 *  script). Its own module so the data-home marker (src/datahome.ts) and the
 *  membership record (src/membership.ts) share one list without importing
 *  each other. */
export const CONFERENCE_LEVELS = ["d1", "d2", "d3"] as const;
export type ConferenceLevel = (typeof CONFERENCE_LEVELS)[number];

export function isConferenceLevel(value: string): value is ConferenceLevel {
  return (CONFERENCE_LEVELS as readonly string[]).includes(value);
}
