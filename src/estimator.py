def expected_profit(
    buy: float,
    ship: float,
    est_working: float,
    est_as_is: float,
    p_fix: float,
    fee_rate: float,
    parts_cost: float,
    time_cost: float,
) -> float:
    exp_resale = est_working * p_fix + est_as_is * (1 - p_fix)
    fees = exp_resale * fee_rate
    return exp_resale - fees - (buy + ship + parts_cost + time_cost)