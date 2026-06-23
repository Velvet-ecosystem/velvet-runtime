# One-Command Development Runtime Start

After creating the repo-local development state:

```bash
python3 velvet_cli.py dev-bootstrap
```

start the Runtime with:

```bash
python3 velvet_cli.py dev-start
```

The command:

1. loads only the fixed repo-local `.velvet-dev/env.sh` file;
2. accepts only the documented Runtime path variables;
3. sets development mode and disables physical authority;
4. runs the normal startup doctor;
5. refuses to start when required checks fail;
6. enters the existing `main.py` Runtime boot path when ready.

`dev-start` does not create a second Runtime, bypass continuity, alter Court policy, add routes, open a listener, or grant actuation.

The development bootstrap remains bound to a guest session with `physical_presence: false` and observation-only capability. Stop the foreground Runtime with `Ctrl+C` or a normal termination signal.
