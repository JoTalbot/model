# Repos on <PUBLIC_IP_REDACTED> — snapshot 2026-09-18

## words — branch main @ 3555a82 — modified(tracked)=0 untracked=0

## orchestrator — branch main @ 4e5bf75 — modified(tracked)=1 untracked=20
 M arena_agent/arena_auth.py
?? agent_jo/.bak_jo_driver_20260916_130135.py
?? agent_jo/.bak_jo_style_20260915_164113.py
?? check_api_requests.py
?? check_auth.py
?? check_cards.py
?? check_cookies_sidebar.py
?? check_folder.py
?? check_folder2.py
?? check_js_errors.py
?? debug_network.py
?? explore_api.py
?? get_proof_token.py
?? test_api.py
?? test_api_cookies.py
?? test_api_send.py
?? test_chat.py
?? test_chat_no_folder.py
?? test_navigate.py
?? test_sidebar_click.py
?? tools/

## aios — branch main @ 1c78a9ae — modified(tracked)=0 untracked=182
?? agents/__pycache__/
?? api/__pycache__/
?? automation/
?? cognition/__pycache__/
?? cognition/vision_pipeline.py
?? consensus/__pycache__/
?? consensus/multi_agent_debate.py
?? core
?? events/__pycache__/
?? evolution/__pycache__/
?? evolution/auto_evolution_engine.py
?? evolution/evolution_history.json
?? execution/__pycache__/
?? governance/github_pr_reviewer.py
?? kernel/__pycache__/
?? llm/__init__.py
?? llm/__pycache__/
?? llm/dynamic_router_autotuner.py
?? llm/llm_balancer.py
?? llm/llm_balancer.py.bak-20260917-114341
?? llm/llm_balancer.py.bak-20260917-121643
?? llm/llm_balancer.py.bak-20260917-121749
?? memory_fabric/__pycache__/
?? memory_fabric/knowledge_graph.py
?? runtime/__pycache__/
?? supervision/__pycache__/
?? tests/__pycache__/
?? tools/__pycache__/
?? tools/cluster_health.py
?? tools/cpu_throttle_guard.py
?? tools/disk_io_stats.py
?? tools/google_provider_provisioner.py
?? tools/memory_leak_detector.py
?? tools/memory_search.py
?? tools/network_latency_probe.py
?? tools/octopus_captcha_solver.py
?? tools/registry.json
?? tools/vault_status.py

## madworld — branch main @ 791cf4e — modified(tracked)=6 untracked=107
 M .github/workflows/android-ci.yml
 M .github/workflows/backend-ci.yml
 M .github/workflows/release-gate.yml
 M docs/RELEASE_EVIDENCE_MATRIX.md
 M ops/B10_OWNER_GATE_EVIDENCE.md
 M ops/LEGAL_REVIEW_REQUIRED.md
?? .github-deployed-sha
?? .github/remote-operator/REQUESTS/20260907-capacity-isolated-v1.txt
?? .github/remote-operator/REQUESTS/20260907-capacity-isolated-v3.txt
?? .github/remote-operator/REQUESTS/20260907-capacity-isolated-v4.txt
?? .github/remote-operator/REQUESTS/20260907-dr-isolated-rehearsal-direct-v4.txt
?? .github/remote-operator/REQUESTS/20260907-workflow-dispatch-release-gate.txt
?? .github/remote-operator/REQUESTS/20260907-workflow-dispatch-remote-wrapper-v2.txt
?? .github/remote-operator/REQUESTS/20260907-workflow-dispatch-remote-wrapper-v3.txt
?? .github/remote-operator/REQUESTS/20260907-workflow-dispatch-smoke.txt
?? .github/remote-operator/REQUESTS/20260908-093000-capacity-release-gate.txt
?? .github/remote-operator/REQUESTS/20260908-111500-final-release-gate-v2.txt
?? .github/remote-operator/REQUESTS/20260908-112500-5min-capacity-queue-recovery.txt
?? .github/remote-operator/REQUESTS/20260908-113000-isolated-rollback-rehearsal.txt
?? .github/remote-operator/REQUESTS/20260908-113500-final-release-gate-v3.txt
?? .github/remote-operator/REQUESTS/20260908-122800-final-release-gate.txt
?? .github/remote-operator/REQUESTS/20260908-123100-b10-server-discovery.txt
?? .github/remote-operator/REQUESTS/20260908-153700-server-runtime-followup.txt
?? .github/remote-operator/REQUESTS/20260908-final-release-gate.txt
?? .github/remote-operator/REQUESTS/cmd-20260907-150500-prod-verify-3b100fc4.json
?? .github/remote-operator/results/cmd-20260904-220309-operator-test/
?? .github/remote-operator/results/cmd-20260904-220600-home-tree/
?? .github/remote-operator/results/cmd-20260904-220900-operator-delivery-diagnostic/
?? .github/remote-operator/results/cmd-20260905-005600-server-status/
?? .github/remote-operator/results/cmd-20260905-045900-dr-isolated-rehearsal/
?? .github/remote-operator/results/cmd-20260905-135000-server-health/
?? .github/remote-operator/results/cmd-20260905-135500-disk-space/
?? .github/remote-operator/results/cmd-20260905-140000-server-status-tree/
?? .github/remote-operator/results/cmd-20260905-140500-server-runtime-final/
?? .github/remote-operator/results/cmd-20260905-141500-production-proxy-check/
?? .github/remote-operator/results/cmd-20260905-143000-nginx-cert-permission-diagnose/
?? .github/remote-operator/results/cmd-20260905-160000-dr-rehearsal-preflight/
?? .github/remote-operator/results/cmd-20260905-160101-production-audit/
?? .github/remote-operator/results/cmd-20260905-160201-release-gates/
?? .github/remote-operator/results/cmd-20260905-160301-dr-prepare/
?? .github/remote-operator/results/cmd-20260905-160500-capacity-baseline-readonly-probe/
?? .github/remote-operator/state/cmd-20260904-220309-operator-test.json
?? .github/remote-operator/state/cmd-20260904-220600-home-tree.json
?? .github/remote-operator/state/cmd-20260904-220900-operator-delivery-diagnostic.json
?? .github/remote-operator/state/cmd-20260905-005600-server-status.json
?? .github/remote-operator/state/cmd-20260905-045900-dr-isolated-rehearsal.json
?? .github/remote-operator/state/cmd-20260905-135000-server-health.json
?? .github/remote-operator/state/cmd-20260905-135500-disk-space.json
?? .github/remote-operator/state/cmd-20260905-140000-server-status-tree.json
?? .github/remote-operator/state/cmd-20260905-140500-server-runtime-final.json
?? .github/remote-operator/state/cmd-20260905-141500-production-proxy-check.json
?? .github/remote-operator/state/cmd-20260905-143000-nginx-cert-permission-diagnose.json
?? .github/remote-operator/state/cmd-20260905-160000-dr-rehearsal-preflight.json
?? .github/remote-operator/state/cmd-20260905-160101-production-audit.json
?? .github/remote-operator/state/cmd-20260905-160201-release-gates.json
?? .github/remote-operator/state/cmd-20260905-160301-dr-prepare.json
?? .github/remote-operator/state/cmd-20260905-160500-capacity-baseline-readonly-probe.json
?? .github/remote-operator/state/last-parse-errors.log
?? .github/workflows/remote-operator-postdeploy-verify.yml
?? .github/workflows/root-runtime-verify.yml

## octopus-browser — branch main @ 44620db — modified(tracked)=0 untracked=4
?? browser-image/
?? cookie-keeper/

## logistics — branch main @ ead46bb — modified(tracked)=0 untracked=0
