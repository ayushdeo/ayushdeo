"""Rotating 3-D "language x mind" visual as a self-contained SMIL SVG.

GitHub READMEs can't run JavaScript, so the 3-D is done here: a point-cloud
brain is rotated in Python, projected with perspective for a fixed set of
frames, and each point/edge gets its own looping SMIL animation. Depth drives
size and opacity so the front of the brain reads brighter than the back.

On top of that, socially/morally loaded words stream from an "LLM" source into
the brain (neurons flash where they land), the six Moral Foundations orbit it,
and a typewriter line shows normative LLM phrasing.
"""

from __future__ import annotations

import math
import random
from html import escape

FRAMES = 20          # rotation keyframes (18 degrees apart, interpolated)
ROTATE_S = 26.0      # one full turn
PITCH = math.radians(20)
FOCAL = 3.4

# Moral Foundations Theory: colour per foundation
FOUNDATIONS = [
    ("care", "#7ee7b0"),
    ("fairness", "#7cc7ff"),
    ("loyalty", "#b39dff"),
    ("authority", "#ffcc66"),
    ("sanctity", "#ff9bd2"),
    ("liberty", "#ffa657"),
]
WORDS = [
    ("kind", 0), ("fair", 1), ("us", 2), ("should", 3), ("pure", 4), ("free", 5),
    ("harm", 0), ("cheat", 1), ("betray", 2), ("obey", 3), ("trust", 0), ("rights", 5),
]
LINES = [
    "most people would agree that…",
    "a reasonable person would…",
    "you should probably feel…",
]


def _fib(n: int):
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        y = 1 - 2 * (i + 0.5) / n
        r = math.sqrt(max(0.0, 1 - y * y))
        yield r * math.cos(golden * i), y, r * math.sin(golden * i)


def brain_points() -> list[tuple[float, float, float, str]]:
    """Two hemispheres with gyri wobble, plus cerebellum and stem."""
    pts = []
    for side in (-1, 1):
        for ux, uy, uz in _fib(68):
            if side * uz < -0.72:          # open the medial wall -> visible fissure
                continue
            g = 1 + 0.07 * math.sin(9 * ux + 3 * uz) * math.sin(7 * uy + 1.3)
            x, y, z = ux * 1.0 * g, uy * 0.6 * g, uz * 0.4 * g + side * 0.43
            if y < 0:
                y *= 0.78                   # flatter underside
            x -= 0.08 * max(0.0, -y)        # temporal lobes sweep back a little
            region = "front" if x > 0.3 else ("back" if x < -0.35 else "mid")
            pts.append((x, y, z, region))
    for ux, uy, uz in _fib(18):
        pts.append((-0.74 + ux * 0.28, -0.46 + uy * 0.15, uz * 0.5, "cereb"))
    for i in range(5):
        pts.append((-0.4, -0.5 - i * 0.08, 0.0, "stem"))
    return pts


def _edges(pts, k: int = 2) -> list[tuple[int, int]]:
    seen = set()
    for i, (x, y, z, _) in enumerate(pts):
        near = sorted(
            range(len(pts)),
            key=lambda j: (pts[j][0] - x) ** 2 + (pts[j][1] - y) ** 2 + (pts[j][2] - z) ** 2,
        )[1 : k + 1]
        for j in near:
            seen.add((min(i, j), max(i, j)))
    return sorted(seen)


def _project(p, yaw, cx, cy, scale):
    x, y, z = p
    xr = x * math.cos(yaw) + z * math.sin(yaw)
    zr = -x * math.sin(yaw) + z * math.cos(yaw)
    yr = y * math.cos(PITCH) - zr * math.sin(PITCH)
    zz = y * math.sin(PITCH) + zr * math.cos(PITCH)
    s = FOCAL / (FOCAL + zz)
    return cx + xr * scale * s, cy - yr * scale * s, zz


def build_brain_svg(*, x: float, y: float, w: float, h: float, palette: dict) -> tuple[str, str]:
    """Return (defs, body) drawing the visual inside the box (x, y, w, h)."""
    random.seed(11)
    p = palette
    cx, cy = x + w * 0.54, y + h * 0.45
    scale = w * 0.36
    yaws = [2 * math.pi * f / FRAMES for f in range(FRAMES + 1)]
    loop = f'dur="{ROTATE_S}s" repeatCount="indefinite"'
    color = {"front": p["mint"], "mid": p["sky"], "back": p["lav"], "cereb": p["lav"], "stem": p["dim"]}

    def near(zz):  # 0 (far) .. 1 (near)
        return max(0.0, min(1.0, (1.25 - zz) / 2.5))

    pts = brain_points()
    frames = [[_project(pt[:3], a, cx, cy, scale) for pt in pts] for a in yaws]

    def vals(seq):
        return ";".join(seq)

    defs = f"""
<radialGradient id="spark"><stop offset="0" stop-color="#ffffff" stop-opacity=".95"/>
  <stop offset=".35" stop-color="{p['mint']}" stop-opacity=".7"/><stop offset="1" stop-color="{p['mint']}" stop-opacity="0"/></radialGradient>
<radialGradient id="aura"><stop offset="0" stop-color="{p['lav']}" stop-opacity=".16"/>
  <stop offset="1" stop-color="{p['lav']}" stop-opacity="0"/></radialGradient>
<filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="1.4"/></filter>"""

    out = []
    # gentle float for everything brain-related
    out.append(
        '<g><animateTransform attributeName="transform" type="translate" values="0 0;0 -7;0 0" '
        'dur="7s" calcMode="spline" keyTimes="0;.5;1" keySplines=".45 0 .55 1;.45 0 .55 1" repeatCount="indefinite"/>'
    )
    out.append(f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{scale * 1.45:.0f}" ry="{scale * 1.15:.0f}" fill="url(#aura)"/>')

    # orbit ring (back half drawn first, dim)
    orx, ory = scale * 1.2, scale * 1.2 * math.sin(PITCH) * 1.15
    oy = cy + scale * 0.05
    out.append(
        f'<ellipse cx="{cx:.0f}" cy="{oy:.0f}" rx="{orx:.0f}" ry="{ory:.0f}" fill="none" '
        f'stroke="{p["border"]}" stroke-width="1" stroke-dasharray="3 5"/>'
    )

    # edges
    for i, j in _edges(pts):
        xs1 = vals(f"{fr[i][0]:.0f}" for fr in frames)
        ys1 = vals(f"{fr[i][1]:.0f}" for fr in frames)
        xs2 = vals(f"{fr[j][0]:.0f}" for fr in frames)
        ys2 = vals(f"{fr[j][1]:.0f}" for fr in frames)
        out.append(
            f'<line stroke="{p["sky"]}" stroke-width=".7" stroke-opacity=".17">'
            f'<animate attributeName="x1" values="{xs1}" {loop}/><animate attributeName="y1" values="{ys1}" {loop}/>'
            f'<animate attributeName="x2" values="{xs2}" {loop}/><animate attributeName="y2" values="{ys2}" {loop}/>'
            f'</line>'
        )

    # points
    for i, pt in enumerate(pts):
        xs = vals(f"{fr[i][0]:.0f}" for fr in frames)
        ys = vals(f"{fr[i][1]:.0f}" for fr in frames)
        rs = vals(f"{0.8 + 1.9 * near(fr[i][2]):.1f}" for fr in frames)
        op = vals(f"{0.18 + 0.82 * near(fr[i][2]):.2f}" for fr in frames)
        out.append(
            f'<circle fill="{color[pt[3]]}">'
            f'<animate attributeName="cx" values="{xs}" {loop}/><animate attributeName="cy" values="{ys}" {loop}/>'
            f'<animate attributeName="r" values="{rs}" {loop}/><animate attributeName="opacity" values="{op}" {loop}/></circle>'
        )

    # neuron sparks: follow a cortex point, flash when a word lands
    word_cycle = 9.6
    cortex = [i for i, pt in enumerate(pts) if pt[3] in ("front", "mid", "back")]
    for n in range(len(WORDS)):
        i = random.choice(cortex)
        xs = vals(f"{fr[i][0]:.0f}" for fr in frames)
        ys = vals(f"{fr[i][1]:.0f}" for fr in frames)
        begin = n * word_cycle / len(WORDS)
        land = 2.6 / word_cycle
        out.append(
            f'<circle r="9" fill="url(#spark)" opacity="0">'
            f'<animate attributeName="cx" values="{xs}" {loop}/><animate attributeName="cy" values="{ys}" {loop}/>'
            f'<animate attributeName="opacity" values="0;0;1;0;0" keyTimes="0;{land:.3f};{land + 0.02:.3f};{land + 0.12:.3f};1" '
            f'dur="{word_cycle}s" begin="{begin:.2f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="r" values="3;3;12;5;3" keyTimes="0;{land:.3f};{land + 0.03:.3f};{land + 0.12:.3f};1" '
            f'dur="{word_cycle}s" begin="{begin:.2f}s" repeatCount="indefinite"/></circle>'
        )

    # moral foundations orbiting in 3-D
    orbit_s = ROTATE_S * 1.6
    for k, (label, col) in enumerate(FOUNDATIONS):
        phase = 2 * math.pi * k / len(FOUNDATIONS)
        tx, ty, op, right = [], [], [], []
        for a in yaws:
            ang = -a + phase
            px, py, pz = _project((1.2 * math.cos(ang), 0.05, 1.2 * math.sin(ang)), 0, cx, cy, scale)
            tx.append(f"{px:.0f} {py:.0f}")
            op.append(f"{0.25 + 0.75 * near(pz):.2f}")
            right.append(px > cx)
        # Labels always face inward so they never leave the panel: on the right
        # half of the orbit the label sits left of its dot, and vice versa.
        keys = ";".join(f"{i / FRAMES:.4f}" for i in range(FRAMES + 1))
        show_r = vals("0" if r else "1" for r in right)
        show_l = vals("1" if r else "0" for r in right)
        font = 'font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="10.5"'
        anim = f'calcMode="discrete" keyTimes="{keys}" dur="{orbit_s:.1f}s" repeatCount="indefinite"'
        out.append(
            f'<g><animateTransform attributeName="transform" type="translate" values="{vals(tx)}" dur="{orbit_s:.1f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="{vals(op)}" dur="{orbit_s:.1f}s" repeatCount="indefinite"/>'
            f'<circle r="3.6" fill="{col}"/><circle r="8" fill="{col}" opacity=".18"/>'
            f'<text x="9" y="4" {font} fill="{col}">{label}<animate attributeName="opacity" values="{show_r}" {anim}/></text>'
            f'<text x="-9" y="4" {font} fill="{col}" text-anchor="end">{label}<animate attributeName="opacity" values="{show_l}" {anim}/></text></g>'
        )
    out.append("</g>")  # end float

    # LLM source + word stream
    sx, sy = x + 26, y + h - 66
    out.append(
        f'<rect x="{sx - 4}" y="{sy - 14}" width="44" height="26" rx="7" fill="{p["panel"]}" stroke="{p["mint"]}" stroke-opacity=".6"/>'
        f'<text x="{sx + 18}" y="{sy + 4}" text-anchor="middle" class="mono" font-size="11" font-weight="700" fill="{p["mint"]}">LLM</text>'
    )
    for n, (word, f) in enumerate(WORDS):
        col = FOUNDATIONS[f][1]
        begin = n * word_cycle / len(WORDS)
        jitter = random.uniform(-40, 40)
        tx, ty = cx + random.uniform(-scale * 0.5, scale * 0.4), cy + random.uniform(-scale * 0.35, scale * 0.25)
        path = f"M{sx + 44},{sy - 2} C{sx + 120},{sy - 30 + jitter} {tx - 90},{ty + 70} {tx:.0f},{ty:.0f}"
        land = 2.6 / word_cycle
        out.append(
            f'<text class="mono" font-size="12" font-weight="700" fill="{col}" text-anchor="middle" opacity="0">{escape(word)}'
            f'<animateMotion path="{path}" keyPoints="0;1;1" keyTimes="0;{land:.3f};1" calcMode="linear" '
            f'dur="{word_cycle}s" begin="{begin:.2f}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0;1;1;0;0" keyTimes="0;.04;{land - 0.05:.3f};{land:.3f};1" '
            f'dur="{word_cycle}s" begin="{begin:.2f}s" repeatCount="indefinite"/></text>'
        )

    # typewriter: normative LLM phrasing
    ty0 = y + h - 18
    seg = 6.0
    total = seg * len(LINES)
    out.append(t_mono(x + 22, ty0, "llm.generate() ▸", p["dim"], 11.5))
    for n, line in enumerate(LINES):
        text = f"“{line}”"
        width = len(text) * 7.2
        a0, a1, a2 = n * seg / total, (n * seg + 2.4) / total, (n * seg + seg - 0.4) / total
        clip = f"tw{n}"
        out.append(
            f'<clipPath id="{clip}"><rect x="{x + 152}" y="{ty0 - 14}" height="20" width="0">'
            f'<animate attributeName="width" values="0;0;{width:.0f};{width:.0f};0;0" '
            f'keyTimes="0;{a0:.3f};{a1:.3f};{a2:.3f};{a2 + 0.001:.3f};1" dur="{total}s" repeatCount="indefinite"/></rect></clipPath>'
            f'<text x="{x + 152}" y="{ty0}" clip-path="url(#{clip})" class="mono" font-size="12" fill="{p["text"]}">{escape(text)}</text>'
        )

    return defs, "\n".join(out)


def t_mono(x, y, s, fill, size):
    return f'<text x="{x}" y="{y}" class="mono" font-size="{size}" fill="{fill}">{escape(s)}</text>'
