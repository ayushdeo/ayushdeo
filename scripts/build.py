"""Build the profile README and its SVG panels from live GitHub data.

Run locally:   GH_TOKEN=$(gh auth token) python scripts/build.py
In CI:         the workflow passes GITHUB_TOKEN (or ACCESS_TOKEN) and commits assets/.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import urllib.request
from collections import Counter
from html import escape
from pathlib import Path

from chess_replay import build_chess_svg

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
CONFIG = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
LOGIN = CONFIG["login"]

# ------------------------------------------------------------------ palette
P = {
    "bg": "#0b0f14",
    "panel": "#0f151c",
    "panel2": "#131b24",
    "border": "#243041",
    "text": "#e6edf3",
    "muted": "#8b98a8",
    "dim": "#5d6b7c",
    "mint": "#7ee7b0",
    "lav": "#b39dff",
    "sky": "#7cc7ff",
    "sq_light": "#223040",
    "sq_dark": "#17212c",
    "hl": "#7ee7b0",
    "piece_light": "#eef2f6",
    "piece_ink": "#0b0f14",
    "piece_accent": "#7ee7b0",
}
MONO = "ui-monospace,SFMono-Regular,'JetBrains Mono',Menlo,Consolas,'Liberation Mono',monospace"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"

STYLE = f"""<style>
.mono{{font-family:{MONO}}} .sans{{font-family:{SANS}}}
.coord{{font-family:{MONO};font-size:10px;fill:{P['dim']}}}
.ticker{{font-family:{MONO};font-size:15px;font-weight:700;fill:{P['mint']}}}
.ticker.dim{{fill:{P['dim']};font-weight:400}}
.ticker.mate{{fill:#ff7b72;letter-spacing:2px}}
</style>"""

COMMON_DEFS = f"""
<linearGradient id="rim" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="{P['mint']}" stop-opacity=".55"/>
  <stop offset=".5" stop-color="{P['border']}"/>
  <stop offset="1" stop-color="{P['lav']}" stop-opacity=".55"/>
</linearGradient>
<radialGradient id="checkGlow">
  <stop offset="0" stop-color="#ff5b5b" stop-opacity=".85"/>
  <stop offset="1" stop-color="#ff5b5b" stop-opacity="0"/>
</radialGradient>"""


def svg_doc(w: int, h: int, body: str, defs: str = "", title: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="{escape(title)}">'
        f"<title>{escape(title)}</title>{STYLE}<defs>{COMMON_DEFS}{defs}</defs>{body}</svg>\n"
    )


def t(x, y, s, cls="mono", size=13, fill=None, weight=None, anchor=None, extra=""):
    fill = fill or P["text"]
    a = f' text-anchor="{anchor}"' if anchor else ""
    w = f' font-weight="{weight}"' if weight else ""
    return f'<text x="{x}" y="{y}" class="{cls}" font-size="{size}" fill="{fill}"{w}{a} {extra}>{escape(str(s))}</text>'


def wrap(text: str, width_chars: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for word in words:
        if len(cur) + len(word) + (1 if cur else 0) <= width_chars:
            cur = f"{cur} {word}".strip()
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: width_chars - 1].rstrip(" .,;") + "…"
    return lines


def ago(iso: str, now: dt.datetime) -> str:
    then = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    days = (now - then).days
    if days < 1:
        return "today"
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def blink(begin="0s"):
    return f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;.5;.5;1" dur="1.1s" begin="{begin}" repeatCount="indefinite"/>'


# --------------------------------------------------------------- data
def gql(query: str) -> dict:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or os.environ.get("ACCESS_TOKEN")
    if not token:
        raise SystemExit("Set GH_TOKEN (e.g. GH_TOKEN=$(gh auth token)).")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def fetch() -> dict:
    q = """query {
      user(login: "%s") {
        name avatarUrl
        followers { totalCount }
        pinnedItems(first: 6, types: REPOSITORY) { nodes { ... on Repository {
          name description url stargazerCount pushedAt
          primaryLanguage { name color }
          languages(first: 6, orderBy: {field: SIZE, direction: DESC}) { totalSize edges { size node { name color } } }
        } } }
        repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
          totalCount
          nodes { name stargazerCount
            languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { totalSize edges { size node { name color } } } }
        }
      }
    }""" % LOGIN
    return gql(q)["user"]


def avatar_data_uri(url: str) -> str:
    sep = "&" if "?" in url else "?"
    with urllib.request.urlopen(f"{url}{sep}s=200", timeout=30) as r:
        mime = r.headers.get_content_type() or "image/png"
        return f"data:{mime};base64,{base64.b64encode(r.read()).decode()}"


def language_stack(repos: list[dict]) -> tuple[list[tuple[str, float, str]], int]:
    """Repository-weighted: each repo contributes 1, split by its byte shares."""
    weight, color, counted = Counter(), {}, 0
    for r in repos:
        if r["name"] == LOGIN:
            continue
        total = r["languages"]["totalSize"]
        if not total:
            continue
        counted += 1
        for e in r["languages"]["edges"]:
            weight[e["node"]["name"]] += e["size"] / total
            color[e["node"]["name"]] = e["node"]["color"] or P["muted"]
    s = sum(weight.values())
    ranked = [(name, 100 * w / s, color[name]) for name, w in weight.most_common()]
    return ranked, counted


# ------------------------------------------------------------- panels
def dashboard(user: dict, stack, stars: int, repo_count: int, now: dt.datetime) -> str:
    W, H = 1000, 600
    defs, board, loop_s, caption = build_chess_svg(x=58, y=100, square=48, palette=P)
    avatar = avatar_data_uri(user["avatarUrl"])
    b = []

    # window
    b.append(f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="20" fill="{P["panel"]}" stroke="url(#rim)"/>')
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        b.append(f'<circle cx="{26 + i * 20}" cy="24" r="6" fill="{c}"/>')
    b.append(t(94, 28, f"{LOGIN} / README.md", size=13, fill=P["muted"]))
    b.append(
        f'<circle cx="{W - 186}" cy="24" r="4" fill="{P["mint"]}">'
        f'<animate attributeName="opacity" values="1;.25;1" dur="2s" repeatCount="indefinite"/></circle>'
    )
    b.append(t(W - 24, 28, f"synced {now:%b %d, %Y}", size=12, fill=P["muted"], anchor="end"))
    b.append(f'<line x1="0" y1="46" x2="{W}" y2="46" stroke="{P["border"]}"/>')

    # chess panel
    b.append(f'<rect x="20" y="64" width="452" height="516" rx="14" fill="{P["panel2"]}" stroke="{P["border"]}"/>')
    b.append(t(40, 88, "CHESS.REPLAY", size=11, fill=P["mint"], weight=700, extra='letter-spacing="1.5"'))
    b.append(t(452, 88, "opera_game.pgn", size=11, fill=P["dim"], anchor="end"))
    b.append(board)
    b.append(t(40, 560, caption, size=11, fill=P["dim"]))

    # profile card
    b.append(f'<rect x="488" y="64" width="492" height="230" rx="14" fill="{P["panel2"]}" stroke="{P["border"]}"/>')
    b.append(
        f'<clipPath id="av"><circle cx="552" cy="140" r="44"/></clipPath>'
        f'<image href="{avatar}" xlink:href="{avatar}" x="508" y="96" width="88" height="88" clip-path="url(#av)" preserveAspectRatio="xMidYMid slice"/>'
        f'<circle cx="552" cy="140" r="49" fill="none" stroke="url(#rim)" stroke-width="3"/>'
    )
    b.append(t(616, 106, f"@{LOGIN}", size=13, fill=P["mint"]))
    b.append(t(614, 146, CONFIG["name"], cls="sans", size=34, weight=700))
    for i, line in enumerate(CONFIG["tagline"]):
        b.append(t(616, 172 + i * 20, line, cls="sans", size=14, fill=P["muted"]))
    b.append(t(956, 118, stars, cls="sans", size=40, weight=700, fill=P["mint"], anchor="end"))
    b.append(t(956, 138, "TOTAL STARS", size=10, fill=P["muted"], anchor="end", extra='letter-spacing="1.2"'))
    b.append(f'<line x1="508" y1="216" x2="960" y2="216" stroke="{P["border"]}"/>')
    cx = 508
    chips = [(c["name"], c["color"]) for c in CONFIG.get("chips", [])] or [(n, c) for n, _, c in stack[:4]]
    for name, color in chips:
        w = 30 + len(name) * 7
        b.append(
            f'<rect x="{cx}" y="228" width="{w}" height="24" rx="12" fill="{P["panel"]}" stroke="{P["border"]}"/>'
            f'<circle cx="{cx + 13}" cy="240" r="4" fill="{color}"/>'
        )
        b.append(t(cx + 23, 244.5, name, size=11.5, fill=P["text"]))
        cx += w + 8
    b.append(
        t(508, 276, f"{repo_count} public repos  ·  {CONFIG['publications']} publications  ·  {CONFIG['location']}", size=11.5, fill=P["dim"])
    )

    # now panel
    b.append(f'<rect x="488" y="310" width="492" height="270" rx="14" fill="{P["panel2"]}" stroke="{P["border"]}"/>')
    b.append(t(508, 336, "NOW.MD", size=11, fill=P["mint"], weight=700, extra='letter-spacing="1.5"'))
    b.append(t(960, 336, "$ cat now.md", size=11, fill=P["dim"], anchor="end"))
    y = 374
    for key, value, live in CONFIG["now"]:
        b.append(t(508, y, "▸", size=13, fill=P["mint"]))
        b.append(t(526, y, key.upper(), size=10.5, fill=P["muted"], extra='letter-spacing="1"'))
        if live:
            b.append(
                f'<circle cx="618" cy="{y - 4}" r="3.5" fill="{P["mint"]}">'
                f'<animate attributeName="opacity" values="1;.2;1" dur="1.6s" repeatCount="indefinite"/></circle>'
            )
        b.append(t(632, y, value, cls="sans", size=14.5, fill=P["text"]))
        y += 34
    b.append(t(508, y + 6, "$", size=13, fill=P["mint"]))
    b.append(f'<rect x="522" y="{y - 6}" width="9" height="15" fill="{P["mint"]}">{blink()}</rect>')

    return svg_doc(W, H, "".join(b), defs, f"{CONFIG['name']}: profile dashboard with an animated chess replay")


ICONS = {
    # 18x18 line icons drawn at (0,0)
    "portfolio": '<path d="M9 1 17 9 9 17 1 9Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
    "scholar": '<path d="M1 7 9 3l8 4-8 4-8-4Z M4.5 9v4c2.6 2 6.4 2 9 0V9" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
    "linkedin": '<rect x="1" y="1" width="16" height="16" rx="3.5" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="M5 8v5M5 5v.01M8.5 13V8m0 2.4c0-1.4 1-2.4 2.3-2.4S13 9 13 10.4V13" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" fill="none"/>',
    "email": '<rect x="1" y="3" width="16" height="12" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.7"/><path d="m2 5 7 5 7-5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>',
}


def link_button(label: str, icon: str) -> str:
    W, H = 240, 52
    body = (
        f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="14" fill="{P["panel2"]}" stroke="url(#rim)"/>'
        f'<g transform="translate(20 17)" color="{P["mint"]}">{ICONS[icon]}</g>'
        + t(50, 31, label, size=14, fill=P["text"], weight=700)
        + t(W - 20, 31, "↗", size=15, fill=P["dim"], anchor="end")
    )
    return svg_doc(W, H, body, title=label)


def projects_header(count: int) -> str:
    W, H = 1000, 62
    body = (
        f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="14" fill="{P["panel"]}" stroke="url(#rim)"/>'
        + t(26, 37, "PROJECTS.LIST", size=15, fill=P["mint"], weight=700, extra='letter-spacing="1.5"')
        + t(172, 37, "./projects.sh --pinned", size=13, fill=P["dim"])
        + f'<circle cx="{W - 96}" cy="32" r="4" fill="{P["mint"]}"/>'
        + t(W - 26, 37, f"{count} pinned", size=13, fill=P["muted"], anchor="end")
    )
    return svg_doc(W, H, body, title="Pinned projects")


SHORT_LANG = {"Jupyter Notebook": "Notebook", "TypeScript": "TS", "JavaScript": "JS"}


def project_card(repo: dict, meta: dict, now: dt.datetime, i: int) -> str:
    W, H = 494, 204
    title = meta.get("title") or repo["name"]
    if len(title) > 36:
        title = title[:35].rstrip("-_ ") + "…"
    desc = meta.get("description") or repo["description"] or "No description yet."
    lang = repo["primaryLanguage"] or {"name": "—", "color": P["muted"]}
    langs = repo["languages"]
    share = (langs["edges"][0]["size"] / langs["totalSize"]) if langs["totalSize"] else 0
    top_lang = langs["edges"][0]["node"] if langs["edges"] else lang

    b = [f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="14" fill="{P["panel2"]}" stroke="{P["border"]}"/>']
    b.append(f'<circle cx="26" cy="33" r="5" fill="{lang["color"] or P["muted"]}"/>')
    b.append(t(40, 38, title, size=15.5, fill=P["text"], weight=700))
    for j, line in enumerate(wrap(desc, 47, 3)):
        b.append(t(22, 70 + j * 19, line, size=12.5, fill=P["muted"]))

    # language-share ring
    r, cx, cy = 30, 438, 66
    circ = 2 * 3.14159 * r
    dash = circ * share
    color = top_lang.get("color") or P["mint"]
    b.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{P["border"]}" stroke-width="6"/>')
    b.append(
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" stroke-width="6" stroke-linecap="round" '
        f'stroke-dasharray="{dash:.1f} {circ:.1f}" transform="rotate(-90 {cx} {cy})">'
        f'<animate attributeName="stroke-dasharray" from="0 {circ:.1f}" to="{dash:.1f} {circ:.1f}" dur="1.2s" '
        f'begin="{0.15 * i:.2f}s" fill="freeze" calcMode="spline" keyTimes="0;1" keySplines=".3 0 .2 1"/></circle>'
    )
    b.append(t(cx, cy + 5, f"{round(share * 100)}%", size=13, fill=P["text"], weight=700, anchor="middle"))
    b.append(t(cx, cy + r + 20, SHORT_LANG.get(top_lang["name"], top_lang["name"]), size=10.5, fill=P["dim"], anchor="middle"))

    # tags
    x = 22
    for tag in meta.get("tags", [])[:3]:
        w = 22 + len(tag) * 7.2
        b.append(f'<rect x="{x}" y="140" width="{w}" height="24" rx="7" fill="{P["panel"]}" stroke="{P["border"]}"/>')
        b.append(t(x + 11, 156, tag, size=11.5, fill=P["sky"]))
        x += w + 8

    b.append(f'<line x1="22" y1="176" x2="{W-22}" y2="176" stroke="{P["border"]}"/>')
    b.append(t(22, 194, f"★ {repo['stargazerCount']}   ·   updated {ago(repo['pushedAt'], now)}", size=11.5, fill=P["dim"]))
    b.append(t(W - 22, 194, "open ↗", size=11.5, fill=P["mint"], anchor="end"))
    return svg_doc(W, H, "".join(b), title=f"{title}: {desc}")


def stack_panel(stack, counted: int) -> str:
    top = stack[:6]
    W, H = 1000, 96 + len(top) * 38 + 10
    b = [f'<rect x=".5" y=".5" width="{W-1}" height="{H-1}" rx="14" fill="{P["panel"]}" stroke="url(#rim)"/>']
    b.append(t(28, 44, "Language Stack", cls="sans", size=21, weight=700))
    b.append(t(28, 66, f"repository-weighted across {counted} repos", size=11.5, fill=P["mint"]))
    b.append(t(W - 40, 44, "> stack.scan", size=13, fill=P["dim"], anchor="end"))
    b.append(f'<rect x="{W - 38}" y="32" width="9" height="15" fill="{P["mint"]}">{blink()}</rect>')
    track_x, track_w = 330, W - 330 - 32
    y = 104
    for i, (name, pct, color) in enumerate(top):
        w = max(4, track_w * pct / 100)
        b.append(f'<circle cx="36" cy="{y - 4}" r="5" fill="{color}"/>')
        b.append(t(52, y, name, size=13.5, fill=P["text"]))
        b.append(t(300, y, f"{pct:.0f}%" if pct >= 1 else "<1%", size=13, fill=P["muted"], anchor="end"))
        b.append(f'<rect x="{track_x}" y="{y - 10}" width="{track_w}" height="10" rx="5" fill="{P["panel2"]}"/>')
        b.append(
            f'<rect x="{track_x}" y="{y - 10}" width="{w:.1f}" height="10" rx="5" fill="{color}">'
            f'<animate attributeName="width" from="0" to="{w:.1f}" dur="1.1s" begin="{0.1 * i:.1f}s" fill="freeze" '
            f'calcMode="spline" keyTimes="0;1" keySplines=".3 0 .2 1"/></rect>'
        )
        y += 38
    return svg_doc(W, H, "".join(b), title="Language stack")


# -------------------------------------------------------------- README
def readme(pinned: list[dict]) -> str:
    links = CONFIG["links"]
    out = [
        "<!-- Generated by scripts/build.py — edit profile.json instead. -->",
        '<p align="center">',
        f'  <img src="assets/dashboard.svg" width="100%" alt="{escape(CONFIG["name"])}: {escape(" · ".join(CONFIG["tagline"]))}. An animated board replays Morphy\'s Opera Game." />',
        "</p>",
        "",
        '<p align="center">',
    ]
    for ln in links:
        out.append(f'  <a href="{ln["url"]}"><img src="assets/link-{ln["icon"]}.svg" width="23.5%" alt="{escape(ln["label"])}" /></a>')
    out += ["</p>", "", '<p align="center">', '  <img src="assets/projects.svg" width="100%" alt="Pinned projects" />', "</p>", ""]
    for i in range(0, len(pinned), 2):
        out.append('<p align="center">')
        for j, repo in enumerate(pinned[i : i + 2], start=i):
            meta = CONFIG["repos"].get(repo["name"], {})
            title = meta.get("title") or repo["name"]
            out.append(f'  <a href="{repo["url"]}"><img src="assets/project-{j + 1}.svg" width="49%" alt="{escape(title)}" /></a>')
        out += ["</p>", ""]
    out += [
        '<p align="center">',
        '  <img src="assets/stack.svg" width="100%" alt="Language stack" />',
        "</p>",
        "",
        '<p align="center"><sub>Board replays Paul Morphy\'s 1858 Opera Game · pieces by Cburnett via python-chess · panels rebuilt daily by GitHub Actions</sub></p>',
        "",
    ]
    return "\n".join(out)


def main() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    user = fetch()
    repos = user["repositories"]["nodes"]
    pinned = user["pinnedItems"]["nodes"]
    stars = sum(r["stargazerCount"] for r in repos)
    stack, counted = language_stack(repos)

    ASSETS.mkdir(exist_ok=True)
    write = lambda name, s: (ASSETS / name).write_text(s, encoding="utf-8", newline="\n")
    write("dashboard.svg", dashboard(user, stack, stars, user["repositories"]["totalCount"], now))
    for ln in CONFIG["links"]:
        write(f'link-{ln["icon"]}.svg', link_button(ln["label"], ln["icon"]))
    write("projects.svg", projects_header(len(pinned)))
    for old in ASSETS.glob("project-*.svg"):
        old.unlink()
    for i, repo in enumerate(pinned):
        write(f"project-{i + 1}.svg", project_card(repo, CONFIG["repos"].get(repo["name"], {}), now, i))
    write("stack.svg", stack_panel(stack, counted))
    (ROOT / "README.md").write_text(readme(pinned), encoding="utf-8", newline="\n")
    print(f"built: {len(pinned)} pinned · {stars} stars · top langs {[s[0] for s in stack[:4]]}")


if __name__ == "__main__":
    main()
