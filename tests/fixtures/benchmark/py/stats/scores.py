def summarize_scores(scores):
    total = 0
    highest = None
    for score in scores:
        total += score
        if highest is None or score > highest:
            highest = score
    average = total / len(scores) if scores else 0
    return {"total": total, "highest": highest, "average": average}
