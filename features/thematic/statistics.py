"""Thematic ranking deliberately differs from the tests' percentage ranking."""
from fractions import Fraction


def best_attempt(attempts):
    finished = [a for a in attempts if a["state"] == "finished"]
    return max(finished, key=lambda a: (a["correct_count"], Fraction(a["correct_count"], a["total_count"]),
                                       a["submitted_at"], a["id"]), default=None)
