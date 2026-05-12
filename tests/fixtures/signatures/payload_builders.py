def build_first(
    report: Json,
    targets: Json,
    budgets: BudgetConfig | None = None,
) -> Json:
    resolved_budgets = budgets or BudgetConfig()
    payload = {
        "schema_version": "first",
        "summary": report["summary"],
        "items": targets["targets"][:10],
        "rules": [
            "alpha",
            "beta",
            "gamma",
            "delta",
            "epsilon",
            "zeta",
            "eta",
            "theta",
        ],
    }
    return enforce_embedded_target_budget(
        payload,
        target_key="items",
        max_bytes=resolved_budgets.report,
    )


def build_second(
    report: Json,
    targets: Json,
    budgets: BudgetConfig | None = None,
) -> Json:
    resolved_budgets = budgets or BudgetConfig()
    payload = {
        "schema_version": "second",
        "summary": report["summary"],
        "items": targets["targets"][:5],
        "rules": [
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
        ],
    }
    return enforce_embedded_target_budget(
        payload,
        target_key="items",
        max_bytes=resolved_budgets.agent_summary,
    )
