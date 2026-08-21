# Keelson rib documentation style guide

This guide governs the documentation site under `docs/` for this rib. It
**extends** the keelson harness style guide rather than forking it: where this
file is silent, keelson's
[STYLE.md](https://github.com/danielscholl/keelson/blob/main/docs/STYLE.md) is
the parent law. Read both before writing or generating a page.

A rib's docs are a family member of the keelson docs, not a separate brand. A
reader moving from the harness site to a rib site should feel the same hand:
the same blueprint identity, the same tiers, the same voice. Only the subject
changes. keelson's STYLE.md states that the harness "does not document specific
ribs ... Document only the generic, reusable rib contract." This site fills that
gap from the other side: it documents the one concrete rib that implements the
contract.

This file is the per-rib instance of a shared pattern. A new rib copies it,
keeps the rules verbatim, and swaps only the rib-specific specifics (the tier
content, the snapshot keys, the screenshots, the upstreams credited). See
"Starting a new rib's docs" at the foot.

## What a rib inherits verbatim

These are copied from keelson and held identical. Do not diverge; a divergence
here is a bug, not a style choice.

| Inherited | Rule |
|---|---|
| Theme | `src/styles/keelson-theme.css` is a byte-identical copy of keelson's. The blueprint palette (navy `--keel`, brass accent) is the single source of color. Do not fork it per page. |
| Framework + versions | Astro Starlight, dependency versions pinned to keelson's (`@astrojs/starlight`, `astro`, `starlight-llms-txt`). Bump in lockstep with the harness site. |
| IA tiers | The same five: `concepts`, `guides`, `tutorials`, `reference`, `design`. No new top-level tiers. |
| `llms.txt` | `starlight-llms-txt` emits `/llms.txt`, `/llms-full.txt`, `/llms-small.txt` at build. |
| CI | `docs.yml` builds on `docs/**` push and PR (validation) and deploys from `main`. The Bun version is pinned to the same release `ci.yml` validates against. |
| Tooling fences | `biome.json` ignores `docs` (the Astro project is checked by `astro check`, not biome). `.gitignore` ignores `.astro/`. |

Naming conventions that keep the family legible:

- Site title is `Keelson Rib · <Name>` (for example `Keelson Rib · Touchline`).
- Pages deploy to the project Pages URL: `site: https://<owner>.github.io`,
  `base: /<repo>` (for example `/keelson-rib-touchline`), `trailingSlash: always`.
- Favicon is the shared `keelson-mark.svg`.

## Where a rib differs from the harness

A rib has no bespoke marketing landing, so the layout is deliberately simpler
than keelson's. These divergences are intentional and load-bearing:

- **Flat content layout.** Pages live at `src/content/docs/<tier>/`, not
  keelson's nested `src/content/docs/docs/<tier>/`. keelson nests because it
  serves a hand-authored landing at `/` and pushes docs under `/docs/`. A rib
  has no separate landing, so Starlight owns `/` and a flat tree is cleaner.
- **Sidebar Overview links `/`** (keelson links `/docs/`).
- **No bespoke drafting-sheet landing.** There is no `public/index.html` +
  `keelson.css`. Starlight's overview index (`src/content/docs/index.mdx`) is
  the root. If a rib later earns a hand-authored landing, it adopts keelson's
  drafting-sheet treatment rather than inventing a new one.

## What each tier holds, for a rib

Same tiers as keelson, aimed at the concrete rib. The Touchline rib's framing:

- **`concepts/`** — the shape of the rib: how pages are collected under proof,
  reconciled into canonical identities, computed into a deterministic digest,
  and interpreted by a gated model under an evidence standard. Explain *why*
  the rib is built this way before *how*. Link out to keelson's concept pages
  for anything generic (the rib contract, workflows, surfaces); do not
  re-explain the harness.
- **`guides/`** — task-oriented operator how-tos: install, create a data home,
  run a collection, work the board, run a report, build a player profile,
  onboard a school, rebuild from the archive, audit the data. The guides tier
  is user-facing; contributor setup (linking the rib into a local keelson
  checkout, the pre-PR checks) lives in `CONTRIBUTING.md`, the way keelson
  keeps dev setup out of its guides. Don't add a "develop locally" page here.
- **`tutorials/`** — a problem-first learning rail, each page handing off to
  the next. For Touchline this rail is also a data-science curriculum run
  against the real data home; the capstone is the rib's own deepest task
  (running and auditing a full gated scouting report).
- **`reference/`** — the contract tier for *this* rib: its surface and tools,
  the `rib:touchline:board` snapshot key, the four workflows, the data home on
  disk, the versioned file contracts, gates and exit codes, the pipeline CLI,
  and the prompt contracts. Terse and precise, like keelson's reference pages.
- **`design/`** — decision records and the system-design narrative. The right
  home for design narrative the source comment policy keeps out of code, and
  the one tier where dated measurements live (see the delta below).

## Voice

Inherit keelson's voice wholesale: engineering-honest, practitioner to
practitioner, active voice, short sentences, no marketing register, no
unshipped-capability claims, no "Generated with" footers. Two rib-specific notes:

- **Seat the harness relationship once, then drop it.** State "Touchline is a
  keelson rib" at the entry point and move on. Do not keep re-explaining what a
  rib is; link to keelson's concept tier for the generic model and spend your
  words on what *this* rib does.
- **Em dashes: know the boundary.** Docs-site prose (everything under
  `src/content/docs/`) follows keelson's no-em-dash rule: use a comma, a colon,
  parentheses, or two sentences. The repo `README.md` and source files follow
  the repo's own house style, which uses em dashes; that is not a docs-site page
  and the rule does not reach it.

## Figures

Inherit keelson's figure discipline: no ASCII-art diagrams, every figure gets a
one-sentence lead-in in the prose above it and a numbered `figcaption`
("Figure 1. ..."), never dropped in cold.

A rib's signature figures are usually **app screenshots** of its live surfaces,
not abstract diagrams. For Touchline that is the season board (the season rail,
an open drawer, the gaps notice); capture them as captioned figures rather than
re-describing them in prose. The report excerpts and covers shipped in
`src/assets/` (`excerpt-numbers.png`, `excerpt-squadmap.png`, `cover-*.png`)
are placed where the deepening pages use them. keelson reserves the dark
`screenshot-figure` frame for app screenshots and the light `diagram-figure`
frame for diagrams; the inherited theme styles both.

There is **no `Figure` component to author.** Figures are native Markdown
`<figure>` / `<figcaption>`, styled by the inherited `keelson-theme.css`. Write
them directly; the frame and caption styling come for free.

## Attribution is part of the docs pattern

A rib that shells or ports upstream tooling carries the same attribution
contract keelson does, so credit travels with the package:

- **`LICENSE`** — the rib's own license text (the file must exist, not just a
  `package.json` field).
- **`NOTICE`** — per-upstream attribution following keelson's NOTICE structure:
  a header, then one section per upstream with `Project` / `Source` / `License`.
  Quote an upstream's full license text verbatim only when it differs from the
  rib's own license; when it matches, the name and link suffice.
- **`README.md` Acknowledgments** — a short section linking each upstream and
  pointing at `NOTICE`, with the License section pointing at `LICENSE`.
- Ship `LICENSE` and `NOTICE` in `package.json` `files`.

## Definition of done (every rib docs page)

A rib page inherits keelson's per-page checklist (figures captioned, prose
within the ~72ch measure, no em dashes in docs prose, sentence case, the
metaphor seated once and then dropped, a `related` cross-link block). Plus one
rib-specific item:

- **Link back to the harness** wherever a concept is generic. The rib documents
  what it adds; the keelson docs own the contract it adds against. A page that
  re-explains the harness has drifted out of scope.

## Touchline delta

These rules are additions for this rib. They extend the family law; they do not
replace any rule above.

- **Two readers, one site.** The site serves an operator ("run it") and a
  data-science student ("understand it") through shared pages. The tiers are
  the seam: guides do the task with no teaching detours; concepts explain why
  the mechanism exists; tutorials teach through the task; reference stays
  register-neutral. Registers never mix mid-body: no deep-dive callouts inside
  guides, no task steps inside concepts.
- **The two-lane Related block.** Every page's closing `## Related` section is
  split into two labeled lanes: **Run it** (guides, reference) and
  **Understand it** (concepts, tutorials, design). A lane with no natural
  target may be omitted, but prefer finding one.
- **Guides close with "What you just exercised."** A short line naming the
  three or four concepts the task touched, each a link. Concept pages close by
  naming the tutorial that makes them physical ("Lab: ...").
- **Citation law.** Code anchors use file paths and symbol names, never line
  numbers (`pipeline/src/digest.py`'s `AVAILABILITY_MIN_MISSED`, not
  `digest.py:659`). Pipeline paths always carry their `pipeline/` prefix.
  Never hardcode a countable fact the code owns (the number of adjudications,
  the number of schools); state where it is counted instead. The drift script
  enforces the known offenders.
- **Dated measurements.** Point-in-time empirical claims (the measured
  generative share, the Jaccard overlap) are evidence with dates, not
  narration. They live only in `design/` tier pages that state their date, and
  other pages reference them by link rather than restating the number. This is
  a distinction from keelson's ban on point-in-time narration ("per review",
  "addresses issue N"), which remains banned.
- **Exercise durability.** Exercises live in tutorials (numbered "Try it"
  blocks). A flagship concepts page may carry at most one "Observe it" line:
  read-only, under ten minutes, pinned to a completed archived season.
  "Check yourself" criteria are structural (exit codes, schema tags, states,
  a recomputation matching the digest), never count-exact against the living
  season; exact expected values pin only to completed archived seasons.
  Destructive exercises operate on scratch copies and say so.
- **The system grades the student.** Checkpoints end "verify with this
  command"; no prose answer keys.
- **Canonical-page ownership.** Each mechanism has exactly one canonical page;
  every other mention links to it. The founding incident lives in
  `design/gate-after-every-generative-step`; the exemplar leak lives in
  `design/contracts-not-examples`.

## Starting a new rib's docs

To stand up docs for another rib, copy this rib's `docs/` Astro project and this
`STYLE.md`, then:

1. Set the site `title`, `base`, and `description` to the new rib (keep the
   `Keelson Rib · <Name>` title shape).
2. Keep `keelson-theme.css`, the tier folders, the `llms.txt` plugin, `docs.yml`,
   and the biome/gitignore fences as-is.
3. Replace the tier content with the new rib's framing; keep this file's rules
   verbatim and update only the rib-specific examples (snapshot keys,
   screenshots, upstreams credited). Drop or rewrite the Touchline delta to fit
   the new rib.
