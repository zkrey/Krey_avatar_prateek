"""
Glicko-2 rating from pairwise votes — the ranking engine for the social-testing loop.

Each look is a "player"; each rank vote is a game (winner beats loser). We run ONE rating
period over all votes and return a rating + reliability (RD) per look, so a look with 2 votes
isn't ranked with false confidence next to one with 200. Pure stdlib, no dependency.

Reference: Glickman, "Example of the Glicko-2 system" (tau=0.5). Scale constant 173.7178.
"""
from __future__ import annotations
import math

TAU = 0.5              # system constant: constrains volatility change (0.3–1.2 typical)
SCALE = 173.7178
BASE_R = 1500.0
BASE_RD = 350.0
BASE_VOL = 0.06
EPS = 1e-6


class _P:
    __slots__ = ("r", "rd", "vol")

    def __init__(self, r=BASE_R, rd=BASE_RD, vol=BASE_VOL):
        self.r, self.rd, self.vol = r, rd, vol

    # Glicko-2 (internal) scale
    @property
    def mu(self):
        return (self.r - BASE_R) / SCALE

    @property
    def phi(self):
        return self.rd / SCALE


def _g(phi):
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _E(mu, mu_j, phi_j):
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def _new_vol(phi, v, delta, vol):
    """Iterative volatility update (Illinois algorithm), per the Glicko-2 paper."""
    a = math.log(vol * vol)
    d2 = delta * delta
    phi2 = phi * phi

    def f(x):
        ex = math.exp(x)
        num = ex * (d2 - phi2 - v - ex)
        den = 2.0 * (phi2 + v + ex) ** 2
        return num / den - (x - a) / (TAU * TAU)

    A = a
    if d2 > phi2 + v:
        B = math.log(d2 - phi2 - v)
    else:
        k = 1
        while f(a - k * TAU) < 0:
            k += 1
        B = a - k * TAU
    fA, fB = f(A), f(B)
    while abs(B - A) > EPS:
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB <= 0:
            A, fA = B, fB
        else:
            fA = fA / 2.0
        B, fB = C, fC
    return math.exp(A / 2.0)


def bradley_terry(items: list[str], votes: list[tuple[str, str]],
                  prior: float = 0.5) -> dict[str, float]:
    """Regularized Bradley-Terry (Zermelo MMM). Returns normalized strengths (sum = len(items)).

    The `prior` adds a light virtual tie per pair so strengths stay finite even when an item wins
    or loses all its matchups (the classic BT divergence with sparse data). Ideal for 2–5 fits.
    """
    items = list(items)
    if not items:
        return {}
    wins = {i: 0.0 for i in items}
    pair = {}  # (i,j) -> count i beat j
    for w, l in votes:
        if w in wins and l in wins and w != l:
            wins[w] += 1.0
            pair[(w, l)] = pair.get((w, l), 0) + 1
    n = len(items)
    p = {i: 1.0 for i in items}
    for _ in range(200):
        newp = {}
        for i in items:
            num = wins[i] + prior * (n - 1)
            den = 0.0
            for j in items:
                if j == i:
                    continue
                nij = pair.get((i, j), 0) + pair.get((j, i), 0) + 2 * prior
                den += nij / (p[i] + p[j])
            newp[i] = num / den if den else p[i]
        s = sum(newp.values()) or 1.0
        p = {i: newp[i] / s * n for i in items}
    return p


def p_best(strengths: dict[str, float]) -> dict[str, float]:
    """P(item is the single best) = strength share. Sums to 1."""
    tot = sum(strengths.values()) or 1.0
    return {i: s / tot for i, s in strengths.items()}


def rank_probabilities(strengths: dict[str, float]) -> dict[str, list[float]]:
    """Plackett-Luce P(item finishes at each position 1..k), exact by enumeration (k<=~7).

    Returns {item: [P(1st), P(2nd), ...]}. This is the 'granular probability of each rank'."""
    import itertools
    items = list(strengths)
    k = len(items)
    if k == 0:
        return {}
    if k > 7:  # enumeration blows up; fall back to strength share in slot 0
        pb = p_best(strengths)
        return {i: [pb[i]] + [0.0] * (k - 1) for i in items}
    probs = {i: [0.0] * k for i in items}
    for perm in itertools.permutations(items):
        # PL probability of this full ordering
        pr = 1.0
        remaining = sum(strengths.values())
        for pos, it in enumerate(perm):
            s = strengths[it]
            pr *= s / remaining if remaining else 0.0
            remaining -= s
        for pos, it in enumerate(perm):
            probs[it][pos] += pr
    return probs


def kendall_tau(order_a: list[str], order_b: list[str]) -> float:
    """Kendall's tau between two rankings (agreement). +1 identical, -1 reversed, 0 unrelated.

    Only items present in BOTH orders are compared."""
    import itertools
    common = [x for x in order_a if x in set(order_b)]
    ra = {x: i for i, x in enumerate(order_a)}
    rb = {x: i for i, x in enumerate(order_b)}
    c = d = 0
    for i, j in itertools.combinations(common, 2):
        s = (ra[i] - ra[j]) * (rb[i] - rb[j])
        if s > 0:
            c += 1
        elif s < 0:
            d += 1
    return (c - d) / (c + d) if (c + d) else 1.0


def rate(look_ids: list[str], votes: list[tuple[str, str]]) -> dict[str, dict]:
    """Given look ids and (winner_id, loser_id) pairs, return
    {look_id: {rating, rd, wins, games}} after one Glicko-2 rating period.

    Looks with no games keep the provisional 1500 / RD 350 (max uncertainty)."""
    players = {lid: _P() for lid in look_ids}
    for w, l in votes:
        players.setdefault(w, _P())
        players.setdefault(l, _P())
    games: dict[str, list] = {lid: [] for lid in players}
    wins: dict[str, int] = {lid: 0 for lid in players}
    for w, l in votes:
        if not w or not l or w == l:
            continue
        games[w].append((l, 1.0))
        games[l].append((w, 0.0))
        wins[w] += 1

    out = {}
    for lid, p in players.items():
        gl = games[lid]
        if not gl:
            # no games: RD grows toward max but rating unchanged
            new_phi = min(math.sqrt(p.phi ** 2 + p.vol ** 2), BASE_RD / SCALE)
            out[lid] = {"rating": round(p.r, 1), "rd": round(new_phi * SCALE, 1),
                        "wins": 0, "games": 0}
            continue
        v_inv = 0.0
        delta_sum = 0.0
        for opp_id, score in gl:
            opp = players[opp_id]
            g = _g(opp.phi)
            e = _E(p.mu, opp.mu, opp.phi)
            v_inv += g * g * e * (1.0 - e)
            delta_sum += g * (score - e)
        v = 1.0 / v_inv if v_inv else float("inf")
        delta = v * delta_sum
        new_vol = _new_vol(p.phi, v, delta, p.vol)
        phi_star = math.sqrt(p.phi ** 2 + new_vol ** 2)
        new_phi = 1.0 / math.sqrt(1.0 / (phi_star ** 2) + 1.0 / v)
        new_mu = p.mu + new_phi ** 2 * delta_sum
        out[lid] = {
            "rating": round(new_mu * SCALE + BASE_R, 1),
            "rd": round(new_phi * SCALE, 1),
            "wins": wins[lid],
            "games": len(gl),
        }
    return out
