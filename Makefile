.PHONY: run-backend test mock-mac demo-flow generate-xcode

run-backend:
	cd backend && python3 run_server.py

test:
	cd backend && python3 -m pytest -q

mock-mac:
	python3 scripts/mock_mac_status_reporter.py --base-url http://127.0.0.1:8787

demo-flow:
	python3 scripts/run_morning_flow_demo.py --base-url http://127.0.0.1:8787

generate-xcode:
	./scripts/generate_xcode_project.sh

run-tunnel:
	cloudflared tunnel --url http://localhost:8787
