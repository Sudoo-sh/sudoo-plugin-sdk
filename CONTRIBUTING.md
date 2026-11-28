# Contributing

Thank you for helping with the Sudoo.sh plugin SDK. Set up and run the checks as described in
[Working on the SDK](README.md#working-on-the-sdk), and run `uvx pre-commit install` once.

## Documentation rule

Every file must be clear to someone reading it for the first time.

- Every module, class and public function has a docstring (Google style): what it does, its arguments, what it
  returns, the errors it raises and any side effects (files written, network calls). Complex private helpers too.
- Comments explain why, not what. If the code needs a comment to say what it does, make the code clearer first.
- Use plain English and short sentences.
- Pydantic models whose docstring would end up in the JSON Schema served by the hub (`Author`, `Manifest`) are
  documented with a comment above the class instead; keep that comment up to date.
- Docstring coverage is checked with interrogate on every commit (`--fail-under 90`), and ruff checks the
  docstring style (`D` rules). A change that adds code without documentation does not pass.
