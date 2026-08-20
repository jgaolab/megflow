# Safe Local Execution — Task 1 Report

## Scope and baseline

- Task: Resource-aware local scheduling and fixed-concurrency overrides.
- Required baseline commit: `ef6babcbedfb74902bd268622e65632c939c3949`.
- Confirmed starting `HEAD`: `ef6babcbedfb74902bd268622e65632c939c3949`.
- Scope stayed within Task 1. No DeepReject preprocessing or ICA behavior was changed.
- No Docker cleanup command was run.

## Changes

1. Added identical public execution defaults to the source config, Docker config,
   and full user overlay:

   ```groovy
   execution {
       local_cpus = "auto"
       local_memory = "auto"
       local_max_tasks = "auto"
   }
   ```

2. Mapped the three settings independently into `executor.$local.cpus`,
   `executor.$local.memory`, and `executor.$local.queueSize` in both base
   configs. Lazy GStrings defer evaluation until all additive overlays have
   merged. `auto` resolves to the same container-visible CPU, physical-memory,
   and default-capacity values used by Nextflow 24.10.3; fixed overlay values
   remain visible at executor initialization.

3. Added a default per-task native thread environment derived from
   `task.cpus` for NumExpr, OpenMP, MKL, and OpenBLAS. `score_meg_quality` and
   `detect_artifacts` override these libraries to one native thread per outer
   worker. The existing `score_meg_quality --n_jobs ${task.cpus}` contract was
   retained.

4. Removed the fixed eight-thread `beforeScript` and ordinary-process
   `maxForks = 4/6` settings from both corpus/demo configs. Preserved the
   intentional `import_meg_dataset maxForks = 1` I/O guard.

5. Documented auto and fixed workstation modes, `local_max_tasks` to local
   `queueSize` mapping, cumulative CPU/memory/DAG/`maxForks` limits, a
   per-process cap example, and advanced native-thread overrides in the README
   and execution reference.

6. Added execution-contract tests for defaults, lazy local mappings, native
   thread caps, corpus/demo cleanup, full-overlay examples, and documentation.

## TDD evidence

### RED 1 — complete execution contract

The brief's exact command could not start because this machine has no
`python` executable:

```text
$ python scripts/validation/run_unittest_gate.py test_nextflow_execution_config
zsh:1: command not found: python
exit 127
```

The same gate was rerun with the available `python3`:

```text
$ python3 scripts/validation/run_unittest_gate.py test_nextflow_execution_config
Ran 53 tests in 41.870s
FAILED (failures=6)
```

The failures were the intended missing behavior:

- fixed eight-thread and `maxForks = 4/6` corpus/demo settings remained;
- full overlay/docs lacked global and per-process examples;
- the `execution` defaults were absent;
- the local executor mappings were absent;
- native thread caps were absent.

### GREEN 1 — static contract

```text
$ python3 scripts/validation/run_unittest_gate.py test_nextflow_execution_config
Ran 53 tests in 29.220s
OK
```

### RED 2 — additive overlay evaluation bug

Real Nextflow composition then showed the initial eager expressions had been
evaluated before the fixed additive overlay: all three resolved executor values
were still `null`. The mapping contract was tightened to require deferred
expressions and run before changing production config:

```text
$ python3 scripts/validation/run_unittest_gate.py \
    test_nextflow_execution_config.NextflowExecutionConfigTests.test_local_executor_maps_each_fixed_resource_override_independently
Ran 1 test
FAILED (failures=2)
```

### GREEN 2 — final static contract

```text
$ PYTHONPYCACHEPREFIX=/tmp/megprep-task1-pycache \
    python3 scripts/validation/run_unittest_gate.py test_nextflow_execution_config
Ran 53 tests in 16.255s
OK
```

No tests were skipped; `run_unittest_gate.py` would reject unexpected skips.

## Nextflow 24.10.3 validation

The public Nextflow 24.10.3 launcher/JAR from the user-authorized validation
host was copied into `/tmp` and run locally. No repository content was sent to
the remote host.

### Shipped config parsing

Every tracked `nextflow/*.config` parsed successfully with Nextflow 24.10.3:

1. `nextflow/deepprep.common.config`
2. `nextflow/full_workflow.config`
3. `nextflow/nextflow.config`
4. `nextflow/nextflow_anatomy_smoke.config`
5. `nextflow/nextflow_corpus.config`
6. `nextflow/nextflow_for_docker.config`
7. `nextflow/nextflow_maxwell_tsss_example.config`
8. `nextflow/nextflow_meg_masc_deepprep_anat.config`
9. `nextflow/nextflow_multi_dataset_demo.config`
10. `nextflow/nextflow_opm_cog_task_overrides_example.config`
11. `nextflow/nextflow_pseudomri_docker.config`
12. `nextflow/nextflow_pseudomri_source.config`
13. `nextflow/quickstart.config`

Final summary:

```text
parsed_count=13 composed_source_docker=2
```

`full_workflow.config` also composed successfully over both source and Docker
bases. Source and Docker bases with the fixed overlay parsed under
`NXF_SYNTAX_PARSER=v2` as well.

### Fixed and auto resolution

For the fixed overlay `local_cpus = 16`, `local_memory = "48 GB"`, and
`local_max_tasks = 3`, flat config contained:

```text
executor.$local.cpus = '16'
executor.$local.memory = '48 GB'
executor.$local.queueSize = '3'
```

On this machine, auto mode resolved to its visible resources:

```text
executor.$local.cpus = '8'
executor.$local.memory = '17179869184'
executor.$local.queueSize = '8'
```

### Fixed-concurrency smoke

A temporary DSL2 smoke workflow launched six independent two-second stub
tasks with `local_cpus = 8`, `local_memory = "8 GB"`, and
`local_max_tasks = 2`. Nextflow logged:

```text
Creating local task monitor for executor 'local' > cpus=8; memory=8 GB; capacity=2
```

The generated trace was independently swept over task start/complete times:

```text
tasks=6 peak_concurrency=2
```

Thus no more than two independent tasks ran concurrently.

### Documentation config parsing

```text
$ MEGFLOW_NEXTFLOW=/tmp/megprep-nextflow-24.10.3-wrapper \
    python3 scripts/validation/run_unittest_gate.py \
    test_documentation_config_examples.DocumentationConfigExamplesIntegrationTests.test_all_documented_groovy_blocks_parse_together
Ran 1 test in 25.371s
OK
```

### Diff hygiene

```text
$ git diff --check -- <Task 1 paths>
exit 0
```

## Files changed

- `tests/test_nextflow_execution_config.py`
- `nextflow/nextflow.config`
- `nextflow/nextflow_for_docker.config`
- `nextflow/full_workflow.config`
- `nextflow/nextflow_corpus.config`
- `nextflow/nextflow_multi_dataset_demo.config`
- `docs/source/reference/configuration_execution.rst`
- `README.md`
- `.superpowers/sdd/safe-task-1-report.md` (this report; ignored by default and
  force-added only for the required task record)

## Self-review conclusion

- All Task 1 checklist items are implemented and directly covered by tests or
  Nextflow runtime evidence.
- CPU, memory, global task count, and per-process `maxForks` remain independent
  and cumulative.
- Auto and fixed modes resolve correctly after additive config composition.
- Thread caps avoid nested oversubscription while preserving the existing
  outer-worker contract.
- Corpus/demo ordinary-process fixed concurrency was removed; the intentional
  import I/O serialization remains.
- The shipped configurations and new documentation examples parse with the
  required Nextflow version.
- Concern: the local Java 14 runtime emits Nextflow's standard illegal
  reflective-access warning during execution. It did not affect parsing,
  scheduling, task completion, or the measured concurrency result.
