"""Record processing helpers for the Stage 2 sample fixture."""


def classify_record(record):
    """Classify a record with a deliberately high cyclomatic complexity (GT-3)."""
    score = 0
    if record is None:
        return "missing"
    if record.get("alpha"):
        score += 1
    if record.get("beta"):
        score += 2
    if record.get("gamma"):
        score += 3
    if record.get("delta"):
        score += 4
    if record.get("epsilon"):
        score += 5
    if record.get("zeta"):
        score += 6
    if record.get("eta"):
        score += 7
    if record.get("theta"):
        score += 8
    if record.get("iota"):
        score += 9
    if record.get("kappa"):
        score += 10
    if record.get("lambda"):
        score += 11
    if record.get("mu"):
        score += 12
    if record.get("nu"):
        score += 13
    if record.get("xi"):
        score += 14
    if record.get("omicron"):
        score += 15
    if record.get("pi"):
        score += 16
    if score > 45:
        return "extreme"
    if score > 35:
        return "high"
    if score > 25:
        return "medium"
    if score > 15:
        return "low"
    return "minimal"


def read_records(path):
    """Read newline-delimited records from *path* (GT-4: no error handling)."""
    with open(path, encoding="utf-8") as handle:
        data = handle.read()
    return [line for line in data.splitlines() if line]


def find_duplicates(records):
    """Return repeated values using an intentionally quadratic scan (GT-7)."""
    duplicates = []
    for index, left in enumerate(records):
        for right in records[index + 1:]:
            if left == right and left not in duplicates:
                duplicates.append(left)
    return duplicates
