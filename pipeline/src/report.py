"""Deterministic report renderer — the digest made printable.

The renderer merges two inputs into a self-contained, print-first HTML
briefing (US Letter, warm paper, old-gold accent):

* the **digest** (``touchline.digest/1``) — every figure, table, and chart in
  the page is drawn from it and nowhere else.  The renderer may present
  digest numbers (per-match rates, conference medians, streaks) but never
  invents one;
* a **narrative** (``touchline.report-narrative/2``) — prose authored by the
  report workflow's analyst and research nodes.  The narrative never carries
  a number the digest doesn't; the workflow's verification pass enforces
  that upstream.

The split is the product's safety boundary: a language model writes the
narrative *file*, and this renderer — plain code — decides everything that is
actually a fact on the page.  Missing narrative sections render as explicit
placeholders, so the deterministic skeleton always ships.

Every important claim carries an evidence label:
``observed`` (computed from published results/event data), ``projected``
(model estimate, assumptions stated), or ``judgment`` (scouting
interpretation that requires film).  There is no xG anywhere: shot locations
are not collected, and a transparent absence beats false precision.

Narrative contract (``touchline.report-narrative/3``)::

    {
      "schema": "touchline.report-narrative/3",
      "headline": str,
      "exec": {
        "bottom_line": str,
        "findings":   [{"evidence": str, "meaning": str, "implication": str,
                        "label": LABEL, "confidence": CONF}],   # exactly 3
        "decisions":  [{"title": str, "text": str}],            # at most 3
        "priorities": [str]   # renders on the roster-decisions page
      },
      "landscape": str,   # positioning AND where the focus side gains ground
      "focus": {"overview": str,
                 "roster": [{"title": str, "text": str}],
                 "news": [NEWS], "offseason": [LEDGER]},
                 # roster: reads the digest's roster_shape — one row per
                 # line of the team (In goal, Back line, Midfield, Front
                 # line, Squad age), tying last season's problems to this
                 # season's makeup. A plain string renders as prose.
                 # offseason: at most 3 consolidated signals.
      "programmes": {slug: {"threat": str, "vulnerability": str,
                             "roster_note": str, "implication": str,
                             "news": [NEWS],
                             "tier": "benchmark"|"swing"|"update"}},
                             # benchmark: the sides that set the standard
                             # (two full cards per page, news included);
                             # swing: winnable fixtures that decide the
                             # season (three condensed cards per page);
                             # update: too little data — re-run before the
                             # fixture. "vulnerability" renders under the
                             # header "Potential opening".
      "watchlist": [{"player": str, "programme": str, "note": str,
                      "label": LABEL}],
      "dossiers":  [{"player": str, "role": str, "verdict": str,
                     "strengths": [str], "limitations": [str], "fit": str,
                     "question": str, "video_checks": [str]}],
      "questions": [str]
    }
    LABEL = "observed" | "projected" | "signal" | "judgment"
    CONF  = "high" | "medium" | "low"
    NEWS   = {"text", "source", "url", "date"}
    LEDGER = {"player", "text", "sources"?: [{"source", "url"?, "date"?}]}

``signal`` marks an observed pattern whose cause is unverified (participation
gaps, minutes collapses) — the record shows the gap, not the reason.
Paragraph breaks in prose are blank lines.
"""

from __future__ import annotations

import html
from datetime import date
from statistics import median
from typing import Any

MINUTE_BANDS = ("0-15", "15-30", "30-45", "45-60", "60-75", "75-90", "90+")

PLACEHOLDER = (
    "Narrative pending — the report workflow has not written this section yet."
)

LABEL_NAMES = {
    "observed": "Observed",
    "projected": "Projected",
    "signal": "Unverified signal",
    "judgment": "Scouting judgment",
}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def record_line(rec: dict) -> str:
    """American college order — W-L-T — everywhere a record appears."""
    return f"{rec.get('wins', 0)}-{rec.get('losses', 0)}-{rec.get('draws', 0)}"


def prose(text: str | None) -> str:
    if not text or not text.strip():
        return f'<p class="pending">{PLACEHOLDER}</p>'
    return "".join(
        f"<p>{esc(par.strip())}</p>" for par in text.split("\n\n") if par.strip()
    )


def _long_date(iso: str) -> str:
    try:
        year, month, day = (int(part) for part in iso.split("-"))
    except ValueError:
        return iso
    months = (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    )
    return f"{months[month - 1]} {day}, {year}"


def label_chip(label: str | None) -> str:
    key = (label or "").strip().lower()
    if key not in LABEL_NAMES:
        return ""
    return f'<span class="lbl lbl-{key}">{LABEL_NAMES[key]}</span>'


def confidence_dot(level: str | None) -> str:
    key = (level or "").strip().lower()
    if key not in ("high", "medium", "low"):
        return ""
    return f'<span class="conf conf-{key}" title="confidence {key}">{key}</span>'


# ── Digest-derived rates (deterministic presentation math) ───────────────────


def _rate(total: int | None, matches: int | None) -> float | None:
    if not total and total != 0:
        return None
    if not matches:
        return None
    return round(total / matches, 1)


def _pct(part: int | None, whole: int | None) -> int | None:
    if part is None or not whole:
        return None
    return round(part / whole * 100)


def _programme_rates(section: dict) -> dict | None:
    """Per-match rates for one programme's last season, from held box scores."""
    last = section.get("last_season") or {}
    patterns = last.get("patterns") or {}
    counted = patterns.get("matches_counted") or 0
    if not counted:
        return None
    shots = patterns.get("shots", {})
    corners = patterns.get("corners", {})
    bands_against = patterns.get("goals_by_minute", {}).get("against", {})
    halves_against = patterns.get("goals_by_half", {}).get("against", {})
    ga_total = sum(int(v or 0) for v in bands_against.values())
    late = int(bands_against.get("75-90", 0)) + int(bands_against.get("90+", 0))
    overall = last.get("overall", {})
    played = overall.get("played") or 0
    return {
        "matches": counted,
        "shots_for": _rate(shots.get("for"), counted),
        "shots_against": _rate(shots.get("against"), counted),
        "corners_for": _rate(corners.get("for"), counted),
        "corners_against": _rate(corners.get("against"), counted),
        "second_half_ga_pct": _pct(halves_against.get("second"), ga_total),
        "late_ga_pct": _pct(late, ga_total),
        "gf_per_match": _rate(overall.get("gf"), played),
        "ga_per_match": _rate(overall.get("ga"), played),
    }


def _day_gap(prev_iso: str | None, cur_iso: str | None) -> int | None:
    """Days between two ISO dates, for conference-fixture turnaround."""
    if not prev_iso or not cur_iso:
        return None
    try:
        prev = date.fromisoformat(str(prev_iso))
        cur = date.fromisoformat(str(cur_iso))
    except ValueError:
        return None
    return (cur - prev).days


# ── Visual atoms ─────────────────────────────────────────────────────────────


def indicator_tiles(digest: dict) -> str:
    """The executive brief's four real indicators, all observed."""
    focus = digest["programmes"][digest["focus"]]
    turnover = focus.get("turnover") or {}
    share = turnover.get("returning_share") or {}
    counts = turnover.get("counts") or {}
    last = focus.get("last_season") or {}
    conf = last.get("conference", {})
    tiles = []

    def tile(value: str, label: str, sub: str) -> None:
        tiles.append(
            f'<div class="tile"><span class="tile-val num">{esc(value)}</span>'
            f'<span class="tile-label">{esc(label)}</span>'
            f'<span class="tile-sub">{esc(sub)}</span></div>'
        )

    if share.get("minutes") is not None:
        tile(f"{round(share['minutes'] * 100)}%", "Returning minutes", f"of {turnover.get('previous_season')} played")
    if share.get("goals") is not None:
        tile(f"{round(share['goals'] * 100)}%", "Returning goals", f"of {turnover.get('previous_season')} scored")
    if counts.get("returning") is not None:
        tile(
            str(counts["returning"]),
            "Returners",
            f"+{counts.get('newcomers', 0)} new, {counts.get('departed', 0)} departed",
        )
    if conf:
        tile(record_line(conf), f"{last.get('season')} conference (W-L-T)", f"{conf.get('gf')}:{conf.get('ga')} goals")
    return f'<div class="tiles">{"".join(tiles)}</div>'


def share_bars(share: dict | None) -> str:
    if not share:
        return ""
    rows = []
    for field, label in (("goals", "Goals"), ("points", "Points"), ("minutes", "Minutes")):
        value = share.get(field)
        if value is None:
            continue
        pct = round(value * 100)
        rows.append(
            f'<div class="share-row"><span class="share-label">{label}</span>'
            f'<span class="share-track"><span class="share-fill" style="width:{pct}%"></span></span>'
            f'<span class="share-num num">{pct}%</span></div>'
        )
    if not rows:
        return ""
    return (
        '<div class="share"><div class="viz-title">Returning production</div>'
        + "".join(rows)
        + "</div>"
    )


def minute_chart(patterns: dict | None) -> str:
    """Goals for (up, gold) and against (down, rose) by 15-minute band."""
    if not patterns:
        return ""
    bands_for = patterns.get("goals_by_minute", {}).get("for", {})
    bands_against = patterns.get("goals_by_minute", {}).get("against", {})
    values = [int(bands_for.get(band, 0)) for band in MINUTE_BANDS]
    against = [int(bands_against.get(band, 0)) for band in MINUTE_BANDS]
    peak = max([*values, *against, 1])

    width, half, gutter = 660, 74, 26
    col = (width - 60) / len(MINUTE_BANDS)
    bar_width = col - 18
    height = half * 2 + gutter
    mid_top = half
    mid_bottom = half + gutter
    parts = [
        f'<svg viewBox="0 0 {width} {height + 22}" role="img" '
        f'aria-label="Goals for and against by fifteen-minute band">'
    ]
    parts.append(
        f'<line x1="30" y1="{mid_top}" x2="{width - 10}" y2="{mid_top}" class="axis"/>'
        f'<line x1="30" y1="{mid_bottom}" x2="{width - 10}" y2="{mid_bottom}" class="axis"/>'
        f'<text x="8" y="{mid_top - 28}" class="axis-label" transform="rotate(-90 14 {mid_top - 22})">FOR</text>'
        f'<text x="8" y="{mid_bottom + 46}" class="axis-label" transform="rotate(-90 14 {mid_bottom + 40})">AGST</text>'
    )
    for index, band in enumerate(MINUTE_BANDS):
        x = 40 + index * col
        up = round(values[index] / peak * (half - 16))
        down = round(against[index] / peak * (half - 16))
        if values[index]:
            parts.append(
                f'<rect x="{x:.0f}" y="{mid_top - up}" width="{bar_width:.0f}" height="{up}" class="bar-for"/>'
                f'<text x="{x + bar_width / 2:.0f}" y="{mid_top - up - 5}" class="bar-num num">{values[index]}</text>'
            )
        if against[index]:
            parts.append(
                f'<rect x="{x:.0f}" y="{mid_bottom}" width="{bar_width:.0f}" height="{down}" class="bar-against"/>'
                f'<text x="{x + bar_width / 2:.0f}" y="{mid_bottom + down + 13}" class="bar-num num">{against[index]}</text>'
            )
        parts.append(
            f'<text x="{x + bar_width / 2:.0f}" y="{mid_top + 16}" class="band-label num">{band}</text>'
        )
    parts.append("</svg>")
    counted = patterns.get("matches_counted")
    total = patterns.get("played_total")
    coverage = (
        f'<div class="viz-note">Goals by minute of match · {counted} of {total} matches '
        "with a held box score</div>"
        if counted is not None
        else ""
    )
    return f'<div class="minutes">{"".join(parts)}{coverage}</div>'


def dumbbell_chart(digest: dict) -> str:
    """Focus vs conference median, one row per observed per-match rate.

    Each row is scaled to its own maximum — units differ between rows, so
    only the within-row comparison means anything.  The focus dot turns
    rose when it sits on the wrong side of the median for that metric, and
    the values live in fixed columns so labels never collide.
    """
    focus_rates = _programme_rates(digest["programmes"][digest["focus"]])
    if not focus_rates:
        return ""
    all_rates = [
        rates
        for slug, section in digest["programmes"].items()
        if (rates := _programme_rates(section)) is not None
    ]
    metrics = (
        ("shots_for", "Shots taken /match", "higher"),
        ("shots_against", "Shots faced /match", "lower"),
        ("corners_for", "Corners won /match", "higher"),
        ("corners_against", "Corners conceded /match", "lower"),
        ("second_half_ga_pct", "Share of GA after halftime, %", "lower"),
        ("late_ga_pct", "Share of GA from 75′ on, %", "lower"),
    )
    rows = []
    for key, label, better in metrics:
        own = focus_rates.get(key)
        pool = [rates[key] for rates in all_rates if rates.get(key) is not None]
        if own is None or not pool:
            continue
        rows.append((label, better, own, round(median(pool), 1)))
    if not rows:
        return ""

    width, row_h, left = 660, 40, 208
    span = 330
    own_col, med_col = width - 64, width - 8
    parts = [
        f'<svg viewBox="0 0 {width} {len(rows) * row_h + 26}" role="img" '
        f'aria-label="Focus programme versus conference median on observed rates">'
    ]
    parts.append(
        f'<text x="{own_col}" y="12" class="db-colhead" text-anchor="end">'
        f"{esc(digest['programmes'][digest['focus']].get('abbr') or 'own')}</text>"
        f'<text x="{med_col}" y="12" class="db-colhead" text-anchor="end">med</text>'
    )
    for index, (label, better, own, med) in enumerate(rows):
        y = index * row_h + 34
        row_max = max(own, med) * 1.15 or 1
        x_own = left + own / row_max * span
        x_med = left + med / row_max * span
        worse = own < med if better == "higher" else own > med
        own_cls = "db-own-bad" if worse else "db-own"
        parts.append(
            f'<text x="0" y="{y + 4}" class="db-label">{esc(label)}</text>'
            f'<line x1="{left}" y1="{y}" x2="{left + span}" y2="{y}" class="db-track"/>'
            f'<line x1="{x_med:.0f}" y1="{y}" x2="{x_own:.0f}" y2="{y}" class="db-join"/>'
            f'<circle cx="{x_med:.0f}" cy="{y}" r="5" class="db-med"/>'
            f'<circle cx="{x_own:.0f}" cy="{y}" r="6" class="{own_cls}"/>'
            f'<text x="{own_col}" y="{y + 4}" class="db-num num {own_cls}-t" text-anchor="end">{own:g}</text>'
            f'<text x="{med_col}" y="{y + 4}" class="db-mednum num" text-anchor="end">{med:g}</text>'
        )
    parts.append("</svg>")
    focus_name = digest["programmes"][digest["focus"]].get("name", digest["focus"])
    legend = (
        '<div class="viz-note"><span class="dot dot-own"></span> '
        f"{esc(focus_name)} better than the median &nbsp; "
        '<span class="dot dot-bad"></span> worse &nbsp; '
        '<span class="dot dot-med"></span> conference median · '
        f"{digest.get('previous_season')} season · each row on its own scale</div>"
    )
    return f'<div class="dumbbell">{"".join(parts)}{legend}</div>'


def landscape_scatter(digest: dict) -> str:
    """Goals for vs goals against per match, every programme, last season."""
    points = []
    for slug, section in digest["programmes"].items():
        rates = _programme_rates(section)
        if not rates or rates.get("gf_per_match") is None or rates.get("ga_per_match") is None:
            continue
        points.append((slug, section.get("abbr") or slug[:3].upper(), rates["gf_per_match"], rates["ga_per_match"]))
    if len(points) < 3:
        return ""
    width, height, pad = 620, 330, 46
    max_gf = max(p[2] for p in points) * 1.15
    max_ga = max(p[3] for p in points) * 1.15
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Goals scored per match against goals conceded per match, by programme">'
    ]
    parts.append(
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - 12}" y2="{height - pad}" class="axis"/>'
        f'<line x1="{pad}" y1="14" x2="{pad}" y2="{height - pad}" class="axis"/>'
        f'<text x="{(width + pad) / 2}" y="{height - 8}" class="axis-title">Goals scored per match →</text>'
        f'<text x="12" y="{(height - pad) / 2}" class="axis-title" transform="rotate(-90 16 {(height - pad) / 2})">Goals conceded per match →</text>'
    )
    for slug, abbr, gf, ga in sorted(points, key=lambda p: p[2]):
        x = pad + gf / max_gf * (width - pad - 24)
        y = 14 + ga / max_ga * (height - pad - 26)
        own = slug == digest["focus"]
        parts.append(
            f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{7 if own else 5}" class="{"sc-own" if own else "sc-pt"}"/>'
            f'<text x="{x + 9:.0f}" y="{y + 4:.0f}" class="sc-label{" sc-label-own" if own else ""}">{esc(abbr)}</text>'
        )
    parts.append("</svg>")
    return (
        f'<div class="scatter">{"".join(parts)}'
        f'<div class="viz-note">Observed · {digest.get("previous_season")} final results, all matches. '
        "Down-left is porous, up-right is dangerous; the best corner is bottom-right.</div></div>"
    )


def h2h_strip(versus: dict | None, names: dict[str, str], focus: str, limit: int = 8) -> str:
    """Held meetings as result chips, most recent last, scores focus-first."""
    if not versus:
        return '<div class="viz-note">No held meetings.</div>'
    chips = []
    meetings = versus.get("meetings", [])
    for meeting in meetings[-limit:]:
        result = meeting.get("focus_result", "?")
        score = str(meeting.get("score", ""))
        if meeting.get("home") != focus and "-" in score:
            home_goals, _, away_goals = score.partition("-")
            score = f"{away_goals}-{home_goals}"
        chips.append(
            f'<span class="chip chip-{result.lower()}" title="{esc(meeting.get("date"))} · '
            f'{esc(names.get(meeting.get("home"), meeting.get("home")))} '
            f'{esc(meeting.get("score"))} '
            f'{esc(names.get(meeting.get("away"), meeting.get("away")))}">'
            f'<b>{result}</b> <span class="num">{esc(score)}</span>'
            f'<i class="num">{esc(meeting.get("season"))}</i></span>'
        )
    first_season = meetings[0].get("season") if meetings else None
    span_word = f"since {first_season}" if first_season else "held record"
    overall = (
        f'<span class="h2h-rec num">{versus.get("wins")}-{versus.get("losses")}-{versus.get("draws")}'
        f"</span> W-L-T {span_word}, {len(meetings)} held meetings"
    )
    return (
        f'<div class="h2h"><div class="viz-title">Head-to-head <span class="dim">({overall})</span></div>'
        f'<div class="chips">{"".join(chips)}</div></div>'
    )


def news_cards(items: list[dict] | None) -> str:
    if not items:
        return ""
    cards = []
    for item in items:
        source = esc(item.get("source", ""))
        date = esc(item.get("date", ""))
        url = esc(item.get("url", ""))
        cite = f'<a href="{url}">{source}</a>' if url else source
        cards.append(
            f'<div class="news"><span class="news-tag">Verified news</span>'
            f"<p>{esc(item.get('text', ''))}</p>"
            f'<div class="news-cite">{cite} · {date}</div></div>'
        )
    return "".join(cards)


def _cite(source: str, url: str, when: str) -> str:
    link = f'<a href="{esc(url)}">{esc(source)}</a>' if url else esc(source)
    return " · ".join(part for part in (link, esc(when)) if part)


def offseason_ledger(items: list[dict] | None) -> str:
    """At most three consolidated signals; each item carries every source
    that supports it as footnoted citations."""
    if not items:
        return ""
    rows = []
    for item in items[:3]:
        cites = [
            _cite(src.get("source", ""), src.get("url", ""), src.get("date", ""))
            for src in item.get("sources") or []
        ]
        if not cites and (item.get("source") or item.get("date")):
            cites = [_cite(item.get("source", ""), item.get("url", ""), item.get("date", ""))]
        cite_row = (
            f'<span class="ledger-cite">{"&ensp;·&ensp;".join(cites)}</span>' if cites else ""
        )
        rows.append(
            f'<div class="ledger-row"><b>{esc(item.get("player", ""))}</b>'
            f"<span>{esc(item.get('text', ''))}</span>{cite_row}</div>"
        )
    return (
        '<div class="ledger"><div class="viz-title">The offseason ledger · '
        "verified activity between seasons</div>" + "".join(rows) + "</div>"
    )


def takeaway_list(items: list[str] | None, title: str = "Preparation points") -> str:
    if not items:
        return ""
    rows = "".join(f"<li>{esc(item)}</li>" for item in items)
    return (
        f'<div class="takeaways"><div class="viz-title">{esc(title)}</div>'
        f"<ul>{rows}</ul></div>"
    )


# ── Tables ───────────────────────────────────────────────────────────────────


def landscape_table(digest: dict) -> str:
    rows = []
    entries = []
    for slug, section in digest["programmes"].items():
        last = section.get("last_season")
        if not last:
            continue
        entries.append((slug, section, last, last.get("conference", {})))
    entries.sort(
        key=lambda item: (
            -(item[3].get("wins", 0) * 3 + item[3].get("draws", 0)),
            -(item[3].get("gf", 0) - item[3].get("ga", 0)),
        )
    )
    for slug, section, last, conf in entries:
        overall = last.get("overall", {})
        turnover = section.get("turnover") or {}
        share = (turnover.get("returning_share") or {}).get("goals")
        share_cell = (
            f'<span class="mini-track"><span class="mini-fill" style="width:{round(share * 100)}%"></span></span>'
            f'<span class="num">{round(share * 100)}%</span>'
            if share is not None
            else '<span class="dim">roster pending</span>'
        )
        focus_class = ' class="is-focus"' if slug == digest["focus"] else ""
        rows.append(
            f"<tr{focus_class}><td>{esc(section.get('name', slug))}"
            + (f' <span class="abbr">{esc(section["abbr"])}</span>' if section.get("abbr") else "")
            + f'</td><td class="num">{record_line(overall)}</td>'
            f'<td class="num">{overall.get("gf")}:{overall.get("ga")}</td>'
            f'<td class="num">{record_line(conf)}</td>'
            f'<td class="num">{conf.get("gf")}:{conf.get("ga")}</td>'
            f'<td class="num">{last.get("clean_sheets")}</td>'
            f'<td class="share-cell">{share_cell}</td></tr>'
        )
    season = digest.get("previous_season")
    return (
        '<table class="grid"><thead><tr>'
        f'<th>{esc(digest.get("conference", ""))} programme</th>'
        f'<th class="num">{season} W-L-T</th><th class="num">GF:GA</th>'
        '<th class="num">Conf W-L-T</th><th class="num">Conf GF:GA</th>'
        '<th class="num">CS</th><th>Returning goals</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        '<div class="viz-note">Returning goals: the share of last season\'s goals scored by '
        "players on the new roster.</div>"
    )


def schedule_matrix(digest: dict, names: dict[str, str], narrative: dict | None = None) -> str:
    """Every meeting with a conference opponent, chronological — planning
    columns (turnaround, venue, opponent continuity, priority), not history."""
    stories = (narrative or {}).get("programmes") or {}
    rows = []
    fixtures = []
    for slug, section in digest["programmes"].items():
        if slug == digest["focus"]:
            continue
        for fixture in section.get("fixtures_vs_focus") or []:
            fixtures.append((slug, section, fixture))
    fixtures.sort(key=lambda item: str(item[2].get("date")))
    seasons = digest.get("seasons_held") or []
    first_held = seasons[0] if seasons else None
    prev_date: str | None = None
    prev_away = False
    for slug, section, fixture in fixtures:
        at_home = fixture.get("home") == digest["focus"]
        turnover = section.get("turnover") or {}
        share = (turnover.get("returning_share") or {}).get("minutes")
        versus = section.get("head_to_head")
        gap = _day_gap(prev_date, str(fixture.get("date")))
        gap_cell = f"{gap}d" if gap is not None else "–"
        if gap is not None and gap <= 4:
            gap_cell = f'<span class="tight">{gap}d</span>'
        trip = ""
        if not at_home and prev_away:
            trip = ' <span class="tag tag-away">2nd straight</span>'
        priority = bool((stories.get(slug) or {}).get("priority"))
        rows.append(
            f'<tr{" class=" + chr(34) + "is-focus" + chr(34) if priority else ""}>'
            f'<td class="num">{esc(_long_date(str(fixture.get("date"))))}</td>'
            f"<td>{esc(section.get('name', slug))}"
            + (' <span class="prio-mini">priority</span>' if priority else "")
            + "</td>"
            f'<td><span class="tag tag-{"home" if at_home else "away"}">{"HOME" if at_home else "AWAY"}</span>{trip}</td>'
            f'<td class="num">{gap_cell}</td>'
            f'<td class="num">{f"{round(share * 100)}%" if share is not None else "–"}</td>'
            f'<td class="num">{record_line(versus) if versus else "–"}</td></tr>'
        )
        prev_date = str(fixture.get("date"))
        prev_away = not at_home
    h2h_head = f"H2H since {first_held}" if first_held else "H2H held"
    return (
        '<table class="grid"><thead><tr><th class="num">Date</th><th>Opponent</th><th>Venue</th>'
        '<th class="num">Turnaround</th>'
        f'<th class="num">Opp. continuity</th><th class="num">{h2h_head}</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        '<div class="viz-note">Turnaround counts days since the previous conference '
        "fixture only. Non-conference matches in between are not shown, so true rest may be "
        "shorter, never longer. Opponent continuity is the share of last season's minutes "
        "returning on the opponent's published roster. H2H is W-L-T from the focus side over "
        "held seasons.</div>"
    )


def returning_table(profiles: list[dict]) -> str:
    if not profiles:
        return ""
    rows = []
    for profile in profiles:
        last = profile["career"][-1] if profile.get("career") else {}
        seasons = len(profile.get("career") or [])
        meta = " · ".join(
            esc(profile[key]) for key in ("position", "class_year") if profile.get(key)
        )
        rows.append(
            f'<tr><td><b>{esc(profile.get("name", ""))}</b><span class="player-meta">{meta}</span></td>'
            f'<td class="num">{last.get("gp", "–")}</td>'
            f'<td class="num">{last.get("goals", "–")}</td>'
            f'<td class="num">{last.get("assists", "–")}</td>'
            f'<td class="num">{last.get("points", "–")}</td>'
            f'<td class="num">{last.get("minutes", "–")}</td>'
            f'<td class="num">{seasons}</td></tr>'
        )
    return (
        '<div class="viz-title">Returning threats</div>'
        '<table class="grid slim"><thead><tr><th>Player</th>'
        '<th class="num">GP</th><th class="num">G</th><th class="num">A</th>'
        '<th class="num">Pts</th><th class="num">Min</th><th class="num">Yrs</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def availability_block(last: dict | None) -> str:
    """Participation gaps whose cause the record cannot state — rendered as
    UNVERIFIED SIGNAL, and only for players still relevant to the new season.

    The gap is observed; the reason (injury, transfer, discipline, redshirt)
    is unknown. Departed players are omitted — a resolved case changes no
    decision.
    """
    flags = [
        flag
        for flag in (last or {}).get("availability_flags") or []
        if flag.get("on_current_roster") is not False
    ]
    if not flags:
        return ""
    rows = []
    for flag in flags[:4]:
        roster = flag.get("on_current_roster")
        status = (
            '<span class="tag tag-ret">on new roster</span>'
            if roster
            else '<span class="tag tag-away">roster pending</span>'
        )
        if flag.get("kind") == "gap":
            pattern = (
                f"out after {_long_date(str(flag.get('out_after', '')))}, "
                f"back {_long_date(str(flag.get('back_on', '')))} · "
                f"{flag.get('missed')} of {flag.get('of_matches')} missed"
            )
        else:
            pattern = (
                f"stopped {_long_date(str(flag.get('last_seen', '')))} · "
                f"missed final {flag.get('missed_after')} of {flag.get('of_matches')}"
            )
        apps = f"{flag.get('appearances')}"
        if flag.get("starts"):
            apps += f" ({flag['starts']} GS)"
        rows.append(
            f"<tr><td><b>{esc(flag.get('name', ''))}</b></td>"
            f'<td class="num">{esc(apps)}</td>'
            f'<td class="num">{flag.get("minutes")}</td>'
            f"<td>{esc(pattern)}</td>"
            f"<td>{status}</td></tr>"
        )
    return (
        f'<div class="viz-title">Availability — requires confirmation {label_chip("signal")}</div>'
        '<table class="grid slim"><thead><tr><th>Player</th><th class="num">Apps</th>'
        '<th class="num">Min</th><th>Pattern</th>'
        "<th></th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        '<div class="viz-note">The participation gaps are observed in held box scores; their '
        "causes are not. Injury, discipline, and redshirt look identical here. Anyone reading "
        "the public record sees the same pattern, so treat each row as a question to resolve "
        "before opponents answer it for themselves. Resolved departures are omitted.</div>"
    )


def usage_block(section: dict) -> str:
    """Year-over-year minutes collapses for players still on the roster —
    rendered as PROJECTED possible analysis, never as fact."""
    shifts = section.get("usage_shifts") or []
    if not shifts:
        return ""
    rows = []
    for shift in shifts[:5]:
        before = shift.get("before", {})
        after = shift.get("after", {})
        rows.append(
            f"<tr><td><b>{esc(shift.get('name', ''))}</b></td>"
            f'<td class="num">{before.get("minutes")}′ in {before.get("season")}</td>'
            f'<td class="num">{after.get("minutes")}′ in {after.get("season")}</td>'
            f'<td class="num">−{shift.get("drop_pct")}%</td></tr>'
        )
    return (
        f'<div class="viz-title">Usage shifts, year over year {label_chip("signal")}</div>'
        '<table class="grid slim"><thead><tr><th>Player</th><th class="num">Before</th>'
        '<th class="num">After</th><th class="num">Δ minutes</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table>"
        '<div class="viz-note">Players still on the new roster whose minutes collapsed between '
        "the last two seasons. The collapse is observed; the cause is not. An injury year, a "
        "lost position battle, and a redshirt look identical in this data. A returner whose "
        "heavy season was two years ago may be better than last season's film suggests.</div>"
    )


POSITION_LABELS = {
    "GK": "In goal",
    "D": "Back line",
    "M": "Midfield",
    "F": "Front line",
    "?": "Position unlisted",
}
POSITION_ORDER = ("GK", "D", "M", "F", "?")


def shape_strip(section: dict) -> str:
    """The squad map: one row per line, one unit per player, colored by
    class year (light freshman to dark senior).  Returners sit left of the
    divider, newcomers right; the bar is last season's minutes returning.
    All observed."""
    shape = section.get("roster_shape")
    if not shape:
        return ""
    known = shape.get("turnover_known")
    cls_order = ("Sr", "Jr", "So", "Fr", "?")
    cls_words = {"Sr": "senior", "Jr": "junior", "So": "sophomore", "Fr": "freshman", "?": "class unlisted"}

    def units(group: dict, status: str) -> str:
        return "".join(
            f'<i class="unit u-{cls.lower().replace("?", "x")}" '
            f'title="{count} {cls_words[cls]} {status}"></i>' * count
            for cls in cls_order
            if (count := int(group.get(cls) or 0))
        )

    rows = []
    for pos in POSITION_ORDER:
        row = (shape.get("by_position") or {}).get(pos)
        if not row:
            continue
        classes = row.get("classes") or {}
        returning_units = units(classes.get("returning") or {}, "returning")
        newcomer_units = units(classes.get("newcomers") or {}, "new")
        divider = '<i class="sq-div"></i>' if known and (returning_units or newcomer_units) else ""
        share = row.get("minutes_share")
        share_cell = (
            f'<span class="mini-track"><span class="mini-fill" style="width:{round(share * 100)}%"></span></span>'
            f'<span class="num">{round(share * 100)}%</span>'
            if share is not None
            else '<span class="dim">–</span>'
        )
        counts = f"{row.get('returning', 0)} return · {row.get('newcomers', 0)} new" if known else f"{row.get('newcomers', 0)} listed"
        rows.append(
            f'<div class="sq-row"><span class="sq-label">{esc(POSITION_LABELS.get(pos, pos))}'
            f"<em>{esc(counts)}</em></span>"
            f'<span class="sq-units">{returning_units}{divider}{newcomer_units}</span>'
            f'<span class="sq-share">{share_cell}</span></div>'
        )
    if not rows:
        return ""
    legend_classes = "".join(
        f'<span class="lg"><i class="unit u-{cls.lower()}"></i>{cls}</span>'
        for cls in ("Fr", "So", "Jr", "Sr")
    )
    legend = (
        f'<div class="sq-legend">{legend_classes}'
        + (
            '<span class="lg-note">left of the divider returning · right new · '
            "bar = share of last season's minutes returning</span>"
            if known
            else '<span class="lg-note">previous roster not held, so every player counts as new</span>'
        )
        + "</div>"
    )
    return f'<div class="squadmap">{"".join(rows)}{legend}</div>'


def roster_read(value) -> str:
    """The narrative's line-by-line roster read.  A list of {title, text}
    renders as labeled rows; a plain string falls back to prose."""
    if not value:
        return f'<p class="pending">{PLACEHOLDER}</p>'
    if isinstance(value, str):
        return f'<div class="story">{prose(value)}</div>'
    rows = "".join(
        f'<span class="f-label">{esc(item.get("title", ""))}</span>'
        f"<span>{esc(item.get('text', ''))}</span>"
        for item in value
    )
    return f'<div class="f-grid roster-grid">{rows}</div>'


def shape_line(section: dict) -> str:
    """One-line minutes-back summary for opponent cards."""
    shape = section.get("roster_shape")
    if not shape or not shape.get("turnover_known"):
        return ""
    bits = []
    for pos in POSITION_ORDER[:4]:
        row = (shape.get("by_position") or {}).get(pos) or {}
        share = row.get("minutes_share")
        if share is not None:
            bits.append(f"{pos} {round(share * 100)}%")
    if not bits:
        return ""
    return (
        f'<div class="viz-note">Minutes back by line: <span class="num">{esc(" · ".join(bits))}</span></div>'
    )


def keeper_line(last: dict | None, turnover: dict | None) -> str:
    if not last or not last.get("keepers"):
        return ""
    returning = set(turnover.get("returning", [])) if turnover else set()
    departed = set(turnover.get("departed", [])) if turnover else set()
    parts = []
    for keeper in last["keepers"]:
        name = keeper.get("name", "")
        status = ""
        if turnover:
            if name in returning:
                status = ' <span class="tag tag-ret">returns</span>'
            elif name in departed:
                status = ' <span class="tag tag-dep">departed</span>'
        save_pct = keeper.get("save_pct")
        bits = [f"{keeper.get('minutes', 0)}′"]
        if save_pct is not None:
            bits.append(f"{save_pct:.3f} save pct".lstrip("0"))
        if keeper.get("shutouts") is not None:
            bits.append(f"{keeper['shutouts']} CS")
        parts.append(
            f'<span class="keeper"><b>{esc(name)}</b>{status} <span class="num">({" · ".join(bits)})</span></span>'
        )
    return (
        '<div class="keepers"><div class="viz-title">In goal</div>'
        + "".join(parts)
        + "</div>"
    )


def stat_grid(last: dict) -> str:
    overall = last.get("overall", {})
    conf = last.get("conference", {})
    patterns = last.get("patterns") or {}
    shots = patterns.get("shots", {})
    corners = patterns.get("corners", {})
    discipline = last.get("discipline") or {}
    cells = [
        ("Overall", record_line(overall), f"{overall.get('gf')}:{overall.get('ga')}"),
        ("Conference", record_line(conf), f"{conf.get('gf')}:{conf.get('ga')}"),
        ("Clean sheets", str(last.get("clean_sheets", "–")), f"shut out {last.get('times_shut_out', '–')}×"),
        ("One-goal games", str(last.get("one_goal_games", "–")), "margin of one"),
    ]
    if shots:
        cells.append(("Shots for:against", f"{shots.get('for')}:{shots.get('against')}", f"on goal {shots.get('sog_for')}:{shots.get('sog_against')}"))
    if corners:
        cells.append(("Corners", f"{corners.get('for')}:{corners.get('against')}", "for:against"))
    if discipline:
        cells.append(("Cards", f"{discipline.get('yellow')}Y {discipline.get('red')}R", "season total"))
    boxes = "".join(
        f'<div class="stat"><span class="stat-label">{esc(label)}</span>'
        f'<span class="stat-val num">{esc(value)}</span>'
        f'<span class="stat-sub num">{esc(sub)}</span></div>'
        for label, value, sub in cells
    )
    return f'<div class="stats">{boxes}</div>'


def turnover_block(turnover: dict | None, season: int | str) -> str:
    if not turnover:
        return (
            f'<div class="gap">Roster turnover unknown — the {season} roster '
            "has not been published yet.</div>"
        )
    counts = turnover.get("counts", {})
    leaders = turnover.get("departed_leaders") or []
    leader_text = ""
    if leaders:
        led = ", ".join(
            f"{esc(leader['name'])} ({leader['goals']}g, {leader['points']}pts, {leader['minutes']}′)"
            for leader in leaders
        )
        leader_text = f'<div class="departed"><span class="viz-title">Departed production</span> {led}</div>'
    return (
        f'<div class="turnover"><div class="turnover-counts num">'
        f'<span><b>{counts.get("returning")}</b> return</span>'
        f'<span><b>{counts.get("departed")}</b> departed</span>'
        f'<span><b>{counts.get("newcomers")}</b> new</span></div>'
        + share_bars(turnover.get("returning_share"))
        + leader_text
        + "</div>"
    )


def fixtures_line(fixtures: list[dict] | None, focus: str) -> str:
    if not fixtures:
        return ""
    rows = []
    for fixture in fixtures:
        at_home = fixture.get("home") == focus
        where = "HOME" if at_home else "AWAY"
        rows.append(
            f'<span class="fixture"><b class="num">{esc(_long_date(str(fixture.get("date"))))}</b>'
            f' <span class="tag tag-{where.lower()}">{where}</span>'
            f' <span class="dim">{esc(fixture.get("venue", ""))}</span></span>'
        )
    return f'<div class="fixtures"><div class="viz-title">This season</div>{"".join(rows)}</div>'


# ── Player lookups for breakouts and dossiers ────────────────────────────────


def _find_profile(digest: dict, player: str) -> dict | None:
    focus = digest["programmes"][digest["focus"]]
    wanted = player.strip().casefold()
    for profile in focus.get("top_returning") or []:
        if str(profile.get("name", "")).strip().casefold() == wanted:
            return profile
    return None


def _find_keeper(digest: dict, player: str) -> dict | None:
    focus = digest["programmes"][digest["focus"]]
    wanted = player.strip().casefold()
    for keeper in (focus.get("last_season") or {}).get("keepers") or []:
        if str(keeper.get("name", "")).strip().casefold() == wanted:
            return keeper
    return None


def career_table(profile: dict) -> str:
    career = profile.get("career") or []
    if not career:
        return ""
    rows = "".join(
        f'<tr><td class="num">{line.get("season")}</td>'
        f'<td class="num">{line.get("gp", "–")}</td><td class="num">{line.get("gs", "–")}</td>'
        f'<td class="num">{line.get("minutes", "–")}</td><td class="num">{line.get("goals", "–")}</td>'
        f'<td class="num">{line.get("assists", "–")}</td><td class="num">{line.get("points", "–")}</td>'
        f'<td class="num">{line.get("shots", "–")}</td><td class="num">{line.get("sog", "–")}</td></tr>'
        for line in career
    )
    return (
        '<table class="grid slim"><thead><tr><th class="num">Season</th>'
        '<th class="num">GP</th><th class="num">GS</th><th class="num">Min</th>'
        '<th class="num">G</th><th class="num">A</th><th class="num">Pts</th>'
        '<th class="num">Sh</th><th class="num">SOG</th></tr></thead>'
        f"<tbody>{rows}</tbody></table>"
    )


def dossier_sheet(digest: dict, entry: dict) -> str:
    player = entry.get("player", "")
    profile = _find_profile(digest, player)
    keeper = _find_keeper(digest, player) if profile is None else None
    tiles = []

    def tile(value: Any, label: str) -> None:
        tiles.append(
            f'<div class="tile"><span class="tile-val num">{esc(value)}</span>'
            f'<span class="tile-label">{esc(label)}</span></div>'
        )

    meta_bits = []
    if profile:
        last = profile["career"][-1] if profile.get("career") else {}
        for key in ("position", "class_year", "number", "hometown"):
            if profile.get(key):
                meta_bits.append(str(profile[key]))
        tile(last.get("gp", "–"), "Games")
        tile(last.get("goals", "–"), "Goals")
        tile(last.get("assists", "–"), "Assists")
        tile(last.get("points", "–"), "Points")
        tile(last.get("minutes", "–"), "Minutes")
    elif keeper:
        tile(keeper.get("minutes", "–"), "Minutes")
        tile(keeper.get("saves", "–"), "Saves")
        tile(keeper.get("goals_against", "–"), "Goals against")
        if keeper.get("save_pct") is not None:
            tile(f"{keeper['save_pct']:.3f}".lstrip("0"), "Save pct")

    def bullets(items: list[str] | None, cls: str) -> str:
        if not items:
            return ""
        return f'<ul class="{cls}">' + "".join(f"<li>{esc(item)}</li>" for item in items) + "</ul>"

    checks = "".join(
        f'<li class="check">{esc(item)}</li>' for item in entry.get("video_checks") or []
    )
    return f"""
<section class="sheet dossier">
  <div class="sheet-eyebrow">Player dossier · {esc(digest.get("conference", ""))} {esc(digest.get("season", ""))} {label_chip("judgment")}</div>
  <h2 class="dossier-name">{esc(player)}</h2>
  <div class="dossier-meta">{esc(" · ".join(meta_bits))}{" · " if meta_bits and entry.get("role") else ""}{esc(entry.get("role", ""))}</div>
  <div class="tiles tiles-slim">{"".join(tiles)}</div>
  <div class="viz-note">Season line observed from published statistics{f" · {len(profile.get('career') or [])} season(s) held" if profile else ""}. No shot-location data is collected, so shot maps and xG are unavailable rather than estimated.</div>
  {career_table(profile) if profile else ""}
  <div class="dossier-cols">
    <div>
      <div class="viz-title">Strengths {label_chip("judgment")}</div>
      {bullets(entry.get("strengths"), "plain")}
      <div class="viz-title risk">Limitations {label_chip("judgment")}</div>
      {bullets(entry.get("limitations"), "plain risklist")}
    </div>
    <div>
      <div class="viz-title">Fit</div>
      <div class="story">{prose(entry.get("fit"))}</div>
      <div class="viz-title">Coaching question</div>
      <div class="story">{prose(entry.get("question"))}</div>
      {f'<div class="viz-title">Video validation</div><ul class="plain checks">{checks}</ul>' if checks else ""}
    </div>
  </div>
  {f'<div class="verdict"><span class="viz-title">Recommendation</span> {esc(entry.get("verdict"))}</div>' if entry.get("verdict") else ""}
</section>"""


def watchlist_table(entries: list[dict] | None) -> str:
    """Monitoring candidates in one line each — players whose held record
    shows an upward indicator on a sample too small for a full treatment."""
    if not entries:
        return f'<p class="pending">{PLACEHOLDER}</p>'
    rows = "".join(
        f"<tr><td><b>{esc(entry.get('player', ''))}</b></td>"
        f"<td>{esc(entry.get('programme', ''))}</td>"
        f"<td>{esc(entry.get('note', ''))} {label_chip(entry.get('label') or 'judgment')}</td></tr>"
        for entry in entries
    )
    return (
        '<table class="grid slim"><thead><tr><th>Player</th><th>Programme</th>'
        "<th>Why watch</th></tr></thead><tbody>" + rows + "</tbody></table>"
        '<div class="viz-note">Monitoring candidates, not conclusions. The samples behind these '
        "rows are too small to carry a projection. Re-evaluate after the first two matchdays.</div>"
    )


# ── Opponent cards ───────────────────────────────────────────────────────────


def opponent_half_card(
    digest: dict,
    slug: str,
    narrative: dict,
    names: dict[str, str],
    condensed: bool = False,
) -> str:
    """One card per opponent: identity, roster change, key threat, potential
    opening, and the implication for the focus side.  Condensed cards (swing
    tier) drop the news blocks and shorten the head-to-head strip so three
    fit a page.  A field with nothing verified says so."""
    section = digest["programmes"][slug]
    last = section.get("last_season") or {}
    overall = last.get("overall", {})
    conf = last.get("conference", {})
    story = (narrative.get("programmes") or {}).get(slug) or {}
    first_meeting = (section.get("fixtures_vs_focus") or [{}])[0].get("date", "")
    turnover = section.get("turnover") or {}
    share = turnover.get("returning_share") or {}
    counts = turnover.get("counts") or {}
    top = (section.get("top_returning") or [{}])[0]
    top_line = ""
    if top.get("name"):
        last_line = top["career"][-1] if top.get("career") else {}
        top_line = (
            f"<b>{esc(top['name'])}</b> — {last_line.get('goals', 0)}g, "
            f"{last_line.get('points', 0)}pts in {last_line.get('minutes', 0)}′ last season. "
        )
    roster_bits = []
    if counts.get("returning") is not None:
        roster_bits.append(
            f"{counts['returning']} return, {counts.get('newcomers', 0)} new, "
            f"{counts.get('departed', 0)} departed"
        )
    if share.get("minutes") is not None:
        roster_bits.append(f"{round(share['minutes'] * 100)}% of minutes back")
    if share.get("goals") is not None:
        roster_bits.append(f"{round(share['goals'] * 100)}% of goals back")
    roster_line = " · ".join(roster_bits) or "roster not yet published"

    def field(title: str, body: str, cls: str = "") -> str:
        if not body:
            body = "Nothing verified to report."
        return (
            f'<div class="opp-field{" " + cls if cls else ""}">'
            f'<span class="viz-title">{esc(title)}</span>'
            f"<p>{body}</p></div>"
        )

    focus_name = names.get(digest["focus"], digest["focus"])
    tier_word = esc(str(story.get("tier", "priority")).capitalize())
    return f"""
<div class="half-opp{" condensed" if condensed else ""}">
  <header class="opp-head">
    <span class="opp-abbr">{esc(section.get("abbr", slug[:3].upper()))}</span>
    <div>
      <h3>{esc(section.get("name", slug))}</h3>
      <div class="opp-sub num">{record_line(overall)} overall · {record_line(conf)} conf (W-L-T) ·
      {overall.get("gf")}:{overall.get("ga")} · first meeting {esc(_long_date(first_meeting)) if first_meeting else "TBD"}</div>
    </div>
    <span class="prio">{tier_word}</span>
  </header>
  {field("Roster change", esc(story.get("roster_note", "")) + f'<span class="dim"> [{esc(roster_line)}]</span>')}
  {shape_line(section)}
  {field("Key threat", top_line + esc(story.get("threat", "")))}
  {field("Potential opening", esc(story.get("vulnerability", "")), "riskfield")}
  {field(f"Implication for {esc(focus_name)}", esc(story.get("implication", "")), "goldfield")}
  {news_cards(story.get("news")) if not condensed else ""}
  {h2h_strip(section.get("head_to_head"), names, digest["focus"], limit=4 if condensed else 6)}
</div>"""


def compact_card(digest: dict, slug: str, narrative: dict, names: dict[str, str]) -> str:
    section = digest["programmes"][slug]
    last = section.get("last_season") or {}
    overall = last.get("overall", {})
    conf = last.get("conference", {})
    story = (narrative.get("programmes") or {}).get(slug) or {}
    turnover = section.get("turnover") or {}
    share = (turnover.get("returning_share") or {}).get("goals")
    versus = section.get("head_to_head")
    top = (section.get("top_returning") or [{}])[0]
    top_line = ""
    if top.get("name"):
        last_line = top["career"][-1] if top.get("career") else {}
        top_line = (
            f'<div class="compact-line"><span class="viz-title">Top returner</span> '
            f"<b>{esc(top['name'])}</b> — {last_line.get('goals', 0)}g, "
            f"{last_line.get('points', 0)}pts in {last_line.get('minutes', 0)}′</div>"
        )
    takeaway = story.get("implication") or ""
    return f"""
<div class="compact">
  <div class="compact-head"><span class="opp-abbr sm">{esc(section.get("abbr", slug[:3].upper()))}</span>
    <b>{esc(section.get("name", slug))}</b>
    <span class="num dim">{record_line(overall)} · conf {record_line(conf)} (W-L-T) · {overall.get("gf")}:{overall.get("ga")}</span></div>
  <div class="compact-line"><span class="viz-title">Returning goals</span>
    <span class="num">{f"{round(share * 100)}%" if share is not None else "roster pending"}</span>
    · <span class="viz-title">H2H</span> <span class="num">{record_line(versus) if versus else "–"}</span></div>
  {top_line}
  {f'<div class="compact-note">{esc(takeaway)}</div>' if takeaway else ""}
</div>"""


# ── Sheets ───────────────────────────────────────────────────────────────────


def _names(digest: dict) -> dict[str, str]:
    return {slug: section.get("name", slug) for slug, section in digest["programmes"].items()}


def _schedule_order(digest: dict) -> list[str]:
    def first_date(slug: str) -> str:
        fixtures = digest["programmes"][slug].get("fixtures_vs_focus") or []
        return str(fixtures[0]["date"]) if fixtures else "9999"

    opponents = [slug for slug in digest["programmes"] if slug != digest["focus"]]
    return sorted(opponents, key=first_date)


def exec_sheet(digest: dict, narrative: dict) -> str:
    """One page: bottom line → three findings, each split evidence / meaning /
    implication → three decisions.  Priorities render on the roster-decisions
    page, not here — the brief states conclusions once.
    """
    exec_block = narrative.get("exec") or {}
    findings = (exec_block.get("findings") or [])[:3]
    decisions = (exec_block.get("decisions") or [])[:3]
    bottom = exec_block.get("bottom_line")
    finding_rows = "".join(
        f'<li><div class="ev-row"><span class="ev">{esc(item.get("evidence", ""))}</span>'
        f'<span class="ev-tags">{label_chip(item.get("label"))}{confidence_dot(item.get("confidence"))}</span></div>'
        f'<div class="f-grid"><span class="f-label">Meaning</span>'
        f'<span>{esc(item.get("meaning", ""))}</span>'
        + (
            f'<span class="f-label">For the staff</span><span>{esc(item["implication"])}</span>'
            if item.get("implication")
            else ""
        )
        + "</div></li>"
        for item in findings
    ) or f'<li class="pending">{PLACEHOLDER}</li>'
    decision_rows = "".join(
        f'<div class="decision"><span class="decision-n num">{index}</span>'
        f'<div><b>{esc(item.get("title", ""))}</b><p>{esc(item.get("text", ""))}</p></div></div>'
        for index, item in enumerate(decisions, start=1)
    ) or f'<p class="pending">{PLACEHOLDER}</p>'
    bottom_block = (
        f'<div class="bottomline"><span class="viz-title">Bottom line</span>'
        f"<p>{esc(bottom)}</p></div>"
        if bottom
        else f'<p class="pending">{PLACEHOLDER}</p>'
    )
    return f"""
<section class="sheet">
  <h2 class="section-head">Executive brief</h2>
  {bottom_block}
  {indicator_tiles(digest)}
  <div class="viz-title big">Findings</div>
  <ol class="findings split">{finding_rows}</ol>
  <div class="viz-title big">Decisions</div>
  <div class="decision-row">{decision_rows}</div>
</section>"""


def sources_sheet(digest: dict, focus_name: str) -> str:
    file_count = len(digest.get("sources") or {})
    seasons = digest.get("seasons_held") or ["–"]
    labels = (
        (label_chip("observed"), "Computed directly from published schedules, rosters, statistics, and play-by-play."),
        (label_chip("projected"), "A model estimate with stated assumptions."),
        (label_chip("signal"), "An observed pattern whose cause is unverified and needs confirmation."),
        (label_chip("judgment"), "Interpretation that needs film or coaching context to validate."),
    )
    label_rows = "".join(
        f'<span class="d-term">{chip}</span><span>{esc(text)}</span>' for chip, text in labels
    )
    definitions = (
        ("Records", "Wins-losses-ties (W-L-T) throughout."),
        ("Statistics", "As published by each programme's official statistics page."),
        ("Save percentage", "Saves ÷ (saves + goals against)."),
        ("Returning share", "Last season's production from players on the new roster, joined by name."),
        ("Goal timing", "Published play-by-play; charts state their match sample."),
        ("Head-to-head", f"Seasons held in the archive ({seasons[0]}–{seasons[-1]}) only; a held record, not an all-time one."),
        ("xG", "Not reported; shot locations are not collected."),
        ("Collection record", f"{file_count} season files with collection dates, published separately as the technical appendix."),
    )
    definition_rows = "".join(
        f'<span class="f-label">{esc(term)}</span><span>{esc(text)}</span>'
        for term, text in definitions
    )
    return f"""
<section class="sheet">
  <h2 class="section-head">Sources, definitions, and method</h2>
  <div class="viz-title big">Evidence labels</div>
  <div class="f-grid def-grid">{label_rows}</div>
  <div class="viz-title big">Definitions</div>
  <div class="f-grid def-grid">{definition_rows}</div>
  <div class="foot-note">
    <p>Independent analysis by <b>EDInsights</b> from public, published data · not issued by or
    affiliated with {esc(focus_name)} University Athletics · no institutional marks are used</p>
  </div>
</section>"""


def render_appendix(digest: dict) -> str:
    """The technical appendix — the collection record, out of the coach's way."""
    source_rows = "".join(
        f'<tr><td>{esc(key)}</td><td class="num">{esc(str(value)[:10])}</td></tr>'
        for key, value in sorted((digest.get("sources") or {}).items())
    )
    title = (
        f"{digest.get('conference', '')} {digest.get('gender', '')} "
        f"{digest.get('season', '')} — Technical appendix"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style>
</head>
<body>
<section class="sheet">
  <h2 class="section-head">Technical appendix — collection record</h2>
  <p class="section-sub">Every season file behind the preseason briefing, with its collection
  date. Digest generated {esc(str(digest.get("generated_at", ""))[:10])}.</p>
  <table class="grid slim sources"><thead><tr><th>Season file</th><th class="num">Collected</th></tr></thead>
  <tbody>{source_rows}</tbody></table>
</section>
</body>
</html>"""


def render_report(digest: dict, narrative: dict | None = None) -> str:
    narrative = narrative or {}
    names = _names(digest)
    focus_slug = digest["focus"]
    focus = digest["programmes"][focus_slug]
    focus_name = names.get(focus_slug, focus_slug)
    seasons = digest.get("seasons_held") or []
    span = f"{seasons[0]}–{seasons[-1]}" if seasons else "–"
    generated = str(digest.get("generated_at", ""))[:10]
    gender_word = "Men's" if digest.get("gender") == "men" else "Women's"
    focus_last = focus.get("last_season") or {}
    focus_story = narrative.get("focus") or {}

    programme_stories = narrative.get("programmes") or {}
    ordered = _schedule_order(digest)

    def tier_of(slug: str) -> str | None:
        story = programme_stories.get(slug) or {}
        tier = str(story.get("tier") or "").strip().lower()
        if tier in ("benchmark", "swing", "update"):
            return tier
        if story.get("priority"):
            return "benchmark"
        return None

    benchmark = [slug for slug in ordered if tier_of(slug) == "benchmark"]
    swing = [slug for slug in ordered if tier_of(slug) == "swing"]
    update = [slug for slug in ordered if tier_of(slug) == "update"]
    untiered = [slug for slug in ordered if tier_of(slug) is None]

    exec_block = narrative.get("exec") or {}
    questions = "".join(
        f'<li class="check">{esc(item)}</li>' for item in narrative.get("questions") or []
    ) or f'<li class="pending">{PLACEHOLDER}</li>'
    priorities = "".join(
        f"<li>{esc(item)}</li>" for item in exec_block.get("priorities") or []
    )
    extrapolated = (
        '<p class="caveat">Conference membership for this season is carried forward from the '
        "last authored year and not yet confirmed.</p>"
        if digest.get("membership_extrapolated")
        else ""
    )

    sheets: list[str] = []

    sheets.append(f"""<section class="sheet cover">
  <div class="cover-eyebrow">Prepared for {esc(focus_name)} {gender_word} Soccer</div>
  <h1>{esc(digest.get("conference", ""))} {gender_word} Soccer<br><span class="cover-season num">{esc(digest.get("season", ""))} Preseason Intelligence</span></h1>
  <div class="cover-rule"></div>
  {f'<p class="headline">{esc(narrative.get("headline", ""))}</p>' if narrative.get("headline") else ""}
  {extrapolated}
  <div class="cover-bottom">
    <div class="cover-meta num">Prepared {esc(_long_date(generated))} · seasons {esc(span)} · published data only</div>
    <div class="cover-mark">EDInsights <span>Independent analysis</span></div>
  </div>
</section>""")

    sheets.append(exec_sheet(digest, narrative))

    sheets.append(f"""<section class="sheet">
  <h2 class="section-head">{esc(focus_name)} — the view from outside</h2>
  <p class="section-sub">The numbers and patterns an opposing staff preparing for
  {esc(focus_name)} will read.</p>
  {stat_grid(focus_last)}
  <div class="two-col">
    <div>{minute_chart(focus_last.get("patterns"))}</div>
    <div>{turnover_block(focus.get("turnover"), digest.get("season", ""))}{keeper_line(focus_last, focus.get("turnover"))}</div>
  </div>
  <div class="story">{prose(focus_story.get("overview"))}</div>
  {news_cards(focus_story.get("news"))}
  {offseason_ledger(focus_story.get("offseason"))}
</section>""")

    sheets.append(f"""<section class="sheet">
  <h2 class="section-head">{esc(focus_name)} — roster decisions and preseason scorecard</h2>
  <p class="section-sub">The squad as published, line by line, joined to last season's
  minutes.</p>
  {shape_strip(focus)}
  <div class="viz-title big">The read, line by line</div>
  {roster_read(focus_story.get("roster"))}
  {availability_block(focus_last)}
  {usage_block(focus)}
  {f'<div class="viz-title big">Preseason priorities</div><ul class="plain">{priorities}</ul>' if priorities else ""}
  <div class="viz-title big">Preseason scorecard</div>
  <ul class="plain checks">{questions}</ul>
</section>""")

    sheets.append(f"""<section class="sheet">
  <h2 class="section-head">The landscape — and where {esc(focus_name)} gains ground</h2>
  {landscape_table(digest)}
  <p class="section-sub">Observed per-match rates against the conference median. These gaps are
  the controllable ones.</p>
  {dumbbell_chart(digest)}
  <div class="story">{prose(narrative.get("landscape"))}</div>
</section>""")

    sheets.append(f"""<section class="sheet">
  <h2 class="section-head">Schedule and workload</h2>
  {schedule_matrix(digest, names, narrative)}
</section>""")

    for index in range(0, len(benchmark), 2):
        head = "Benchmark opponents" if index == 0 else "Benchmark opponents, continued"
        cards = "".join(
            opponent_half_card(digest, slug, narrative, names)
            for slug in benchmark[index : index + 2]
        )
        sheets.append(
            f'<section class="sheet opponent"><h2 class="section-head">{head}</h2>'
            '<p class="section-sub">The sides that set the standard this season.</p>'
            f"{cards}</section>"
        )

    update_cards = "".join(
        f'<div class="update-card"><b>{esc(digest["programmes"][slug].get("name", slug))}</b> '
        f'<span class="tag tag-away">update required</span>'
        f"<p>{esc((programme_stories.get(slug) or {}).get('roster_note', ''))} "
        f"{esc((programme_stories.get(slug) or {}).get('implication', ''))}</p></div>"
        for slug in update
    )
    for index in range(0, len(swing), 3):
        head = "Swing matches" if index == 0 else "Swing matches, continued"
        cards = "".join(
            opponent_half_card(digest, slug, narrative, names, condensed=True)
            for slug in swing[index : index + 3]
        )
        tail = update_cards if index + 3 >= len(swing) else ""
        sheets.append(
            f'<section class="sheet opponent"><h2 class="section-head">{head}</h2>'
            '<p class="section-sub">The winnable fixtures that will decide the season.</p>'
            f"{cards}{tail}</section>"
        )
    if update and not swing:
        sheets.append(
            '<section class="sheet"><h2 class="section-head">Awaiting data</h2>'
            f"{update_cards}</section>"
        )

    if untiered:
        compact_cards = "".join(
            compact_card(digest, slug, narrative, names) for slug in untiered
        )
        sheets.append(
            '<section class="sheet"><h2 class="section-head">The rest of the conference</h2>'
            f"{compact_cards}</section>"
        )

    sheets.append(f"""<section class="sheet">
  <h2 class="section-head">Watchlist — the conference and {esc(focus_name)}</h2>
  <p class="section-sub">Players whose held record or verified offseason deserves tracking.</p>
  {watchlist_table(narrative.get("watchlist"))}
</section>""")

    for entry in narrative.get("dossiers") or []:
        sheets.append(dossier_sheet(digest, entry))

    sheets.append(sources_sheet(digest, focus_name))

    brand = (
        f"EDInsights · {esc(digest.get('season', ''))} {esc(digest.get('conference', ''))} "
        "Preseason Intelligence"
    )
    total = len(sheets)
    numbered = [
        sheet.replace(
            "</section>",
            f'<footer class="sheet-foot"><span>{brand}</span>'
            f'<span class="num">{page} / {total}</span></footer></section>',
            1,
        )
        for page, sheet in enumerate(sheets, start=1)
    ]

    body = "\n\n".join(numbered)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(digest.get("conference", ""))} {esc(digest.get("gender", ""))} {esc(digest.get("season", ""))} — Preseason Briefing · {esc(focus_name)}</title>
<style>{CSS}</style>
</head>
<body>

{body}

</body>
</html>"""


CSS = """
:root{
--paper:#ececea;--sheet:#ffffff;--ink:#1c1c1c;--ink2:#3d3d3d;
--muted:#686868;--faint:#979792;--rule:#e4e4e0;--rule2:#c9c9c3;
--gold:#2f5d8a;--gold-fill:#6d94b8;--gold-wash:#eef3f8;
--rose:#a03a4e;--rose-wash:#f6e9ec;--bench:#8b8b85;
--win:#2e7d4f;--loss:#a03a4e;--draw:#8a7a2a;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--paper);color:var(--ink);
font:14.5px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
-webkit-font-smoothing:antialiased}
.num{font-variant-numeric:tabular-nums}
.dim{color:var(--faint)}
a{color:var(--gold)}
.sheet{background:var(--sheet);max-width:850px;margin:26px auto;padding:52px 58px;
box-shadow:0 1px 4px rgba(60,50,20,.14),0 8px 28px rgba(60,50,20,.08);
page-break-after:always}

.cover{display:flex;flex-direction:column;padding-top:150px;min-height:920px}
.cover-eyebrow{font:700 12px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.24em;text-transform:uppercase;color:var(--gold);margin-bottom:22px}
.cover h1{font:700 54px/1.04 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;letter-spacing:.005em}
.cover-season{color:var(--ink2)}
.cover-rule{height:3px;background:var(--gold-fill);margin:30px 0;width:180px}
.headline{font-size:17.5px;line-height:1.6;max-width:56ch;color:var(--ink2);
border-left:3px solid var(--gold-fill);padding-left:18px;margin:20px 0}
.cover-bottom{margin-top:auto;display:flex;justify-content:space-between;align-items:baseline;
border-top:1px solid var(--rule);padding-top:14px}
.cover-meta{font-size:12px;color:var(--muted)}
.cover-mark{font:700 13px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.16em;text-transform:uppercase;color:var(--ink2)}
.cover-mark span{color:var(--faint);font-size:10px;letter-spacing:.12em;margin-left:8px}

.section-head{font:700 23px/1.1 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;letter-spacing:.04em;margin:0 0 16px;
border-bottom:2px solid var(--gold-fill);padding-bottom:8px}
.section-sub{color:var(--muted);margin:-6px 0 14px;font-size:13px}

.lbl{font:700 8.5px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;letter-spacing:.1em;
text-transform:uppercase;padding:3px 6px;border-radius:2px;vertical-align:1.5px;white-space:nowrap}
.lbl-observed{background:var(--gold-wash);color:var(--gold);border:1px solid var(--gold-fill)}
.lbl-projected{background:#eeece5;color:var(--bench);border:1px solid var(--rule2)}
.lbl-signal{background:#ece7f0;color:#5e5375;border:1px solid #b9aecb}
.lbl-judgment{background:var(--rose-wash);color:var(--rose);border:1px solid #d9aab6}
.conf{font:700 9px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;letter-spacing:.08em;
text-transform:uppercase;margin-left:6px;padding-left:12px;position:relative;color:var(--muted)}
.conf::before{content:"";position:absolute;left:0;top:1px;width:8px;height:8px;border-radius:50%}
.conf-high::before{background:var(--gold-fill)}
.conf-medium::before{background:var(--bench)}
.conf-low::before{background:#d4cdbb}

.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin:6px 0 6px}
.tiles-slim{grid-template-columns:repeat(auto-fit,minmax(96px,1fr))}
.tile{border:1px solid var(--rule2);border-top:3px solid var(--gold-fill);padding:12px 14px;
background:var(--sheet)}
.tile-val{display:block;font:700 30px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;color:var(--gold)}
.tiles-slim .tile-val{font-size:24px}
.tile-label{display:block;font:700 10px/1.3 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.1em;text-transform:uppercase;color:var(--ink2);margin-top:6px}
.tile-sub{display:block;font-size:11px;color:var(--faint)}

.findings{margin:6px 0 18px 22px}
.findings li{margin:9px 0;font-size:14px;max-width:72ch}
.bottomline{border-left:4px solid var(--gold);background:var(--gold-wash);
padding:12px 16px;margin:4px 0 16px}
.bottomline .viz-title{margin:0 0 4px;color:var(--gold)}
.bottomline p{font-size:15px;line-height:1.5;color:var(--ink);max-width:68ch}
.findings.split li{margin:0;padding:15px 0;border-bottom:1px solid var(--rule)}
.findings.split li:last-child{border-bottom:none}
.ev-row{display:flex;gap:16px;align-items:baseline;justify-content:space-between}
.findings.split .ev{font-weight:600;font-size:14px;max-width:64ch}
.ev-tags{white-space:nowrap;flex:none}
.f-grid{display:grid;grid-template-columns:92px minmax(0,1fr);gap:7px 14px;margin-top:9px}
.f-label{font:700 9.5px/1.7 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.f-grid > span:not(.f-label){font-size:13px;line-height:1.55;color:var(--ink2);max-width:68ch}
.exec-cols{display:grid;grid-template-columns:1.4fr 1fr;gap:26px}
@media(max-width:700px){.exec-cols{grid-template-columns:1fr}}
.decision{display:flex;gap:12px;margin:12px 0}
.decision-n{flex:none;width:26px;height:26px;background:var(--gold-fill);color:#fff;
display:inline-flex;align-items:center;justify-content:center;
font:700 14px/1 "Avenir Next Condensed","Arial Narrow",sans-serif}
.decision p{font-size:13px;color:var(--ink2);margin-top:2px}
.risk{color:var(--rose)}
.risklist li{margin:8px 0;font-size:13px;color:var(--ink2)}
.plain{list-style:none;margin:4px 0}
.plain li{padding-left:14px;position:relative;margin:6px 0;font-size:13px}
.plain li::before{content:"—";position:absolute;left:0;color:var(--gold-fill)}
.risklist li::before{color:var(--rose)}
.checks li::before{content:"☐";color:var(--muted)}

.grid{width:100%;border-collapse:collapse;font-size:13px;margin:4px 0}
.grid th{font:700 10.5px/1.4 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.09em;text-transform:uppercase;color:var(--muted);text-align:left;
padding:7px 9px;border-bottom:2px solid var(--rule2)}
.grid td{padding:7px 9px;border-bottom:1px solid var(--rule)}
.grid th.num,.grid td.num{text-align:right}
.grid tr.is-focus td{background:var(--gold-wash)}
.grid tr.is-focus td:first-child{box-shadow:inset 3px 0 0 var(--gold-fill)}
.abbr{color:var(--faint);font-size:11px;margin-left:4px}
.player-meta{display:block;color:var(--faint);font-size:11px}
.grid.slim{font-size:12.5px}
.grid.sources{max-width:430px}
.mini-track{display:inline-block;width:84px;height:7px;background:var(--rule);
border-radius:4px;overflow:hidden;vertical-align:2px;margin-right:8px}
.mini-fill{display:block;height:100%;background:var(--gold-fill)}
.share-cell{white-space:nowrap}
.streak{font-weight:700}

.opponent{padding-top:44px}
.half-opp{border-top:2px solid var(--rule2);padding:16px 0 8px;margin-top:14px}
.half-opp:first-of-type{border-top:none;margin-top:0}
.half-opp h3{font:700 21px/1.05 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;letter-spacing:.02em}
.opp-field{margin:9px 0}
.opp-field .viz-title{margin:0 0 2px}
.opp-field p{font-size:13px;color:var(--ink2);max-width:76ch}
.riskfield .viz-title{color:var(--rose)}
.goldfield{border-left:3px solid var(--gold-fill);padding-left:12px}
.goldfield .viz-title{color:var(--gold)}
.prio-mini{font:700 8.5px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.1em;text-transform:uppercase;color:var(--gold);
border:1px solid var(--gold-fill);padding:2px 5px;margin-left:6px;vertical-align:1px}
.tight{color:var(--rose);font-weight:700}
.opp-head{display:flex;align-items:center;gap:16px;margin-bottom:16px}
.opp-abbr{display:inline-flex;align-items:center;justify-content:center;
min-width:54px;height:54px;padding:0 8px;background:var(--gold-wash);border:1px solid var(--gold-fill);
font:700 18px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;color:var(--gold)}
.opp-abbr.sm{min-width:38px;height:38px;font-size:13px}
.opp-head h2{font:700 26px/1.05 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;letter-spacing:.02em}
.opp-sub{color:var(--muted);font-size:12px;margin-top:3px}
.prio{margin-left:auto;font:700 10px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.12em;text-transform:uppercase;color:var(--gold);
border:1px solid var(--gold-fill);padding:5px 8px}

.stats{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;gap:7px;margin:0 0 16px}
@media(max-width:700px){.stats{grid-auto-flow:row;grid-template-columns:repeat(3,1fr)}}
.stat{background:var(--gold-wash);padding:8px 9px;border:1px solid var(--rule2);min-width:0}
.stat-label{display:block;font:700 9px/1.3 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.08em;text-transform:uppercase;color:var(--muted);white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}
.stat-val{display:block;font-size:17px;font-weight:700;margin-top:2px;white-space:nowrap}
.stat-sub{display:block;font-size:10.5px;color:var(--faint);white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}

.two-col{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:20px;margin:2px 0 14px}
@media(max-width:700px){.two-col{grid-template-columns:1fr}}
.viz-title{font:700 10.5px/1.4 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:10px 0 6px}
.viz-title.big{font-size:12px;margin-top:18px;color:var(--ink2)}
.viz-note{font-size:11px;color:var(--faint);margin-top:4px}
.minutes svg,.dumbbell svg,.scatter svg{width:100%;height:auto;display:block}
.axis{stroke:var(--rule2);stroke-width:1}
.axis-label{font:700 9px "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.12em;fill:var(--faint)}
.axis-title{font:700 10px "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.08em;fill:var(--muted);text-anchor:middle}
.band-label{font-size:9.5px;fill:var(--faint);text-anchor:middle}
.bar-for{fill:var(--gold-fill)}
.bar-against{fill:#c06a7c}
.bar-num{font-size:10px;fill:var(--ink2);text-anchor:middle}

.db-label{font-size:11.5px;fill:var(--ink2)}
.db-track{stroke:var(--rule);stroke-width:2}
.db-join{stroke:var(--rule2);stroke-width:2}
.db-med{fill:var(--bench)}
.db-own{fill:var(--gold-fill)}
.db-own-bad{fill:var(--rose)}
.db-colhead{font:700 9px "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.1em;text-transform:uppercase;fill:var(--faint)}
.db-num{font-size:11.5px;font-weight:700}
.db-own-t{fill:var(--gold)}
.db-own-bad-t{fill:var(--rose)}
.db-mednum{font-size:10.5px;fill:var(--bench)}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;vertical-align:-1px}
.dot-own{background:var(--gold-fill)}
.dot-bad{background:var(--rose)}
.dot-med{background:var(--bench)}

.sc-pt{fill:var(--bench)}
.sc-own{fill:var(--gold-fill);stroke:var(--gold);stroke-width:1.5}
.sc-label{font-size:10.5px;fill:var(--muted)}
.sc-label-own{fill:var(--gold);font-weight:700}

.share-row{display:flex;align-items:center;gap:8px;margin:4px 0}
.share-label{width:56px;font-size:11px;color:var(--muted)}
.share-track{flex:1;height:8px;background:var(--rule);border-radius:4px;overflow:hidden}
.share-fill{display:block;height:100%;background:var(--gold-fill)}
.share-num{width:36px;text-align:right;font-size:11.5px}
.turnover-counts{display:flex;gap:16px;font-size:12.5px;color:var(--ink2);margin-bottom:4px}
.turnover-counts b{font-size:16px;color:var(--ink)}
.departed{font-size:12px;color:var(--ink2);margin-top:8px}
.departed .viz-title{display:block}
.gap{background:var(--gold-wash);border:1px dashed var(--rule2);color:var(--muted);
padding:10px 12px;font-size:12.5px;margin:8px 0}
.keepers{margin-top:10px}
.keeper{display:block;font-size:12.5px;color:var(--ink2);margin:2px 0}
.tag{font:700 9px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;letter-spacing:.08em;
text-transform:uppercase;padding:3px 6px;border-radius:2px;vertical-align:1px}
.tag-ret{background:#e2efe6;color:var(--win)}
.tag-dep{background:var(--rose-wash);color:var(--rose)}
.tag-home{background:var(--gold-wash);color:var(--gold);border:1px solid var(--gold-fill)}
.tag-away{background:#eeece5;color:var(--muted);border:1px solid var(--rule2)}

.h2h{margin:14px 0 4px}
.h2h-rec{font-weight:700}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:inline-flex;align-items:center;gap:5px;background:var(--sheet);
border:1px solid var(--rule2);padding:4px 8px;font-size:11px;color:var(--ink2)}
.chip b{font-size:11px}
.chip i{font-style:normal;color:var(--faint);font-size:10px}
.chip-w{border-left:3px solid var(--win)}.chip-w b{color:var(--win)}
.chip-l{border-left:3px solid var(--loss)}.chip-l b{color:var(--loss)}
.chip-d{border-left:3px solid var(--draw)}.chip-d b{color:var(--draw)}

.fixtures{margin:12px 0 4px}
.fixture{display:inline-flex;align-items:center;gap:8px;margin-right:18px;font-size:12.5px}

.story{margin:12px 0 4px;max-width:70ch}
.story p{margin:8px 0;color:var(--ink2);font-size:13.5px}
.pending{color:var(--faint);font-style:italic}
.news{background:var(--gold-wash);border-left:3px solid var(--gold-fill);padding:10px 14px;margin:10px 0}
.news-tag{font:700 9px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.14em;text-transform:uppercase;color:var(--gold)}
.news p{margin:5px 0 4px;font-size:13px}
.news-cite{font-size:11px;color:var(--faint)}
.ledger{margin:14px 0 4px}
.ledger-row{display:grid;grid-template-columns:150px 1fr;gap:2px 14px;
padding:8px 0;border-bottom:1px solid var(--rule);font-size:12.5px}
.ledger-row span{color:var(--ink2)}
.ledger-cite{grid-column:2;font-size:11px;color:var(--faint)}
@media(max-width:700px){.ledger-row{grid-template-columns:1fr}.ledger-cite{grid-column:1}}
.takeaways{margin:14px 0 2px;background:var(--gold-wash);border:1px solid var(--rule2);padding:10px 14px}
.takeaways ul{margin:2px 0 2px 18px}
.takeaways li{margin:5px 0;font-size:13px}

.compact{border:1px solid var(--rule2);border-left:3px solid var(--gold-fill);
padding:12px 16px;margin:12px 0;background:var(--sheet)}
.compact-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.compact-head b{font:700 16px/1.1 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase}
.compact-line{font-size:12.5px;color:var(--ink2);margin-top:6px}
.compact-line .viz-title{display:inline;margin:0}
.compact-note{font-size:12.5px;color:var(--ink2);margin-top:6px;font-style:italic}

.breakout{border:1px solid var(--rule2);padding:14px 18px;margin:12px 0}
.breakout-head{display:flex;align-items:center;gap:10px}
.breakout-head b{font:700 17px/1.1 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase}

.dossier-name{font:700 34px/1.05 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;margin-top:6px}
.sheet-eyebrow{font:700 11px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.2em;text-transform:uppercase;color:var(--gold)}
.dossier-meta{color:var(--muted);font-size:13px;margin:4px 0 12px}
.dossier-cols{display:grid;grid-template-columns:1fr 1fr;gap:26px;margin-top:10px}
@media(max-width:700px){.dossier-cols{grid-template-columns:1fr}}
.verdict{margin-top:18px;border:2px solid var(--gold-fill);padding:12px 16px;font-size:14px}
.verdict .viz-title{display:block;color:var(--gold)}

.sheet-foot{display:flex;justify-content:space-between;margin-top:34px;
border-top:1px solid var(--rule);padding-top:8px;
font:700 9.5px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.12em;text-transform:uppercase;color:var(--faint)}
.decision-row{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin-top:4px}
@media(max-width:700px){.decision-row{grid-template-columns:1fr}}
.half-opp.condensed{padding:12px 0 6px}
.half-opp.condensed .opp-field{margin:6px 0}
.half-opp.condensed h3{font-size:18px}
.update-card{border:1px dashed var(--rule2);padding:10px 14px;margin:14px 0 4px}
.update-card b{font:700 15px/1.1 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;margin-right:8px}
.update-card p{font-size:12.5px;color:var(--ink2);margin-top:4px;max-width:76ch}
.squadmap{margin:4px 0 10px;max-width:640px}
.sq-row{display:flex;align-items:center;gap:14px;padding:7px 0;border-bottom:1px solid var(--rule)}
.sq-row:last-of-type{border-bottom:none}
.sq-label{flex:none;width:118px;font-size:13px}
.sq-label em{display:block;font-style:normal;font-size:10.5px;color:var(--faint)}
.sq-units{flex:1;display:flex;align-items:center;gap:3px;flex-wrap:wrap}
.unit{display:inline-block;width:13px;height:19px;border-radius:2px}
.u-fr{background:#dde7f0;box-shadow:inset 0 0 0 1px #b5cadd}
.u-so{background:#b5cadd}
.u-jr{background:#6d94b8}
.u-sr{background:#2f5d8a}
.u-x{background:var(--rule);box-shadow:inset 0 0 0 1px var(--rule2)}
.sq-div{width:1.5px;height:24px;background:var(--ink2);margin:0 5px;flex:none}
.sq-share{flex:none;width:130px;text-align:right;font-size:11.5px;white-space:nowrap}
.sq-legend{display:flex;align-items:center;gap:12px;margin-top:8px;flex-wrap:wrap}
.lg{display:inline-flex;align-items:center;gap:4px;font-size:10.5px;color:var(--muted)}
.lg .unit{width:10px;height:14px}
.lg-note{font-size:10.5px;color:var(--faint)}
.roster-grid{margin:6px 0 14px;max-width:76ch}
.roster-grid .f-label{padding-top:1px}
.caveat{color:var(--draw);margin:10px 0;font-size:12.5px}
.foot-note{margin-top:30px;border-top:1px solid var(--rule2);padding-top:12px;
font-size:11.5px;color:var(--faint)}
.foot-note b{color:var(--muted)}
.def-grid{grid-template-columns:130px minmax(0,1fr);gap:9px 16px;max-width:78ch;margin:4px 0 10px}
.def-grid .d-term{padding-top:1px}
.def-grid > span:not(.f-label):not(.d-term){font-size:13px;color:var(--ink2)}

@page{size:letter;margin:0.5in}
@media print{
body{background:#fff}
.sheet{box-shadow:none;margin:0;max-width:none;padding:0.1in 0.2in}
a{color:var(--ink);text-decoration:none}
}
"""
