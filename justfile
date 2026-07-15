set shell := ["zsh", "-cu"]

doctor:
    python3 tools/lab.py doctor

codegraph:
    python3 tools/check_codegraph.py .

memory-check:
    python3 tools/check_version_record.py

preflight config:
    python3 workflow/sage.py preflight --config "{{config}}"

prepare name:
    python3 tools/lab.py prepare "{{name}}"

verify name:
    python3 tools/lab.py verify "{{name}}"

verify-fixture:
    python3 tools/lab.py verify-fixture

run-flow flow name:
    python3 tools/run_flow.py "{{flow}}" "{{name}}"

list-flows:
    python3 tools/run_flow.py --list

audit-runs:
    python3 tools/audit_runs.py

promote run repo branch signers="workflow/trusted_signers":
    python3 workflow/promote.py --run "{{run}}" --repo "{{repo}}" --branch "{{branch}}" --allowed-signers "{{signers}}"

resume-promotion run repo signers="workflow/trusted_signers":
    python3 workflow/promote.py --run "{{run}}" --repo "{{repo}}" --allowed-signers "{{signers}}" --resume

benchmark-real:
    python3 tools/benchmark_real_repos.py

audit-sprite:
    python3 tools/audit_sprite_game.py

verify-upgrade:
    python3 -m unittest discover -s tests -p 'test_*.py'
    python3 tools/audit_sprite_game.py
    python3 tools/lab.py verify-fixture

clean-run name:
    python3 tools/lab.py clean "{{name}}"
