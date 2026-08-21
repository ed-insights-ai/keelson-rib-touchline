---
title: Research with receipts
description: "Run a real player-profile research pass, reject a bare-name match by hand, split a compound claim under the one-page rule, and verify like the adversary."
sidebar:
  order: 7
---

The last lab proved the gates are mechanical. This one works the other
side of the boundary: the evidence rules that govern what a research stage
may write in the first place. You will run a real research pass over one
player, then do the verifier's job by hand against a finding you planted
yourself. The law is `prompts/research-protocol.md`, applied to one player
by `prompts/player-profile.md`; the machinery is
`workflows/touchline-player-profile.yml`.

By the end you can:

- run `touchline-player-profile` against a real roster player and read
  every receipt it writes
- read a refute ledger: what the verify pass dropped, why, and where a
  dropped claim goes instead of being deleted
- apply identity binding to a bare-name hit and reject one that no
  attribute binds
- split a compound claim under the one-finding-one-page rule and pass the
  adversary's check
- explain why a successful fetch confirms a claim without raising its
  confidence tier

## What you need

- A data home with a collected season for the player's programme. The
  workflow's `assemble` node refuses a name with no trace in the season
  files, so pick a player from a published roster:

  ```sh
  jq -r '.rosters["{programme}"].players[].name' "data/rosters/{season}-{gender}-{conference}.json"
  ```

  Here `{conference}` is the shard slug, lowercase: `gac` for the GAC.
- Live web access: the research stage lives on the open web
  (`webSearchMode: live`).
- The two contracts open beside you: `prompts/research-protocol.md` (how
  to look, for every research stage) and `prompts/player-profile.md` (the
  per-player method and its three verdicts: confirmed, ruled out, no
  indexed mention).

## 1. Try it: run the pass and read the refute ledger

```sh
keelson workflow run touchline-player-profile \
  --inputs "player={player}" \
  --inputs programme={programme} \
  --inputs gender={gender} \
  --inputs conference={conference}
```

The run assembles the deterministic record, researches the one player
under the protocol, then turns adversarial: the `verify` node re-fetches
every finding's URL trying to refute the claim as written, rewrites the
same file with the survivors, and moves each dropped claim into a
`dropped` array with a one-line reason. Its contract allows exactly two
moves, keep a finding verbatim or drop it with its reason; there is no
soften, no merge, no edit. (The report workflow's verify loop extends the
same principle to coaches: an unsupported coach is downgraded to
"unknown", never removed from the map.)

When the summary lands, open the findings file:

```sh
F="data/research/players/{programme}-{player-key}.json"
jq '{findings: (.findings | length), dropped: (.dropped // [] | length),
    attested: (.attested_uncaptured // [] | length), unswept: (.unswept // [] | length)}' "$F"
jq '.dropped // []' "$F"
```

`{player-key}` is the lowercased, hyphenated name. The buckets are the
whole evidence model in one file: findings that survived refutation,
dropped claims each wearing the reason they died, attested-but-uncaptured
beliefs that will never reach a report in any form, and the surfaces the
sweep could not read. A refuted claim leaves `findings` but never leaves
the record. An empty findings array beside a populated `unswept` is a
legal, honest result; "nothing found" is a result too.

Check yourself: the file carries the schema tag and every survivor keeps
its receipt; verify with:

```sh
jq -e '.schema == "touchline.player-findings/1"
  and all(.findings[]; .text and .source and .url and .date)' "$F"
```

## 2. Try it: reject a bare name by hand

Search your player's plain name in a search engine, exactly as the
protocol's bare-name step does. Among the hits, find one that shares the
name but is not your player; a different sport, level, or state usually
surfaces within a page. Now try to make it a finding under the identity
binding rule: a hit must attach through at least one corroborating
attribute (school, hometown, club, age or class year, jersey number, or a
photo caption or tag naming them). A face that looks right is not
evidence, and recency counts: a hometown match on a five-year-old roster
cannot by itself confirm a current-season claim. If nothing binds, the hit
is not a finding, however plausible the story it suggests. The protocol
calls "discoverable but wrong" the pipeline's highest risk, and this
rejection move is the whole defense.

Check yourself: the machine held the same line, so no surviving finding
rests on your namesake; verify with:

```sh
jq '[.findings[] | select(.text | test("{namesake-detail}"; "i"))] | length' "$F"
```

where `{namesake-detail}` is the club or town that belongs to the wrong
person. It must print 0.

## 3. Try it: plant a compound claim and force the split

Destructive edits stay off the real file, so work on a scratch copy:

```sh
cp "$F" {scratch}/findings-lab.json
```

Hand-write one finding into the scratch copy's `findings` array, in the
`touchline.player-findings/1` shape. Give it a URL you really fetched, and
a text that deliberately claims two facts at once:

```json
{
  "type": "summer-league",
  "text": "{player} appeared for {club} in June and was named to the league's Team of the Week",
  "source": "{club} match report",
  "url": "{fetched-url}",
  "date": "{date-the-page-states}",
  "confidence": "medium"
}
```

Now do the verifier's job on it, following the `verify` node's own
instruction: re-fetch the URL and check the page supports the claim as
written (name present, honor named, date plausible). The match report
names the appearance; it says nothing about the weekly honor. As written,
the finding is refutable even if both halves are true, and a verify pass
would move the whole claim into `dropped`. That is the one-finding-one-page
rule doing its work. Read it in `prompts/research-protocol.md` under "One
finding, one page": never write a finding whose truth needs two pages to
check, because the verifier fetches each finding's single URL and drops
any claim that page alone cannot support.

So split it. One finding for the appearance, carrying the match report's
URL. One for the honor, carrying the award post's URL. If the honor has no
fetchable page, it is not a finding at all: it goes to
`attested_uncaptured`, the dead-end bucket, or it goes nowhere.

Check yourself: every finding in the scratch file is schema-shaped and
single-sourced; verify with:

```sh
jq -e 'all(.findings[]; .text and .source and .url and .date
  and (.confidence == "high" or .confidence == "medium"))' {scratch}/findings-lab.json
```

then re-fetch each URL you wrote and confirm the page states the full text
on its own, which is exactly the check the verify pass runs.

## 4. Try it: confirm without promoting

Grade your split findings with the protocol's source-confidence tiers. A match report
on the club's official site is high confidence. The honor announced in a
club social post captured at a stable URL, or in the player's own post, is
medium. You fetched both pages and both support their claims, so both are
confirmed. And the fetch does not raise the tier. Verdict (was the claim
verified at a fetched page) and confidence (what kind of page carried it)
are orthogonal axes; per the protocol, the tier never rises by being
fetched. A fetched self-post is confirmed at medium: the fetch settles
that the source says it, while the tier still says what kind of source it
is. The verify node cannot promote either, since keep-verbatim and drop
are its only moves. Downstream, the protocol's report entry rule spends
the grade: confirmed-at-high may appear in prose freely, while
confirmed-at-medium enters only with its source kind named in the sentence
and never as the sole support for a decision or a major-news item.

Check yourself, the lab's exit criterion: your finding survives your
verify pass with its tier unchanged; verify with:

```sh
jq -r '.findings[] | select(.url == "{fetched-url}") | .confidence' {scratch}/findings-lab.json
```

It must print `medium`, the tier you graded before the fetch, and nothing
downstream will ever raise it.

## Next stop

Your profiled player now stands in
`data/players/{gender}/{programme}/{player-key}.json`, and the report
workflow's research loop reads profiles there as already-verified
findings, so the receipts you produced ride into the full run. Take them
to the capstone: [Capstone: scout a season](../capstone-scout-a-season/)
runs this protocol across every programme in the conference, then audits
the result.

## Related

**Run it**

- [Build a player profile](../../guides/build-a-player-profile/): the same workflow as an operator task, with the no-trace refusal and the enrich-never-replace merge.
- [Prompt contracts](../../reference/prompts-and-protocols/): the contract surface of every prompt file.

**Understand it**

- [Evidence, not recall](../../concepts/evidence-not-recall/): the theory this lab makes physical.
- [Absence is data](../../concepts/absence-is-data/): ruled out against no indexed mention, and why a recorded gap is a result.
