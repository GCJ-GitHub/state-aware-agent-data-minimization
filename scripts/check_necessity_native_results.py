"""Reuse the unchanged independent event checker, changing only artifact root.

The native adapter preserves the event/field ledger. This script deliberately
does not import either experiment scorer or the planner implementation.
"""
from pathlib import Path

original = Path(__file__).resolve().with_name('check_necessity_factorial_results.py')
source = original.read_text()
needle = "'necessity-factorial-pilot'"
assert source.count(needle) == 1
adapted = source.replace(needle, "'necessity-native-retest'")
exec(compile(adapted, str(original), 'exec'), {'__file__': str(original), '__name__': '__main__'})
