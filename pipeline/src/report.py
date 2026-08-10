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

Narrative contract (``touchline.report-narrative/2``)::

    {
      "schema": "touchline.report-narrative/2",
      "headline": str,
      "exec": {
        "findings":      [{"text": str, "label": LABEL, "confidence": CONF}],
        "decisions":     [{"title": str, "text": str}],
        "uncertainties": [str]
      },
      "landscape": str,
      "gain": str,
      "focus": {"overview": str, "takeaways": [str], "news": [NEWS],
                 "offseason": [LEDGER]},
      "programmes": {slug: {"overview": str, "takeaways": [str],
                             "news": [NEWS], "priority": bool}},
      "breakouts": [{"player": str, "text": str, "label": LABEL}],
      "dossiers":  [{"player": str, "role": str, "verdict": str,
                     "strengths": [str], "limitations": [str], "fit": str,
                     "question": str, "video_checks": [str]}],
      "questions": [str]
    }
    LABEL = "observed" | "projected" | "judgment"
    CONF  = "high" | "medium" | "low"
    NEWS   = {"text", "source", "url", "date"}
    LEDGER = {"player", "text", "source"?, "url"?, "date"?}

Paragraph breaks in prose are blank lines.
"""

from __future__ import annotations

import html
from statistics import median
from typing import Any

MINUTE_BANDS = ("0-15", "15-30", "30-45", "45-60", "60-75", "75-90", "90+")

PLACEHOLDER = (
    "Narrative pending — the report workflow has not written this section yet."
)

LABEL_NAMES = {
    "observed": "Observed",
    "projected": "Projected",
    "judgment": "Scouting judgment",
}


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def record_line(rec: dict) -> str:
    return f"{rec.get('wins', 0)}-{rec.get('draws', 0)}-{rec.get('losses', 0)}"


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


def _streak(versus: dict | None) -> str:
    """Current run of identical results from the focus side, e.g. ``L5``."""
    meetings = (versus or {}).get("meetings") or []
    if not meetings:
        return "–"
    last = meetings[-1].get("focus_result")
    count = 0
    for meeting in reversed(meetings):
        if meeting.get("focus_result") != last:
            break
        count += 1
    return f"{last}{count}"


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
        tile(record_line(conf), f"{last.get('season')} conference", f"{conf.get('gf')}:{conf.get('ga')} goals")
    return (
        f'<div class="tiles">{"".join(tiles)}</div>'
        '<div class="viz-note">All four indicators observed — computed from published '
        "rosters, statistics, and results.</div>"
    )


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
        f'<div class="viz-note">Goals by minute of match · observed over {counted} of {total} '
        "matches with a held box score · goal times from published play-by-play</div>"
        if counted is not None
        else ""
    )
    return f'<div class="minutes">{"".join(parts)}{coverage}</div>'


def dumbbell_chart(digest: dict) -> str:
    """Focus vs conference median on observed per-match rates."""
    focus_rates = _programme_rates(digest["programmes"][digest["focus"]])
    if not focus_rates:
        return ""
    all_rates = [
        rates
        for slug, section in digest["programmes"].items()
        if (rates := _programme_rates(section)) is not None
    ]
    metrics = (
        ("shots_for", "Shots taken /match", "higher is better"),
        ("shots_against", "Shots faced /match", "lower is better"),
        ("corners_for", "Corners won /match", "higher is better"),
        ("corners_against", "Corners conceded /match", "lower is better"),
        ("second_half_ga_pct", "Share of GA after halftime, %", "lower is better"),
        ("late_ga_pct", "Share of GA from 75′ on, %", "lower is better"),
    )
    rows = []
    for key, label, direction in metrics:
        own = focus_rates.get(key)
        pool = [rates[key] for rates in all_rates if rates.get(key) is not None]
        if own is None or not pool:
            continue
        rows.append((label, direction, own, round(median(pool), 1)))
    if not rows:
        return ""

    width, row_h, left = 660, 34, 232
    span = width - left - 60
    peak = max(max(own, med) for _, _, own, med in rows) or 1
    parts = [
        f'<svg viewBox="0 0 {width} {len(rows) * row_h + 30}" role="img" '
        f'aria-label="Focus programme versus conference median on observed rates">'
    ]
    for index, (label, direction, own, med) in enumerate(rows):
        y = index * row_h + 22
        x_own = left + own / peak * span
        x_med = left + med / peak * span
        parts.append(
            f'<text x="0" y="{y + 4}" class="db-label">{esc(label)}</text>'
            f'<line x1="{left}" y1="{y}" x2="{left + span}" y2="{y}" class="db-track"/>'
            f'<line x1="{x_med:.0f}" y1="{y}" x2="{x_own:.0f}" y2="{y}" class="db-join"/>'
            f'<circle cx="{x_med:.0f}" cy="{y}" r="5" class="db-med"/>'
            f'<circle cx="{x_own:.0f}" cy="{y}" r="6" class="db-own"/>'
            f'<text x="{x_own:.0f}" y="{y - 10}" class="db-num num">{own}</text>'
            f'<text x="{x_med:.0f}" y="{y + 18}" class="db-mednum num">{med}</text>'
        )
    parts.append("</svg>")
    legend = (
        '<div class="viz-note"><span class="dot dot-own"></span> '
        f"{esc(digest['programmes'][digest['focus']].get('name', digest['focus']))}"
        ' &nbsp; <span class="dot dot-med"></span> conference median · observed, from held '
        f"box scores of the {digest.get('previous_season')} season</div>"
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
    overall = (
        f'<span class="h2h-rec num">{versus.get("wins")}-{versus.get("draws")}-{versus.get("losses")}'
        f"</span> all-time in {len(meetings)} held meetings"
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


def offseason_ledger(items: list[dict] | None) -> str:
    if not items:
        return ""
    rows = []
    for item in items:
        source = esc(item.get("source", ""))
        url = esc(item.get("url", ""))
        cite = f'<a href="{url}">{source}</a>' if url else source
        date = esc(item.get("date", ""))
        cite_row = (
            f'<span class="ledger-cite">{" · ".join(part for part in (cite, date) if part)}</span>'
            if cite or date
            else ""
        )
        rows.append(
            f'<div class="ledger-row"><b>{esc(item.get("player", ""))}</b>'
            f"<span>{esc(item.get('text', ''))}</span>{cite_row}</div>"
        )
    return (
        '<div class="ledger"><div class="viz-title">The offseason ledger — '
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
        f'<th class="num">{season} W-D-L</th><th class="num">GF:GA</th>'
        '<th class="num">Conf</th><th class="num">Conf GF:GA</th>'
        '<th class="num">CS</th><th>Returning goals</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        '<div class="viz-note">Observed · records from published results; returning share '
        "joins the two published rosters against last season's statistics.</div>"
    )


def schedule_matrix(digest: dict, names: dict[str, str]) -> str:
    """Every 2026 meeting with a conference opponent, chronological."""
    rows = []
    fixtures = []
    for slug, section in digest["programmes"].items():
        if slug == digest["focus"]:
            continue
        for fixture in section.get("fixtures_vs_focus") or []:
            fixtures.append((slug, section, fixture))
    fixtures.sort(key=lambda item: str(item[2].get("date")))
    for slug, section, fixture in fixtures:
        at_home = fixture.get("home") == digest["focus"]
        last = section.get("last_season") or {}
        conf = last.get("conference", {})
        turnover = section.get("turnover") or {}
        share = (turnover.get("returning_share") or {}).get("goals")
        versus = section.get("head_to_head")
        rows.append(
            f'<tr><td class="num">{esc(_long_date(str(fixture.get("date"))))}</td>'
            f"<td>{esc(section.get('name', slug))}</td>"
            f'<td><span class="tag tag-{"home" if at_home else "away"}">{"HOME" if at_home else "AWAY"}</span></td>'
            f'<td class="num">{record_line(conf)}</td>'
            f'<td class="num">{f"{round(share * 100)}%" if share is not None else "–"}</td>'
            f'<td class="num">{record_line(versus) if versus else "–"}</td>'
            f'<td class="num streak">{_streak(versus)}</td></tr>'
        )
    return (
        '<table class="grid"><thead><tr><th class="num">Date</th><th>Opponent</th><th>Venue</th>'
        f'<th class="num">{digest.get("previous_season")} conf</th>'
        '<th class="num">Goals returning</th><th class="num">H2H (all-time)</th>'
        '<th class="num">Streak</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table>"
        '<div class="viz-note">Observed · streak reads from the focus side (L5 = five straight '
        "losses in the series). H2H spans every held season.</div>"
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
    """Players whose participation stopped early — rendered as PROJECTED.

    The digest reports the observed pattern; the injury reading is inference,
    and the block says so in place.
    """
    flags = (last or {}).get("availability_flags") or []
    if not flags:
        return ""
    rows = []
    for flag in flags[:5]:
        roster = flag.get("on_current_roster")
        status = ""
        if roster is True:
            status = '<span class="tag tag-ret">on new roster</span>'
        elif roster is False:
            status = '<span class="tag tag-dep">not on new roster</span>'
        rows.append(
            f"<tr><td><b>{esc(flag.get('name', ''))}</b></td>"
            f'<td class="num">{flag.get("appearances")}</td>'
            f'<td class="num">{flag.get("minutes")}</td>'
            f'<td class="num">{esc(_long_date(str(flag.get("last_seen", ""))))}</td>'
            f'<td class="num">{flag.get("missed_after")} of {flag.get("of_matches")}</td>'
            f"<td>{status}</td></tr>"
        )
    return (
        f'<div class="viz-title">Availability watch {label_chip("projected")}</div>'
        '<table class="grid slim"><thead><tr><th>Player</th><th class="num">Apps</th>'
        '<th class="num">Min</th><th class="num">Last seen</th><th class="num">Missed</th>'
        "<th></th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
        '<div class="viz-note">Inferred from participation patterns in held box scores: a '
        "regular who stops appearing while the team plays on. The record cannot distinguish "
        "injury from transfer, discipline, or redshirt — treat these as leads for film and "
        "roster verification, not conclusions.</div>"
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
            f'<span class="keeper"><b>{esc(name)}</b> <span class="num">({" · ".join(bits)})</span>{status}</span>'
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
        leader_text = f'<div class="departed"><span class="viz-title">Walked out the door</span> {led}</div>'
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
        '<div class="viz-note">Observed · published season statistics, all held seasons.</div>'
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


def breakout_cards(digest: dict, entries: list[dict] | None) -> str:
    if not entries:
        return f'<p class="pending">{PLACEHOLDER}</p>'
    cards = []
    for entry in entries:
        profile = _find_profile(digest, entry.get("player", ""))
        trend = ""
        if profile and len(profile.get("career") or []) >= 2:
            trend = career_table(profile)
        elif profile:
            trend = career_table(profile)
        cards.append(
            f'<div class="breakout"><div class="breakout-head"><b>{esc(entry.get("player", ""))}</b>'
            f'{label_chip(entry.get("label") or "judgment")}</div>'
            f'<div class="story"><p>{esc(entry.get("text", ""))}</p></div>{trend}</div>'
        )
    return "".join(cards)


# ── Opponent cards ───────────────────────────────────────────────────────────


def opponent_card(digest: dict, slug: str, narrative: dict, names: dict[str, str]) -> str:
    section = digest["programmes"][slug]
    last = section.get("last_season") or {}
    story = (narrative.get("programmes") or {}).get(slug) or {}
    first_meeting = (section.get("fixtures_vs_focus") or [{}])[0].get("date", "")
    turnover = section.get("turnover")
    return f"""
<section class="sheet opponent">
  <header class="opp-head">
    <span class="opp-abbr">{esc(section.get("abbr", slug[:3].upper()))}</span>
    <div>
      <h2>{esc(section.get("name", slug))}</h2>
      <div class="opp-sub num">First meeting {esc(_long_date(first_meeting)) if first_meeting else "TBD"}</div>
    </div>
    <span class="prio">Priority opponent</span>
  </header>
  {stat_grid(last)}
  <div class="two-col">
    <div>{minute_chart(last.get("patterns"))}</div>
    <div>{turnover_block(turnover, digest.get("season", ""))}{keeper_line(last, turnover)}</div>
  </div>
  {returning_table(section.get("top_returning") or [])}
  {availability_block(last)}
  {h2h_strip(section.get("head_to_head"), names, digest["focus"])}
  {fixtures_line(section.get("fixtures_vs_focus"), digest["focus"])}
  <div class="story">{prose(story.get("overview"))}</div>
  {news_cards(story.get("news"))}
  {takeaway_list(story.get("takeaways"), "What this changes for the focus side")}
</section>"""


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
    takeaway = (story.get("takeaways") or [""])[0]
    return f"""
<div class="compact">
  <div class="compact-head"><span class="opp-abbr sm">{esc(section.get("abbr", slug[:3].upper()))}</span>
    <b>{esc(section.get("name", slug))}</b>
    <span class="num dim">{record_line(overall)} · conf {record_line(conf)} · {overall.get("gf")}:{overall.get("ga")}</span></div>
  <div class="compact-line"><span class="viz-title">Returning goals</span>
    <span class="num">{f"{round(share * 100)}%" if share is not None else "roster pending"}</span>
    · <span class="viz-title">H2H</span> <span class="num">{record_line(versus) if versus else "–"}</span>
    · <span class="viz-title">Streak</span> <span class="num">{_streak(versus)}</span></div>
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
    exec_block = narrative.get("exec") or {}
    findings = exec_block.get("findings") or []
    decisions = exec_block.get("decisions") or []
    uncertainties = exec_block.get("uncertainties") or []
    finding_rows = "".join(
        f'<li>{esc(item.get("text", ""))} {label_chip(item.get("label"))}'
        f"{confidence_dot(item.get('confidence'))}</li>"
        for item in findings
    ) or f'<li class="pending">{PLACEHOLDER}</li>'
    decision_rows = "".join(
        f'<div class="decision"><span class="decision-n num">{index}</span>'
        f'<div><b>{esc(item.get("title", ""))}</b><p>{esc(item.get("text", ""))}</p></div></div>'
        for index, item in enumerate(decisions, start=1)
    ) or f'<p class="pending">{PLACEHOLDER}</p>'
    uncertainty_rows = "".join(
        f"<li>{esc(item)}</li>" for item in uncertainties
    ) or f'<li class="pending">{PLACEHOLDER}</li>'
    return f"""
<section class="sheet">
  <h2 class="section-head">Executive brief</h2>
  {indicator_tiles(digest)}
  <div class="viz-title big">Findings</div>
  <ol class="findings">{finding_rows}</ol>
  <div class="exec-cols">
    <div><div class="viz-title big">Coaching decisions</div>{decision_rows}</div>
    <div><div class="viz-title big risk">Major uncertainties</div>
      <ul class="plain risklist">{uncertainty_rows}</ul></div>
  </div>
</section>"""


def sources_sheet(digest: dict) -> str:
    source_rows = "".join(
        f'<tr><td>{esc(key)}</td><td class="num">{esc(str(value)[:10])}</td></tr>'
        for key, value in sorted((digest.get("sources") or {}).items())
    )
    return f"""
<section class="sheet">
  <h2 class="section-head">Sources, definitions, and method</h2>
  <div class="viz-title big">Evidence labels</div>
  <div class="story">
    <p>{label_chip("observed")} Computed directly from published schedules, results, rosters,
    statistics pages, and box-score play-by-play. Every observed figure in this report traces to
    the digest file named below.</p>
    <p>{label_chip("projected")} A model-based estimate with stated assumptions. This report
    contains no projected figures unless labeled.</p>
    <p>{label_chip("judgment")} Interpretation that requires film or coaching context to
    validate. Player strengths and limitations are judgments, not measurements.</p>
  </div>
  <div class="viz-title big">Definitions</div>
  <div class="story">
    <p>Minutes, goals, assists, points, shots, and cards are as published by each programme's
    official statistics page. Save percentage = saves ÷ (saves + goals against). Returning share
    joins consecutive published rosters by normalized player name and weights last season's
    production. Goal timing comes from published play-by-play; band charts state their match
    sample. Head-to-head covers only seasons held in the archive
    ({esc(digest.get("seasons_held", ["–"])[0])}–{esc(digest.get("seasons_held", ["–"])[-1])}).
    Shot locations are not collected, so xG is not reported anywhere in this document.</p>
  </div>
  <div class="viz-title big">Collection record</div>
  <table class="grid slim sources"><thead><tr><th>Season file</th><th class="num">Collected</th></tr></thead>
  <tbody>{source_rows}</tbody></table>
  <div class="foot-note">
    <p>Independent analysis prepared by EDInsights from public, published data. Not issued by or
    affiliated with Harding University Athletics; no institutional marks are used.</p>
    <p class="mark">EDInsights · Empowered Data. Artificial Intelligence. Real Results.</p>
  </div>
</section>"""


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
    priority = [slug for slug in ordered if (programme_stories.get(slug) or {}).get("priority")]
    if not priority:
        priority = ordered[:3]
    rest = [slug for slug in ordered if slug not in priority]

    priority_sheets = "".join(
        opponent_card(digest, slug, narrative, names) for slug in priority
    )
    compact_cards = "".join(compact_card(digest, slug, narrative, names) for slug in rest)

    dossier_sheets = "".join(
        dossier_sheet(digest, entry) for entry in narrative.get("dossiers") or []
    )
    questions = "".join(
        f"<li>{esc(item)}</li>" for item in narrative.get("questions") or []
    ) or f'<li class="pending">{PLACEHOLDER}</li>'
    extrapolated = (
        '<p class="caveat">Conference membership for this season is carried forward from the '
        "last authored year and not yet confirmed.</p>"
        if digest.get("membership_extrapolated")
        else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(digest.get("conference", ""))} {esc(digest.get("gender", ""))} {esc(digest.get("season", ""))} — Preseason Briefing · {esc(focus_name)}</title>
<style>{CSS}</style>
</head>
<body>

<section class="sheet cover">
  <div class="cover-eyebrow">Prepared for {esc(focus_name)} {gender_word} Soccer</div>
  <h1>{esc(digest.get("conference", ""))} {gender_word} Soccer<br><span class="cover-season num">{esc(digest.get("season", ""))} Preseason Intelligence</span></h1>
  <div class="cover-rule"></div>
  {f'<p class="headline">{esc(narrative.get("headline", ""))}</p>' if narrative.get("headline") else ""}
  <div class="cover-meta">
    <div><span class="viz-title">Prepared</span> {esc(_long_date(generated))}</div>
    <div><span class="viz-title">Record</span> seasons {esc(span)}, published data only</div>
    <div><span class="viz-title">Standard</span> every figure traces to the collection record; gaps are named, never guessed</div>
  </div>
  {extrapolated}
  <div class="cover-foot">Independent analysis · prepared by EDInsights from public, published data ·
  not issued by or affiliated with {esc(focus_name)} University Athletics</div>
</section>

{exec_sheet(digest, narrative)}

<section class="sheet">
  <h2 class="section-head">{esc(focus_name)} — the honest baseline</h2>
  {stat_grid(focus_last)}
  <div class="two-col">
    <div>{minute_chart(focus_last.get("patterns"))}</div>
    <div>{turnover_block(focus.get("turnover"), digest.get("season", ""))}{keeper_line(focus_last, focus.get("turnover"))}</div>
  </div>
  {returning_table(focus.get("top_returning") or [])}
  {availability_block(focus_last)}
  <div class="story">{prose(focus_story.get("overview"))}</div>
  {news_cards(focus_story.get("news"))}
  {offseason_ledger(focus_story.get("offseason"))}
  {takeaway_list(focus_story.get("takeaways"))}
</section>

<section class="sheet">
  <h2 class="section-head">The conference landscape</h2>
  {landscape_table(digest)}
  {landscape_scatter(digest)}
  <div class="story">{prose(narrative.get("landscape"))}</div>
</section>

<section class="sheet">
  <h2 class="section-head">Where {esc(focus_name)} can gain ground</h2>
  <p class="section-sub">Observed per-match rates against the conference median — the gaps are the
  coaching surface area.</p>
  {dumbbell_chart(digest)}
  <div class="story">{prose(narrative.get("gain"))}</div>
</section>

<section class="sheet">
  <h2 class="section-head">Schedule and matchup matrix</h2>
  {schedule_matrix(digest, names)}
</section>

{priority_sheets}

<section class="sheet">
  <h2 class="section-head">The rest of the conference</h2>
  <p class="section-sub">Compact cards — full treatment reserved for the priority opponents above.</p>
  {compact_cards}
</section>

<section class="sheet">
  <h2 class="section-head">Breakout candidates</h2>
  <p class="section-sub">Roster players whose held record shows upward indicators. Trajectories are
  observed; the reads are scouting judgment.</p>
  {breakout_cards(digest, narrative.get("breakouts"))}
</section>

{dossier_sheets}

<section class="sheet">
  <h2 class="section-head">To validate in preseason</h2>
  <ol class="findings">{questions}</ol>
</section>

{sources_sheet(digest)}

</body>
</html>"""


CSS = """
:root{
--paper:#efeadf;--sheet:#fffdf8;--ink:#211c12;--ink2:#453e2f;
--muted:#6e6759;--faint:#99917f;--rule:#e5dfd0;--rule2:#cdc4ab;
--gold:#8a6d24;--gold-fill:#b4975a;--gold-wash:#f4eeda;
--rose:#a03a4e;--rose-wash:#f6e9ec;--bench:#8d8779;
--win:#2e7d4f;--loss:#a03a4e;--draw:#9a7b23;
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

.cover{padding-top:110px;min-height:600px}
.cover-eyebrow{font:700 12px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.24em;text-transform:uppercase;color:var(--gold);margin-bottom:20px}
.cover h1{font:700 52px/1.04 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;letter-spacing:.005em}
.cover-season{color:var(--ink2)}
.cover-rule{height:3px;background:var(--gold-fill);margin:26px 0;width:180px}
.headline{font-size:17px;line-height:1.55;max-width:60ch;color:var(--ink2);
border-left:3px solid var(--gold-fill);padding-left:16px;margin:18px 0 26px}
.cover-meta{margin-top:26px;display:grid;gap:8px;font-size:13px;color:var(--ink2)}
.cover-meta .viz-title{display:inline-block;width:84px;margin:0}
.cover-foot{margin-top:56px;font-size:11.5px;color:var(--faint);border-top:1px solid var(--rule);
padding-top:12px}

.section-head{font:700 23px/1.1 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;letter-spacing:.04em;margin:0 0 16px;
border-bottom:2px solid var(--gold-fill);padding-bottom:8px}
.section-sub{color:var(--muted);margin:-6px 0 14px;font-size:13px}

.lbl{font:700 8.5px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;letter-spacing:.1em;
text-transform:uppercase;padding:3px 6px;border-radius:2px;vertical-align:1.5px;white-space:nowrap}
.lbl-observed{background:var(--gold-wash);color:var(--gold);border:1px solid var(--gold-fill)}
.lbl-projected{background:#eeece5;color:var(--bench);border:1px solid var(--rule2)}
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

.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(99px,1fr));gap:8px;margin:0 0 16px}
.stat{background:var(--gold-wash);padding:9px 11px;border:1px solid var(--rule2)}
.stat-label{display:block;font:700 9.5px/1.3 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.stat-val{display:block;font-size:19px;font-weight:700;margin-top:2px}
.stat-sub{display:block;font-size:11px;color:var(--faint)}

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
.bar-against{fill:#c4677a}
.bar-num{font-size:10px;fill:var(--ink2);text-anchor:middle}

.db-label{font-size:11.5px;fill:var(--ink2)}
.db-track{stroke:var(--rule);stroke-width:2}
.db-join{stroke:var(--rule2);stroke-width:2}
.db-med{fill:var(--bench)}
.db-own{fill:var(--gold-fill)}
.db-num{font-size:10.5px;fill:var(--gold);text-anchor:middle;font-weight:700}
.db-mednum{font-size:9.5px;fill:var(--bench);text-anchor:middle}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;vertical-align:-1px}
.dot-own{background:var(--gold-fill)}
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

.caveat{color:var(--draw);margin:10px 0;font-size:12.5px}
.foot-note{margin-top:26px;border-top:1px solid var(--rule2);padding-top:12px;
font-size:11.5px;color:var(--faint)}
.foot-note .mark{margin-top:8px;font:700 10px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}

@page{size:letter;margin:0.5in}
@media print{
body{background:#fff}
.sheet{box-shadow:none;margin:0;max-width:none;padding:0.1in 0.2in}
a{color:var(--ink);text-decoration:none}
}
"""
