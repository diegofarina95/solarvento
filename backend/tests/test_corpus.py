"""Layer 4 — harness de regresión del corpus de facturas.

Pasa cada contrato del corpus por el pipeline determinista (contract_to_bill),
lo clasifica frente a la verdad etiquetada y emite un scorecard agregado. Falla
el CI si CUALQUIER factura es *wrong-but-computed* (calculada con un valor
equivocado) o *computed-should-review* (calculada cuando debía revisarse): ambos
son fallos duros. El corpus es la red contra la deriva del extractor LLM.
"""

import json
from pathlib import Path

import pytest

from app.bill_normalise import contract_to_bill

CORPUS_DIR = Path(__file__).parent / "corpus"


def _corpus_cases():
    cases = []
    for entry in sorted(CORPUS_DIR.iterdir()):
        if entry.is_dir() and (entry / "contract.json").exists():
            cases.append(entry)
    return cases


def _close(a, b, tol_pct=0.01, tol_abs=5.0):
    if a is None or b is None:
        return False
    return abs(a - b) <= max(tol_pct * max(abs(a), abs(b)), tol_abs)


def _resolved_annual(bill: dict) -> float | None:
    res = bill.get("consumption_resolution") or {}
    return res.get("annual_kwh")


def _classify(entry: Path) -> dict:
    contract = json.loads((entry / "contract.json").read_text(encoding="utf-8"))
    truth = json.loads((entry / "ground_truth.json").read_text(encoding="utf-8"))
    bill = contract_to_bill(contract)
    computed = not bill["needs_review"]
    expected = truth.get("expected_outcome", "compute")
    # El anual autoritativo es el RESUELTO (histórico/declarado/estimado), no el
    # consumo del propio periodo de la factura (que puede ser sub-anual).
    annual = _resolved_annual(bill)
    tags = truth.get("tags")

    if expected == "review":
        outcome = "correct" if not computed else "computed_should_review"
        return {"name": entry.name, "outcome": outcome, "annual": annual, "tags": tags}

    if not computed:
        return {"name": entry.name, "outcome": "review", "annual": annual, "tags": tags}

    checks = _close(annual, truth.get("annual_consumption_kwh"), tol_pct=0.02, tol_abs=20)
    split_truth = truth.get("period_split")
    if split_truth and checks:
        periods = bill.get("consumption_periods") or {}
        checks = all(
            _close(periods.get(k), v, tol_abs=2) for k, v in split_truth.items()
        )
    if truth.get("contracted_power_kw") is not None and checks:
        checks = _close(bill.get("contracted_power_kw"), truth["contracted_power_kw"], tol_abs=0.1)
    outcome = "correct" if checks else "wrong_but_computed"
    return {"name": entry.name, "outcome": outcome, "annual": annual, "tags": tags}


def test_corpus_scorecard(capsys):
    cases = _corpus_cases()
    assert cases, "el corpus está vacío"
    results = [_classify(c) for c in cases]

    tally: dict[str, int] = {}
    for r in results:
        tally[r["outcome"]] = tally.get(r["outcome"], 0) + 1

    lines = ["", "=== CORPUS SCORECARD ==="]
    for r in results:
        tags = f" [{r['tags']}]" if r.get("tags") else ""
        lines.append(f"  {r['outcome']:22} {r['name']:30} annual={r['annual']}{tags}")
    lines.append(
        f"  TOTAL: {len(results)} | correct={tally.get('correct', 0)} "
        f"review={tally.get('review', 0)} "
        f"WRONG_BUT_COMPUTED={tally.get('wrong_but_computed', 0)} "
        f"COMPUTED_SHOULD_REVIEW={tally.get('computed_should_review', 0)}"
    )
    with capsys.disabled():
        print("\n".join(lines))

    # Fallo duro: ninguna factura puede calcularse con un valor equivocado ni
    # calcularse cuando debía revisarse.
    hard_failures = [
        r for r in results if r["outcome"] in ("wrong_but_computed", "computed_should_review")
    ]
    assert not hard_failures, f"facturas peligrosas (calculadas mal): {hard_failures}"


@pytest.mark.parametrize("entry", _corpus_cases(), ids=lambda p: p.name)
def test_corpus_entry_not_dangerous(entry):
    # Un test por factura para localizar la culpable en el informe de CI.
    result = _classify(entry)
    assert result["outcome"] not in ("wrong_but_computed", "computed_should_review"), result
