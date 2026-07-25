def brinson_attribution(
    portfolio: dict[str, dict],
    benchmark: dict[str, dict],
) -> dict:
    all_sectors = set(portfolio.keys()) | set(benchmark.keys())
    total_allocation = 0.0
    total_selection = 0.0
    total_interaction = 0.0
    sectors_detail: dict[str, dict] = {}

    for sector in all_sectors:
        port = portfolio.get(sector, {"weight": 0.0, "return": 0.0})
        bench = benchmark.get(sector, {"weight": 0.0, "return": 0.0})

        wp = port["weight"]
        rp = port["return"]
        wb = bench["weight"]
        rb = bench["return"]

        allocation = (wp - wb) * rb
        selection = wb * (rp - rb)
        interaction = (wp - wb) * (rp - rb)

        total_allocation += allocation
        total_selection += selection
        total_interaction += interaction

        sectors_detail[sector] = {
            "portfolio_weight": wp,
            "benchmark_weight": wb,
            "portfolio_return": rp,
            "benchmark_return": rb,
            "allocation_effect": round(allocation, 6),
            "selection_effect": round(selection, 6),
            "interaction_effect": round(interaction, 6),
        }

    total_excess = total_allocation + total_selection + total_interaction

    return {
        "allocation_effect": round(total_allocation, 6),
        "selection_effect": round(total_selection, 6),
        "interaction_effect": round(total_interaction, 6),
        "total_excess_return": round(total_excess, 6),
        "sectors": sectors_detail,
    }
