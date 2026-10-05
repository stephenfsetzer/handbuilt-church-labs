"""Shared cash wording for the Finance data builder and report renderer."""


def signed_money(value):
    return ("−" if value < 0 else "") + f"${abs(round(value)):,}"


def cash_summary(bank, monthly_spending):
    amount = signed_money(bank)
    if bank < 0:
        answer = f"Bank cash is below zero: {amount}. It does not cover spending."
    elif bank == 0:
        answer = "There is no bank cash to cover spending ($0)."
    elif monthly_spending > 0:
        months = bank / monthly_spending
        lead = "We can pay our bills" if months >= 1.5 else "Cash is tight"
        cover = "less than a week of spending" if months < 0.25 else f"about {months:.1f} months of spending"
        answer = f"{lead}: {amount} in the bank covers {cover}."
    else:
        answer = f"Bank cash is {amount}."
    if monthly_spending <= 0:
        answer += " Cash coverage cannot be estimated because average spending is zero or below."
    return answer
