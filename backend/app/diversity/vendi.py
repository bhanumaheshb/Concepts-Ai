"""Vendi score: the effective number of distinct concepts in a portfolio.

exp(Shannon entropy of the eigenvalues of S/n). Ten near-clones score ~1;
ten genuinely different concepts score 8-9. Interpretable to a non-technical
designer, which is why it is the headline metric rather than mean distance.

Pure Python Jacobi eigensolver — n is 10-20 here, so there is no reason to take
a numpy dependency for it.
"""
from __future__ import annotations

import math


def symmetric_eigenvalues(matrix: list[list[float]], sweeps: int = 60, tol: float = 1e-10) -> list[float]:
    n = len(matrix)
    if n == 0:
        return []
    a = [row[:] for row in matrix]
    for _ in range(sweeps):
        off = math.sqrt(sum(a[i][j] ** 2 for i in range(n) for j in range(n) if i != j))
        if off < tol:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if abs(a[p][q]) < tol:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(n):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(n):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
    return [a[i][i] for i in range(n)]


def vendi_score(similarity_matrix: list[list[float]]) -> float:
    n = len(similarity_matrix)
    if n == 0:
        return 0.0
    if n == 1:
        return 1.0
    scaled = [[v / n for v in row] for row in similarity_matrix]
    eigs = [max(0.0, e) for e in symmetric_eigenvalues(scaled)]
    total = sum(eigs)
    if total <= 0:
        return 1.0
    eigs = [e / total for e in eigs]
    entropy = -sum(e * math.log(e) for e in eigs if e > 1e-12)
    return math.exp(entropy)
