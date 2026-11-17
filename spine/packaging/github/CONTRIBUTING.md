# Contributing

## Before changing a converter

1. Reproduce the issue with one role or prefab.
2. Keep a runnable baseline product.
3. Compare structural output and rendered frames before/after.
4. Record the exact affected route and algorithm, not just the visual symptom.

## Validation

At minimum:

```powershell
python -m compileall -q .\SingleSpine\Shared\Unity2Spine\src `
  .\SingleSpine\Shared\lo_uncen2Spine\src `
  .\MultiSpine\LO\MutiBone\src .\MultiSpine\LO\MutiBone\tools `
  .\MultiSpine\BD\Tools .\StaticSpine\LO\Tools
```

When generated data is available, run the route-specific validator listed in
the route README.

## Repository size

Do not commit full converted products, Unity projects, viewer environments,
truth captures or reverse-engineering databases. Add small representative
examples only.
