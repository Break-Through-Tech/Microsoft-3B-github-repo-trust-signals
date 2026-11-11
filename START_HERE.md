# Task 6 shared library and CLI

Install Python 3.13 or later and uv, then open a terminal in this folder.

```bash
uv sync --frozen --all-groups
uv run gh-signals consolidate --config examples/task6/config_contributors_preview.json --input-dir examples/task6/inputs --output-dir runs/demo
```

The command prints the output directory and validation summary.
It reproduces the 106-repository base with nine baseline and 14 contributor preview features.
Missing measurements stay missing; outside repositories remain in a review file.

Read [the usage guide](docs/task6.md) for temporal integration, assessment commands and website imports.
Read [the validation results](docs/task6-validation.md) for verified behavior and current limits.

The shared library and CLI are implemented and tested.
Final scores still require Vidal's selected model, fitted preprocessing and feature contract.
Organization features and final dataset/schema confirmations are pending.
