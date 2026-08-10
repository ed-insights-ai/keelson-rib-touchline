"""Deterministic report renderer — the digest made visible.

The renderer merges two inputs into a self-contained HTML briefing:

* the **digest** (``touchline.digest/1``) — every figure, table, and chart in
  the page is drawn from it and nowhere else;
* a **narrative** (``touchline.report-narrative/1``) — prose authored by the
  report workflow's analyst and research nodes: per-programme overviews,
  takeaways, and cited news items.  The narrative never carries a number the
  digest doesn't; the workflow's verification pass enforces that upstream.

The split is the product's safety boundary: a language model writes the
narrative *file*, and this renderer — plain code — decides everything that is
actually a fact on the page.  A missing narrative section renders as an
explicit placeholder, so the deterministic skeleton always ships.

Narrative contract::

    {
      "schema": "touchline.report-narrative/1",
      "headline": str,                     # one line under the masthead
      "landscape": str,                    # conference overview prose
      "focus": {"overview": str, "takeaways": [str], "news": [NEWS]},
      "programmes": {slug: {"overview": str, "takeaways": [str], "news": [NEWS]}}
    }
    NEWS = {"text": str, "source": str, "url": str, "date": str}

Paragraph breaks in prose are blank lines.  Everything else on the page is
computed here from the digest.
"""

from __future__ import annotations

import html
from typing import Any

MINUTE_BANDS = ("0-15", "15-30", "30-45", "45-60", "60-75", "75-90", "90+")

PLACEHOLDER = (
    "Narrative pending — the report workflow has not written this section yet."
)


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


# ── Visual atoms ─────────────────────────────────────────────────────────────


def share_bars(share: dict | None) -> str:
    """Returning-production bars: how much of last season walks back in."""
    if not share:
        return ""
    rows = []
    for field, label in (
        ("goals", "Goals"),
        ("points", "Points"),
        ("minutes", "Minutes"),
    ):
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
    """The signature visual: goals for (up) and against (down) by 15' band."""
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
        f'<div class="viz-note">Goals by minute · {counted} of {total} matches held</div>'
        if counted is not None
        else ""
    )
    return f'<div class="minutes">{"".join(parts)}{coverage}</div>'


def h2h_strip(
    versus: dict | None, names: dict[str, str], focus: str, limit: int = 8
) -> str:
    """The held meetings as result chips, most recent last, focus perspective.

    Scores are re-ordered focus-first so "L 1-5" always reads as the focus
    side's 1 — the published home-away order would make half the chips lie.
    """
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


def takeaway_list(items: list[str] | None) -> str:
    if not items:
        return ""
    rows = "".join(f"<li>{esc(item)}</li>" for item in items)
    return (
        '<div class="takeaways"><div class="viz-title">Preparation points</div>'
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
        conf = last.get("conference", {})
        entries.append((slug, section, last, conf))
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
    )


def returning_table(profiles: list[dict]) -> str:
    if not profiles:
        return ""
    rows = []
    for profile in profiles:
        last = profile["career"][-1] if profile.get("career") else {}
        seasons = len(profile.get("career") or [])
        who = esc(profile.get("name", ""))
        meta = " · ".join(
            esc(profile[key])
            for key in ("position", "class_year")
            if profile.get(key)
        )
        rows.append(
            f'<tr><td><b>{who}</b><span class="player-meta">{meta}</span></td>'
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


def turnover_block(turnover: dict | None) -> str:
    if not turnover:
        return (
            '<div class="gap">Roster turnover unknown — the '
            f"{'{season}'} roster has not been published yet.</div>"
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


def fixtures_line(fixtures: list[dict] | None, names: dict[str, str], focus: str) -> str:
    if not fixtures:
        return ""
    rows = []
    for fixture in fixtures:
        at_home = fixture.get("home") == focus
        where = "HOME" if at_home else "AWAY"
        venue = fixture.get("venue", "")
        rows.append(
            f'<span class="fixture"><b class="num">{esc(_long_date(str(fixture.get("date"))))}</b>'
            f' <span class="tag tag-{where.lower()}">{where}</span>'
            f' <span class="dim">{esc(venue)}</span></span>'
        )
    return f'<div class="fixtures"><div class="viz-title">2026 meetings</div>{"".join(rows)}</div>'


# ── Sections ─────────────────────────────────────────────────────────────────


def _names(digest: dict) -> dict[str, str]:
    return {
        slug: section.get("name", slug)
        for slug, section in digest["programmes"].items()
    }


def opponent_section(
    digest: dict, slug: str, narrative: dict, names: dict[str, str]
) -> str:
    section = digest["programmes"][slug]
    last = section.get("last_season") or {}
    story = (narrative.get("programmes") or {}).get(slug) or {}
    first_meeting = (section.get("fixtures_vs_focus") or [{}])[0].get("date", "")
    turnover = section.get("turnover")
    turnover_html = turnover_block(turnover).replace(
        "{season}", str(digest.get("season"))
    )
    return f"""
<section class="opponent" id="{esc(slug)}">
  <header class="opp-head">
    <span class="opp-abbr">{esc(section.get("abbr", slug[:3].upper()))}</span>
    <div>
      <h2>{esc(section.get("name", slug))}</h2>
      <div class="opp-sub num">First meeting {esc(_long_date(first_meeting)) if first_meeting else "TBD"}</div>
    </div>
  </header>
  {stat_grid(last)}
  <div class="two-col">
    <div>{minute_chart(last.get("patterns"))}</div>
    <div>{turnover_html}{keeper_line(last, turnover)}</div>
  </div>
  {returning_table(section.get("top_returning") or [])}
  {h2h_strip(section.get("head_to_head"), names, digest["focus"])}
  {fixtures_line(section.get("fixtures_vs_focus"), names, digest["focus"])}
  <div class="story">{prose(story.get("overview"))}</div>
  {news_cards(story.get("news"))}
  {takeaway_list(story.get("takeaways"))}
</section>"""


def focus_section(digest: dict, narrative: dict, names: dict[str, str]) -> str:
    slug = digest["focus"]
    section = digest["programmes"][slug]
    last = section.get("last_season") or {}
    story = narrative.get("focus") or {}
    turnover = section.get("turnover")
    turnover_html = turnover_block(turnover).replace(
        "{season}", str(digest.get("season"))
    )
    return f"""
<section class="opponent focus-section" id="{esc(slug)}">
  <header class="opp-head">
    <span class="opp-abbr">{esc(section.get("abbr", slug[:3].upper()))}</span>
    <div>
      <h2>{esc(section.get("name", slug))} — the honest baseline</h2>
      <div class="opp-sub">What the record says we were</div>
    </div>
  </header>
  {stat_grid(last)}
  <div class="two-col">
    <div>{minute_chart(last.get("patterns"))}</div>
    <div>{turnover_html}{keeper_line(last, turnover)}</div>
  </div>
  {returning_table(section.get("top_returning") or [])}
  <div class="story">{prose(story.get("overview"))}</div>
  {news_cards(story.get("news"))}
  {takeaway_list(story.get("takeaways"))}
</section>"""


def watch_list(digest: dict) -> str:
    entries = []
    for slug, section in digest["programmes"].items():
        for profile in section.get("top_returning") or []:
            career = profile.get("career") or []
            last = career[-1] if career else {}
            if last.get("season") != digest.get("previous_season"):
                continue
            entries.append((slug, section.get("name", slug), profile, last))
    entries.sort(key=lambda item: (-item[3].get("points", 0), -item[3].get("goals", 0)))
    rows = []
    for slug, team, profile, last in entries[:10]:
        meta = " · ".join(
            esc(profile[key]) for key in ("position", "class_year") if profile.get(key)
        )
        focus_class = ' class="is-focus"' if slug == digest["focus"] else ""
        rows.append(
            f"<tr{focus_class}><td><b>{esc(profile['name'])}</b>"
            f'<span class="player-meta">{meta}</span></td><td>{esc(team)}</td>'
            f'<td class="num">{last.get("gp", "–")}</td><td class="num">{last.get("goals", "–")}</td>'
            f'<td class="num">{last.get("assists", "–")}</td><td class="num">{last.get("points", "–")}</td>'
            f'<td class="num">{last.get("minutes", "–")}</td></tr>'
        )
    return (
        '<table class="grid"><thead><tr><th>Player</th><th>Team</th>'
        '<th class="num">GP</th><th class="num">G</th><th class="num">A</th>'
        '<th class="num">Pts</th><th class="num">Min</th></tr></thead><tbody>'
        + "".join(rows)
        + "</tbody></table>"
    )


def _schedule_order(digest: dict) -> list[str]:
    """Opponents ordered by their first scheduled meeting with the focus."""
    def first_date(slug: str) -> str:
        fixtures = digest["programmes"][slug].get("fixtures_vs_focus") or []
        return str(fixtures[0]["date"]) if fixtures else "9999"

    opponents = [slug for slug in digest["programmes"] if slug != digest["focus"]]
    return sorted(opponents, key=first_date)


def render_report(digest: dict, narrative: dict | None = None) -> str:
    narrative = narrative or {}
    names = _names(digest)
    focus_name = names.get(digest["focus"], digest["focus"])
    seasons = digest.get("seasons_held") or []
    span = f"{seasons[0]}–{seasons[-1]}" if seasons else "–"
    generated = str(digest.get("generated_at", ""))[:10]
    headline = narrative.get("headline") or ""
    opponents = "".join(
        opponent_section(digest, slug, narrative, names)
        for slug in _schedule_order(digest)
    )
    extrapolated = (
        '<p class="caveat">Conference membership for this season is carried '
        "forward from the last authored year and not yet confirmed.</p>"
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
<div class="page">
<header class="mast">
  <div class="eyebrow">Touchline Scouting · Preseason Intelligence</div>
  <h1>{esc(digest.get("conference", ""))} {"Men's" if digest.get("gender") == "men" else "Women's"} Soccer <span class="num">{esc(digest.get("season", ""))}</span></h1>
  <div class="prepared">Prepared for <b>{esc(focus_name)}</b> · {esc(_long_date(generated))}</div>
  <div class="provenance num">Built from the collected record · seasons {esc(span)} · every figure traces to the data</div>
  {f'<p class="headline">{esc(headline)}</p>' if headline else ""}
</header>

<section>
  <h2 class="section-head">The conference at a glance</h2>
  {landscape_table(digest)}
  <div class="story">{prose(narrative.get("landscape"))}</div>
</section>

{focus_section(digest, narrative, names)}

<h2 class="section-head">The opposition, in schedule order</h2>
{opponents}

<section>
  <h2 class="section-head">The watch list</h2>
  <p class="section-sub">The conference's top returning producers — the players who decide games.</p>
  {watch_list(digest)}
</section>

<footer class="foot">
  {extrapolated}
  <p>Figures computed from published schedules, rosters, statistics, and box scores collected
  {esc(_long_date(generated))} · seasons held {esc(span)} · gaps are named, never guessed.</p>
  <p class="mark">EDInsights · Empowered Data. Artificial Intelligence. Real Results.</p>
</footer>
</div>
</body>
</html>"""


CSS = """
:root{
--bg:#0a1020;--sheet:#101831;--sunk:#0d1428;--ink:#e9edf7;--ink2:#aab5cd;
--muted:#8b97b5;--faint:#5f6b88;--rule:#243250;--rule2:#31436b;
--gold:#e3b34c;--gold-soft:#2a2410;--win:#57cf90;--loss:#f0879a;--draw:#d9a441;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);
font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;
-webkit-font-smoothing:antialiased}
.num{font-variant-numeric:tabular-nums}
.dim{color:var(--faint)}
.page{max-width:880px;margin:0 auto;padding:48px 28px 64px}
a{color:var(--gold)}

.mast{border-bottom:3px solid var(--gold);padding-bottom:22px;margin-bottom:34px}
.eyebrow{font:700 11px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.22em;text-transform:uppercase;color:var(--gold);margin-bottom:14px}
.mast h1{font:700 44px/1.02 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;letter-spacing:.01em}
.prepared{margin-top:10px;font-size:15px;color:var(--ink2)}
.provenance{margin-top:4px;font-size:12px;color:var(--faint)}
.headline{margin-top:16px;font-size:16.5px;line-height:1.5;color:var(--ink);
max-width:64ch;border-left:3px solid var(--gold);padding-left:14px}

.section-head{font:700 21px/1.1 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;letter-spacing:.05em;margin:40px 0 14px;color:var(--ink)}
.section-sub{color:var(--muted);margin:-8px 0 14px;font-size:13px}

.grid{width:100%;border-collapse:collapse;background:var(--sheet);font-size:13px}
.grid th{font:700 10.5px/1.4 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.09em;text-transform:uppercase;color:var(--muted);text-align:left;
padding:8px 10px;border-bottom:1px solid var(--rule2)}
.grid td{padding:8px 10px;border-bottom:1px solid var(--rule)}
.grid th.num,.grid td.num{text-align:right}
.grid tr.is-focus td{background:var(--gold-soft);border-bottom-color:var(--rule2)}
.grid tr.is-focus td:first-child{box-shadow:inset 3px 0 0 var(--gold)}
.abbr{color:var(--faint);font-size:11px;margin-left:4px}
.player-meta{display:block;color:var(--faint);font-size:11px}
.grid.slim{font-size:12.5px}
.mini-track{display:inline-block;width:84px;height:7px;background:var(--sunk);
border-radius:4px;overflow:hidden;vertical-align:2px;margin-right:8px}
.mini-fill{display:block;height:100%;background:var(--gold)}
.share-cell{white-space:nowrap}

.opponent{background:var(--sheet);border:1px solid var(--rule);border-top:3px solid var(--rule2);
padding:22px 24px 20px;margin:18px 0}
.focus-section{border-top-color:var(--gold)}
.opp-head{display:flex;align-items:center;gap:16px;margin-bottom:16px}
.opp-abbr{display:inline-flex;align-items:center;justify-content:center;
min-width:56px;height:56px;padding:0 8px;background:var(--sunk);border:1px solid var(--rule2);
font:700 19px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;color:var(--gold)}
.opp-head h2{font:700 25px/1.05 "Avenir Next Condensed","Arial Narrow",sans-serif;
text-transform:uppercase;letter-spacing:.02em}
.opp-sub{color:var(--muted);font-size:12px;margin-top:3px}

.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(99px,1fr));gap:8px;margin:0 0 16px}
.stat{background:var(--sunk);padding:9px 11px;border:1px solid var(--rule)}
.stat-label{display:block;font:700 9.5px/1.3 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.stat-val{display:block;font-size:19px;font-weight:700;margin-top:2px}
.stat-sub{display:block;font-size:11px;color:var(--faint)}

.two-col{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:20px;margin:2px 0 14px}
@media(max-width:700px){.two-col{grid-template-columns:1fr}}
.viz-title{font:700 10.5px/1.4 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin:10px 0 6px}
.viz-note{font-size:11px;color:var(--faint);margin-top:4px}
.minutes svg{width:100%;height:auto;display:block}
.axis{stroke:var(--rule2);stroke-width:1}
.axis-label{font:700 9px "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.12em;fill:var(--faint)}
.band-label{font-size:9.5px;fill:var(--faint);text-anchor:middle}
.bar-for{fill:var(--gold)}
.bar-against{fill:var(--loss);opacity:.85}
.bar-num{font-size:10px;fill:var(--ink2);text-anchor:middle}

.share-row{display:flex;align-items:center;gap:8px;margin:4px 0}
.share-label{width:56px;font-size:11px;color:var(--muted)}
.share-track{flex:1;height:8px;background:var(--sunk);border-radius:4px;overflow:hidden}
.share-fill{display:block;height:100%;background:var(--gold)}
.share-num{width:36px;text-align:right;font-size:11.5px}
.turnover-counts{display:flex;gap:16px;font-size:12.5px;color:var(--ink2);margin-bottom:4px}
.turnover-counts b{font-size:16px;color:var(--ink)}
.departed{font-size:12px;color:var(--ink2);margin-top:8px}
.departed .viz-title{display:block}
.gap{background:var(--sunk);border:1px dashed var(--rule2);color:var(--muted);
padding:10px 12px;font-size:12.5px;margin:8px 0}
.keepers{margin-top:10px}
.keeper{display:block;font-size:12.5px;color:var(--ink2);margin:2px 0}
.tag{font:700 9px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;letter-spacing:.08em;
text-transform:uppercase;padding:3px 6px;border-radius:3px;vertical-align:1px}
.tag-ret{background:#12301f;color:var(--win)}
.tag-dep{background:#331a22;color:var(--loss)}
.tag-home{background:var(--gold-soft);color:var(--gold)}
.tag-away{background:var(--sunk);color:var(--muted);border:1px solid var(--rule2)}

.h2h{margin:14px 0 4px}
.h2h-rec{font-weight:700;color:var(--ink)}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{display:inline-flex;align-items:center;gap:5px;background:var(--sunk);
border:1px solid var(--rule);padding:4px 8px;font-size:11px;color:var(--ink2)}
.chip b{font-size:11px}
.chip i{font-style:normal;color:var(--faint);font-size:10px}
.chip-w{border-left:3px solid var(--win)}.chip-w b{color:var(--win)}
.chip-l{border-left:3px solid var(--loss)}.chip-l b{color:var(--loss)}
.chip-d{border-left:3px solid var(--draw)}.chip-d b{color:var(--draw)}

.fixtures{margin:12px 0 4px}
.fixture{display:inline-flex;align-items:center;gap:8px;margin-right:18px;font-size:12.5px}

.story{margin:14px 0 4px;max-width:70ch}
.story p{margin:8px 0;color:var(--ink2);font-size:13.5px}
.pending{color:var(--faint);font-style:italic}
.news{background:var(--sunk);border-left:3px solid var(--gold);padding:10px 14px;margin:10px 0}
.news-tag{font:700 9px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.14em;text-transform:uppercase;color:var(--gold)}
.news p{margin:5px 0 4px;font-size:13px;color:var(--ink)}
.news-cite{font-size:11px;color:var(--faint)}
.takeaways{margin:14px 0 2px;background:var(--sunk);border:1px solid var(--rule);padding:10px 14px}
.takeaways ul{margin:2px 0 2px 18px}
.takeaways li{margin:5px 0;font-size:13px;color:var(--ink)}

.foot{margin-top:44px;border-top:1px solid var(--rule2);padding-top:14px;
font-size:11.5px;color:var(--faint)}
.foot .mark{margin-top:8px;font:700 10px/1 "Avenir Next Condensed","Arial Narrow",sans-serif;
letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.caveat{color:var(--draw);margin-bottom:6px}
@media print{body{background:#fff}}
"""
