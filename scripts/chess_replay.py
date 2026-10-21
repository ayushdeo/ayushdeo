"""Animated chess replay as a self-contained SVG (SMIL), safe for GitHub READMEs.

GitHub strips JavaScript, but SVG <animate>/<animateTransform> play fine, so the
whole game is baked into one looping timeline: pieces glide between squares,
captures fade out, the last move and checks are highlighted, and a ticker shows
the move in algebraic notation.

Pieces are the "cburnett" set bundled with python-chess (GPL / BSD / GFDL).
"""

from __future__ import annotations

import io
import re

import chess
import chess.pgn
import chess.svg

# Paul Morphy vs. Duke Karl of Brunswick & Count Isouard, Paris 1858 ("The Opera Game")
OPERA_GAME = """
[Event "Paris"]
[White "Paul Morphy"]
[Black "Duke Karl / Count Isouard"]
[Result "1-0"]

1. e4 e5 2. Nf3 d6 3. d4 Bg4 4. dxe5 Bxf3 5. Qxf3 dxe5 6. Bc4 Nf6 7. Qb3 Qe7
8. Nc3 c6 9. Bg5 b5 10. Nxb5 cxb5 11. Bxb5+ Nbd7 12. O-O-O Rd8 13. Rxd7 Rxd7
14. Rd1 Qe6 15. Bxd7+ Nxd7 16. Qb8+ Nxb8 17. Rd8# 1-0
"""

# Timing (seconds)
INTRO = 1.4      # starting position on screen
PLY = 1.05       # one half-move slot
GLIDE = 0.42     # how long a piece takes to travel
OUTRO = 4.0      # hold the mate
FADE = 0.5       # cross-fade at the loop seam

EASE = "0.45 0 0.2 1"


def _recolor(svg: str, white: bool, light: str, ink: str, accent: str) -> str:
    """Swap the set's black/white for the dashboard palette."""

    def norm(c: str) -> str:
        c = c.lower()
        return {"#000000": "#000", "#ffffff": "#fff"}.get(c, c)

    def pick(prop: str, color: str) -> str:
        color = norm(color)
        if white:
            if color == "#fff":
                return light
            return ink  # outlines + dark details
        if color == "#000":
            return accent if prop == "fill" else ink
        return ink  # white detail lines on black pieces

    svg = re.sub(
        r'(fill|stroke)="(#[0-9a-fA-F]{3,6})"',
        lambda m: f'{m.group(1)}="{pick(m.group(1), m.group(2))}"',
        svg,
    )
    svg = re.sub(
        r"(fill|stroke)\s*:\s*(#[0-9a-fA-F]{3,6})",
        lambda m: f"{m.group(1)}:{pick(m.group(1), m.group(2))}",
        svg,
    )
    return svg


def build_chess_svg(
    *,
    x: float,
    y: float,
    square: float,
    palette: dict,
    pgn: str = OPERA_GAME,
) -> tuple[str, str, float, str]:
    """Return (defs, body, loop_seconds, caption) to embed in a larger SVG.

    `body` draws the board with its top-left corner at (x, y).
    """
    game = chess.pgn.read_game(io.StringIO(pgn))
    board = game.board()
    moves = list(game.mainline_moves())
    n = len(moves)
    total = INTRO + n * PLY + OUTRO + FADE

    def kt(t: float) -> str:
        return f"{max(0.0, min(1.0, t / total)):.5f}"

    def sq_xy(sq: int) -> tuple[float, float]:
        file, rank = chess.square_file(sq), chess.square_rank(sq)
        return x + file * square, y + (7 - rank) * square

    # ---- track every piece by identity through the game
    pieces: dict[int, dict] = {}          # id -> {symbol, path: [(t, sq)], captured_at}
    at: dict[int, int] = {}               # square -> id
    for sq, pc in board.piece_map().items():
        pid = len(pieces)
        pieces[pid] = {"symbol": pc.symbol(), "path": [(0.0, sq)], "captured_at": None}
        at[sq] = pid

    last_move: list[tuple[float, int, int]] = []   # (t, from, to)
    checks: list[tuple[float, float, int]] = []     # (t_start, t_end, king square)
    ticker: list[tuple[float, float, str]] = []     # (t_start, t_end, text)

    for i, mv in enumerate(moves):
        t = INTRO + i * PLY
        san = board.san(mv)
        num = board.fullmove_number
        label = f"{num}. {san}" if board.turn == chess.WHITE else f"{num}... {san}"

        moving = at.pop(mv.from_square)
        if board.is_en_passant(mv):
            victim_sq = mv.to_square + (-8 if board.turn == chess.WHITE else 8)
        else:
            victim_sq = mv.to_square
        if victim_sq in at:
            pieces[at.pop(victim_sq)]["captured_at"] = t + GLIDE * 0.75

        if board.is_castling(mv):
            kingside = chess.square_file(mv.to_square) == 6
            rank = chess.square_rank(mv.from_square)
            r_from = chess.square(7 if kingside else 0, rank)
            r_to = chess.square(5 if kingside else 3, rank)
            rook = at.pop(r_from)
            pieces[rook]["path"].append((t, r_to))
            at[r_to] = rook

        pieces[moving]["path"].append((t, mv.to_square))
        at[mv.to_square] = moving
        board.push(mv)

        end = t + PLY if i < n - 1 else total
        last_move.append((t, mv.from_square, mv.to_square))
        ticker.append((t, end, label))
        if board.is_check():
            checks.append((t + GLIDE, end, board.king(board.turn)))

    result = "checkmate" if board.is_checkmate() else ""
    p = palette

    # ---- defs: recolored piece glyphs
    defs = []
    for sym in "KQRBNPkqrbnp":
        g = chess.svg.PIECES[sym]
        g = re.sub(r'\sid="[^"]*"', "", g, count=1)
        g = _recolor(g, sym.isupper(), p["piece_light"], p["piece_ink"], p["piece_accent"])
        defs.append(f'<g id="pc-{sym}">{g}</g>')
    defs_svg = "\n".join(defs)

    out = []
    loop = f'dur="{total:.2f}s" repeatCount="indefinite"'

    # whole board fades at the loop seam so the reset is invisible
    fade_keys = f"0;{kt(0.35)};{kt(total - FADE)};1"
    out.append(
        f'<g><animate attributeName="opacity" values="0;1;1;0" keyTimes="{fade_keys}" {loop}/>'
    )

    # squares
    for rank in range(8):
        for file in range(8):
            sx, sy = x + file * square, y + rank * square
            color = p["sq_light"] if (rank + file) % 2 == 0 else p["sq_dark"]
            out.append(f'<rect x="{sx}" y="{sy}" width="{square}" height="{square}" fill="{color}"/>')

    # last-move highlight (from + to), stepping per ply
    for idx, key in ((1, "from"), (2, "to")):
        vals, times = ["0 0"], ["0"]
        op_vals, op_times = ["0"], ["0"]
        for t, frm, to in last_move:
            sq = frm if key == "from" else to
            sx, sy = sq_xy(sq)
            vals.append(f"{sx - x} {sy - y}")
            times.append(kt(t))
            if len(op_vals) == 1:
                op_vals.append("1")
                op_times.append(kt(t))
        op_vals.append("1")
        op_times.append("1")
        out.append(
            f'<rect x="{x}" y="{y}" width="{square}" height="{square}" fill="{p["hl"]}" '
            f'fill-opacity="{0.22 if key == "from" else 0.38}" opacity="0">'
            f'<animateTransform attributeName="transform" type="translate" calcMode="discrete" '
            f'values="{";".join(vals)}" keyTimes="{";".join(times)}" {loop}/>'
            f'<animate attributeName="opacity" calcMode="discrete" values="{";".join(op_vals)}" '
            f'keyTimes="{";".join(op_times)}" {loop}/></rect>'
        )

    # check / mate glow on the king
    for t0, t1, ksq in checks:
        kx, ky = sq_xy(ksq)
        out.append(
            f'<rect x="{kx}" y="{ky}" width="{square}" height="{square}" fill="url(#checkGlow)" opacity="0">'
            f'<animate attributeName="opacity" calcMode="discrete" values="0;1;0" '
            f'keyTimes="0;{kt(t0)};{kt(t1)}" {loop}/></rect>'
        )

    # coordinates
    for i in range(8):
        out.append(
            f'<text x="{x - 12}" y="{y + i * square + square / 2 + 4}" class="coord" text-anchor="middle">{8 - i}</text>'
        )
        out.append(
            f'<text x="{x + i * square + square / 2}" y="{y + 8 * square + 16}" class="coord" text-anchor="middle">{"abcdefgh"[i]}</text>'
        )

    # pieces
    scale = square / 45
    for pid, pc in pieces.items():
        path = pc["path"]
        sx0, sy0 = sq_xy(path[0][1])
        vals, times = [f"{sx0} {sy0}"], ["0"]
        cur = (sx0, sy0)
        for t, sq in path[1:]:
            nx, ny = sq_xy(sq)
            vals += [f"{cur[0]} {cur[1]}", f"{nx} {ny}"]
            times += [kt(t), kt(t + GLIDE)]
            cur = (nx, ny)
        vals.append(f"{cur[0]} {cur[1]}")
        times.append("1")
        splines = ";".join([EASE] * (len(vals) - 1))
        anim = (
            f'<animateTransform attributeName="transform" type="translate" calcMode="spline" '
            f'values="{";".join(vals)}" keyTimes="{";".join(times)}" keySplines="{splines}" {loop}/>'
        )
        fade = ""
        if pc["captured_at"] is not None:
            tc = pc["captured_at"]
            fade = (
                f'<animate attributeName="opacity" values="1;1;0;0" '
                f'keyTimes="0;{kt(tc - 0.12)};{kt(tc + 0.08)};1" {loop}/>'
            )
        out.append(
            f'<g transform="translate({sx0} {sy0})">{anim}'
            f'<g>{fade}<use href="#pc-{pc["symbol"]}" xlink:href="#pc-{pc["symbol"]}" transform="scale({scale:.4f})"/></g></g>'
        )

    # ticker: current move in SAN
    ty = y + 8 * square + 46
    for t0, t1, text in ticker:
        out.append(
            f'<text x="{x}" y="{ty}" class="ticker" opacity="0">{text}'
            f'<animate attributeName="opacity" calcMode="discrete" values="0;1;0" '
            f'keyTimes="0;{kt(t0)};{kt(t1)}" {loop}/></text>'
        )
    out.append(
        f'<text x="{x}" y="{ty}" class="ticker dim" opacity="1">start position'
        f'<animate attributeName="opacity" calcMode="discrete" values="1;0" keyTimes="0;{kt(INTRO)}" {loop}/></text>'
    )
    if result:
        out.append(
            f'<text x="{x + 8 * square}" y="{ty}" class="ticker mate" text-anchor="end" opacity="0">{result.upper()}'
            f'<animate attributeName="opacity" calcMode="discrete" values="0;1;0" '
            f'keyTimes="0;{kt(INTRO + (n - 1) * PLY + GLIDE)};{kt(total - FADE)}" {loop}/></text>'
        )

    out.append("</g>")

    headers = game.headers
    caption = f'{headers.get("White")} vs {headers.get("Black")} · {headers.get("Event")} 1858'
    return defs_svg, "\n".join(out), total, caption
