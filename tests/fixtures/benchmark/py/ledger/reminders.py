def overdue_total(bills, now):
    return sum(1 for bill in bills if bill.due_date < now and not bill.paid)
