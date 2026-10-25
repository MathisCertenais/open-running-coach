"""Human-readable exports for a coach, a physiotherapist or an archive.

Two renderings of the same data:

- **Markdown** — copy-pasteable, diffable, survives everything.
- **A print-styled HTML page** — the browser's own "Save as PDF" produces the
  document. No PDF library is added: the runtime stays at two dependencies
  (ADR-0003), and the browser's typesetter is better than anything we would
  hand-roll.

Both are one-way: the athlete decides what to export and to whom (ADR-0007).
"""
from __future__ import annotations

from datetime import date
from html import escape

TITLE = "Training report"


def _hours(seconds: float) -> str:
    minutes = round(seconds / 60)
    return f"{minutes // 60}h{minutes % 60:02d}"


def _km(metres: float) -> str:
    return f"{metres / 1000:.1f} km"


def _pace(seconds_per_km: float) -> str:
    if not seconds_per_km:
        return "—"
    minutes, seconds = divmod(round(seconds_per_km), 60)
    return f"{minutes}:{seconds:02d}/km"


def build(data: dict) -> dict:
    """Normalise the report input into the strings both renderings need.

    ``data`` is assembled by the caller so this module stays free of FastAPI and
    of the store: it formats, it does not fetch.
    """
    totals = data.get("totals") or {}
    window = data.get("window") or {}
    load = data.get("load") or {}
    intensity = data.get("intensity") or {}
    injuries = data.get("injuries") or {}
    return {
        "generated": data.get("generated") or date.today().isoformat(),
        "athlete": (data.get("profile") or {}).get("name") or "Athlete",
        "range": f"{window.get('start', '—')} → {window.get('end', '—')}",
        "runs": totals.get("activities", 0),
        "distance": _km(totals.get("distance_m", 0)),
        "moving": _hours(totals.get("moving_time_s", 0)),
        "elevation": f"{round(totals.get('elevation_gain_m', 0))} m",
        "load": {
            "chronic": load.get("ctl"),
            "acute": load.get("atl"),
            "form": load.get("tsb"),
            "form_label": load.get("form"),
        },
        "intensity": {
            "easy": (intensity.get("easy") or {}).get("time_pct"),
            "moderate": (intensity.get("moderate") or {}).get("time_pct"),
            "hard": (intensity.get("hard") or {}).get("time_pct"),
        },
        "injuries": injuries,
        "sessions": data.get("sessions") or [],
        "shoes": data.get("shoes") or [],
    }


def _injury_lines(injuries: dict) -> list[str]:
    episodes = injuries.get("episodes") or []
    if not episodes:
        return ["No pain reported."]
    summary = injuries.get("summary") or {}
    lines = []
    if summary.get("base_rate") is not None:
        lines.append(
            f"A hard session precedes {round((summary.get('observed_rate') or 0) * 100)}% "
            f"of lower-limb episodes versus {round(summary['base_rate'] * 100)}% of all "
            f"days ({summary.get('reading')})."
        )
    links = injuries.get("links") or []
    for episode in episodes:
        head = (
            f"- **{episode['location']}"
            + (f" · {episode['side']}" if episode.get("side") else "")
            + f"** — {episode['first_date']} → {episode['last_date']}, "
            f"{episode['reports']} report(s)"
        )
        if episode.get("max_severity") is not None:
            head += f", max {episode['max_severity']}/10"
        if episode.get("verdict"):
            head += f", athlete verdict: {episode['verdict']}"
        lines.append(head)
        for link in links:
            if (
                link["location"] == episode["location"]
                and link["side"] == episode["side"]
                and link["pain_first_date"] == episode["first_date"]
            ):
                lines.append(
                    f"    - preceded by **{link['session_title']}** on "
                    f"{link['session_date']} (RPE {link['session_rpe']}, "
                    f"{link['hours_before']} h): {link['explanation']}"
                )
    return lines


def markdown(report: dict) -> str:
    """Render the report as Markdown."""
    intensity = report["intensity"]
    load = report["load"]
    lines = [
        f"# {TITLE} — {report['athlete']}",
        "",
        f"_{report['range']} · generated {report['generated']} by open-running-coach_",
        "",
        "## Summary",
        "",
        f"- Runs: **{report['runs']}**",
        f"- Distance: **{report['distance']}**",
        f"- Moving time: **{report['moving']}**",
        f"- Elevation gain: **{report['elevation']}**",
        "",
        "## Load",
        "",
        f"- Chronic load (CTL): {load['chronic'] if load['chronic'] is not None else '—'}",
        f"- Acute load (ATL): {load['acute'] if load['acute'] is not None else '—'}",
        f"- Form (TSB): {load['form'] if load['form'] is not None else '—'}"
        + (f" ({load['form_label']})" if load.get("form_label") else ""),
        "",
        "## Intensity distribution (grade-adjusted pace)",
        "",
        f"- Easy: {intensity['easy'] if intensity['easy'] is not None else '—'}%",
        f"- Moderate: {intensity['moderate'] if intensity['moderate'] is not None else '—'}%",
        f"- Hard: {intensity['hard'] if intensity['hard'] is not None else '—'}%",
        "- Target: 80% easy / 10% moderate / 10% hard (Seiler 2010).",
        "",
        "## Injury watch",
        "",
        *_injury_lines(report["injuries"]),
        "",
        "## Recent strength and mobility",
        "",
    ]
    sessions = report["sessions"]
    if not sessions:
        lines.append("No sessions logged.")
    for session in sessions[:10]:
        exercises = ", ".join(e.get("name", "") for e in session.get("exercises") or [])
        line = (
            f"- {session.get('date')} · {session.get('title') or session.get('kind')}"
            f" · RPE {session.get('rpe') if session.get('rpe') is not None else '—'}"
        )
        if exercises:
            line += f" · {exercises}"
        lines.append(line)
    lines += ["", "## Shoes", ""]
    if not report["shoes"]:
        lines.append("No shoes recorded.")
    for shoe in report["shoes"]:
        lines.append(
            f"- {shoe.get('name')}: {round(shoe.get('distance_m', 0) / 1000)}"
            f" / {round(shoe.get('threshold_km', 0))} km"
        )
    lines += [
        "",
        "---",
        "",
        "Generated locally by open-running-coach. Correlation is not causation: "
        "the injury links above are patterns to discuss, not a diagnosis.",
        "",
    ]
    return "\n".join(lines)


def html(report: dict) -> str:
    """Render the report as a self-contained, print-styled HTML page."""
    intensity = report["intensity"]
    load = report["load"]
    rows = "".join(
        f"<tr><td>{escape(session.get('date', ''))}</td>"
        f"<td>{escape(str(session.get('title') or session.get('kind') or ''))}</td>"
        f"<td>{session.get('rpe') if session.get('rpe') is not None else '—'}</td>"
        f"<td>{escape(', '.join(e.get('name', '') for e in session.get('exercises') or []))}</td></tr>"
        for session in report["sessions"][:15]
    )
    injury_html = "".join(
        f"<li>{escape(line.lstrip('- ').strip())}</li>"
        for line in _injury_lines(report["injuries"])
    )
    shoe_html = "".join(
        f"<li>{escape(shoe.get('name', ''))} — "
        f"{round(shoe.get('distance_m', 0) / 1000)} / "
        f"{round(shoe.get('threshold_km', 0))} km</li>"
        for shoe in report["shoes"]
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{escape(TITLE)} — {escape(report["athlete"])}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         color: #1f2937; margin: 32px auto; max-width: 780px; padding: 0 20px; line-height: 1.5; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  h2 {{ font-size: 15px; margin: 26px 0 8px; text-transform: uppercase;
        letter-spacing: .04em; color: #4b5563; border-bottom: 1px solid #e5e7eb; padding-bottom: 4px; }}
  .meta {{ color: #6b7280; font-size: 13px; margin-bottom: 20px; }}
  .grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
  .card {{ border: 1px solid #e5e7eb; border-radius: 8px; padding: 10px 12px; }}
  .card b {{ display: block; font-size: 18px; }}
  .card span {{ font-size: 11px; color: #6b7280; text-transform: uppercase; letter-spacing: .04em; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid #e5e7eb; }}
  ul {{ padding-left: 18px; font-size: 13px; }}
  .actions {{ margin-bottom: 24px; }}
  button {{ font: inherit; padding: 8px 14px; border-radius: 8px; border: 1px solid #9a3412;
            background: #c2410c; color: #fff; cursor: pointer; }}
  .note {{ font-size: 12px; color: #6b7280; margin-top: 28px; border-top: 1px solid #e5e7eb; padding-top: 10px; }}
  @media print {{
    .actions {{ display: none; }}
    body {{ margin: 0; max-width: none; }}
    h2 {{ break-after: avoid; }}
    table {{ break-inside: auto; }}
    tr {{ break-inside: avoid; }}
  }}
</style>
</head>
<body>
  <div class="actions"><button onclick="window.print()">Print / Save as PDF</button></div>
  <h1>{escape(TITLE)} — {escape(report["athlete"])}</h1>
  <div class="meta">{escape(report["range"])} · generated {escape(report["generated"])} by open-running-coach</div>

  <h2>Summary</h2>
  <div class="grid">
    <div class="card"><b>{report["runs"]}</b><span>runs</span></div>
    <div class="card"><b>{escape(report["distance"])}</b><span>distance</span></div>
    <div class="card"><b>{escape(report["moving"])}</b><span>moving time</span></div>
    <div class="card"><b>{escape(report["elevation"])}</b><span>elevation</span></div>
  </div>

  <h2>Load</h2>
  <ul>
    <li>Chronic load (CTL): {load["chronic"] if load["chronic"] is not None else "—"}</li>
    <li>Acute load (ATL): {load["acute"] if load["acute"] is not None else "—"}</li>
    <li>Form (TSB): {load["form"] if load["form"] is not None else "—"}{f" ({escape(str(load['form_label']))})" if load.get("form_label") else ""}</li>
  </ul>

  <h2>Intensity distribution (grade-adjusted pace)</h2>
  <ul>
    <li>Easy: {intensity["easy"] if intensity["easy"] is not None else "—"}%</li>
    <li>Moderate: {intensity["moderate"] if intensity["moderate"] is not None else "—"}%</li>
    <li>Hard: {intensity["hard"] if intensity["hard"] is not None else "—"}%</li>
    <li>Target: 80% easy / 10% moderate / 10% hard (Seiler 2010).</li>
  </ul>

  <h2>Injury watch</h2>
  <ul>{injury_html}</ul>

  <h2>Recent strength and mobility</h2>
  <table>
    <thead><tr><th>Date</th><th>Session</th><th>RPE</th><th>Exercises</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="4">No sessions logged.</td></tr>'}</tbody>
  </table>

  <h2>Shoes</h2>
  <ul>{shoe_html or "<li>No shoes recorded.</li>"}</ul>

  <p class="note">Generated locally by open-running-coach. Correlation is not
  causation: the injury links above are patterns to discuss with a
  professional, not a diagnosis.</p>
</body>
</html>"""
