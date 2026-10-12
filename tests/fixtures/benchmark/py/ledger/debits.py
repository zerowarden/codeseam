def apply_debit(ledger, account_id, amount):
    entry = ledger.get(account_id)
    if entry is None:
        raise KeyError(account_id)
    new_balance = entry.balance - amount
    ledger.record(account_id, new_balance)
    return new_balance
