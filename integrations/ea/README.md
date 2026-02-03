# EA (Enterprise Architect) — PUML → XMI

Minimal, clean conversion pipeline from PlantUML to XMI for EA import.

## Supported PUML subset
- `actor "Name" as A`
- `usecase "Name" as UC1`
- `A --> UC1` (association)
- `UC2 .> UC1 : <<include>>`
- `UC3 .> UC2 : <<extend>>`

Other directives like `skinparam` and `left to right direction` are ignored.

## Output
- XMI 1.1 (EA-friendly)
- Includes a **Use Case Diagram** with basic **layout** (no manual placement needed)

## CLI
```bash
python -m integrations.ea.cli input.puml -o output.xmi --model-name "My Model"
```

## Notes
- EA will import the model and the diagram; layout is simple but usable.
- You can refine layout in EA after import.
