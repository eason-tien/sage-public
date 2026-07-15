# Maintenance Task

Repair both modules without adding third-party dependencies.

## Python: invoice pricing

Implement `calculate_invoice(lines, discount_bps=0, tax_bps=0)` in
`src/pricing.py`.

Requirements:

- `lines` is an iterable of mappings containing `unit_price` and `quantity`.
- `unit_price` accepts `str`, `int`, or `Decimal`, must be finite and non-negative.
  Binary floats are rejected.
- `quantity` must be an integer greater than zero; booleans are rejected.
- Basis-point values must be integers from 0 through 10,000; booleans are rejected.
- Sum unrounded line extensions first. Apply discount, then tax.
- Round `subtotal`, `discount`, `tax`, and `total` independently to two decimal
  places using `ROUND_HALF_UP`.
- Return those four values as fixed-width decimal strings such as `"12.30"`.
- Do not mutate caller-owned input.

## JavaScript: single-flight loader

Implement `createSingleFlight(loader)` in `src/singleflight.js`.

Requirements:

- `loader` must be a function; otherwise throw `TypeError` synchronously.
- The returned function accepts any JavaScript value as a key.
- Concurrent calls with the same key must share one in-flight loader call and the
  exact same Promise object.
- Different keys run independently.
- Successful results are not cached after settlement.
- Rejections are shared by concurrent callers and removed after settlement so a later
  call retries.
- Synchronous exceptions from `loader` become Promise rejections and do not poison
  later calls.

Do not modify `TASK.md`, `AGENTS.md`, or anything under `tests/`. Run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
node --test tests/*.test.js
```

