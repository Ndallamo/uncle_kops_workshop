from decimal import Decimal, ROUND_HALF_UP


def format_rand(amount: Decimal | int | float | str) -> str:
    rounded_amount = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return f'R {rounded_amount:.2f}'
