# Model adapter contract

Vidal's installed module exports an object with a `contract` property and a `score(features)` method.
The CLI loads that object with `--assessor package.module:object`.
The website passes the same object to `assess_repository(repo, features, assessor)`.

`contract` is a `gh_signals.assessment.ModelContract` containing a model ID, model version and an ordered tuple of `FeatureDefinition` objects.
Each definition gives the exact source-prefixed column name, description, unit, numeric type and whether missing values are allowed.
Definitions must match the fitted preprocessing and model artifact.
Identifiers, labels, metadata and previous scores are rejected as feature names.

`score` receives a mapping containing exactly the declared features.
Observed values are finite numbers, integers or Booleans according to the contract; missing nullable values are `None`.
The library does not fill missing values or fit preprocessing.
The method applies the already-fitted preprocessing and selected composite logic, and returns a finite number from 0 to 100.
It must not retrain on the assessed repository or use its study label.

Missing required features block the model call.
An entirely unobserved feature set also remains unscored, even if all definitions are nullable.
Invalid measurements and invalid scores raise validation errors.
Missing or unconfigured models return `unscored_model_missing` rather than a default score.

Only explicitly selected, trusted installed modules should be used as adapters.
The adapter is Python code; the CLI never imports a module from the repository being assessed or automatically loads a pickle from it.

The response includes normalized repository ID, status, score, model identity/version, selected feature values and missing feature names.
The CLI additionally reports elapsed runtime and API usage.
Exit codes are 0 for a scored assessment or successful data operation, 1 for an input/runtime validation failure, 2 for command syntax errors, and 3 for an unscored assessment.
