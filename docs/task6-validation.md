# Task 6 validation results

Validation ran on November 10 2026 in America/New_York.

- 70 pytest cases passed.
- Ruff formatting, lint checks and ty type checks passed.
- The original baseline matches the saved notebook output: 106 repositories, 9 features, 30 separate candidates and zero validation errors.
- The contributor preview has 106 repositories and 23 features with zero validation errors; coverage gaps and outside identities remain explicit warnings.
- Temporal integration preserves all 106 rows and all existing columns, validates 93 evidence-linked records, appends 30 columns and retains 11 outside identities for review.
- No temporal values are observed in the selected 106-repository snapshot, so those cells remain missing.
- Measured wall times were about 0.05 seconds for baseline consolidation, 0.11 seconds for the contributor preview and 0.04 seconds for temporal integration. These local measurements are not performance guarantees.
- Offline commands made zero external API calls. A local HTTP server verified cache hits, request counting and retry behavior.
- An external live API check could not complete because api.github.com did not resolve from this execution environment. Successful live GitHub access is therefore not claimed.

Final score integration remains pending Vidal's selected artifact, fitted preprocessing, approved feature contract and composite logic.
Organization features and final repository/schema confirmations remain pending.
