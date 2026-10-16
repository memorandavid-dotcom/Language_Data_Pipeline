import json
import math


def _clean_nan(value):
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def load_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}, line {line_no}: invalid JSON ({error})") from error
            if not isinstance(record, dict):
                raise ValueError(f"{path}, line {line_no}: expected a JSON object")
            rows.append({key: _clean_nan(value) for key, value in record.items()})
    return rows