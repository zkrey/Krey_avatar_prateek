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
