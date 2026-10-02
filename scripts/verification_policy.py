"""Separate educational standards from delivery policy; never rewrite receipts."""
import copy
import hashlib
import re
import pipeline_core as v

# These rules govern factual authority, scope, teaching and educational review.
# Delivery/layout changes outside this set do not invalidate factual approval.
EDUCATIONAL_RULES = [1, 3, 4, *range(6, 21), *range(23, 32), 37, 38, 39, 40]


def educational_standard():
    text = (v.BASE / 'SPECIFICATION.md').read_text(encoding='utf-8')
    rules = {}
    for line in text.splitlines():
        match = re.match(r'^- \*\*SG-(\d{3})\b', line)
        if match:
            rules[int(match[1])] = line.strip()
    if not rules:
        return v.digest(v.BASE / 'SPECIFICATION.md')
    if not set(EDUCATIONAL_RULES) <= rules.keys():
        raise ValueError('Missing educational policy rule')
    selected = sorted(set(EDUCATIONAL_RULES) | {n for n in rules if n > 48})
    payload = '\n'.join(rules[n] for n in selected)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def standard_matches(value):
    return value == educational_standard()

def normalized_inputs(inputs):
    return copy.deepcopy(inputs)


def same_inputs(left, right):
    return normalized_inputs(left) == normalized_inputs(right)


def changed_inputs(before, after):
    before, after = normalized_inputs(before), normalized_inputs(after)
    return sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
