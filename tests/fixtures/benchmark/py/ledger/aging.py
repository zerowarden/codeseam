def count_overdue(invoices, today):
    count = 0
    for invoice in invoices:
        if invoice.due_date < today and not invoice.paid:
            count += 1
    return count
