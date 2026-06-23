# UP² First-Run Helper

From the Runtime repository on the UP², run:

```bash
bash scripts/up2_first_run.sh
```

The helper performs a reversible, read-only preparation pass:

1. Verifies Git and Python are available.
2. Confirms it is running from a Runtime checkout.
3. Checks for the local `velvet_event_protocol` and `velvet_continuity` packages.
4. Creates repo-local development state only when missing.
5. Loads `.velvet-dev/env.sh`.
6. Runs `velvet doctor`.
7. Captures `.velvet-dev/first-boot-snapshot.json`.
8. Prints the next manual Runtime start command.

It does not install packages, create Linux users, copy files into `/opt`, modify systemd, enable services, generate production identity, or grant physical authority.

A successful final message looks like:

```text
[VELVET FIRST RUN] SAFE CHECK COMPLETE
```

Then, when ready, start the read-only development Runtime manually:

```bash
bash scripts/run_dev.sh
```

Keep the generated snapshot. It is the cleanest artifact to share when diagnosing the first UP² run.
