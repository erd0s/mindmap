.PHONY: test package validate audit clean mindmap mindmap-dist desktop-test macos-preflight test-frontier-handoff

VERSION := $(shell sed -n 's/^version = "\([^"]*\)"/\1/p' pyproject.toml)
GOVULNCHECK_VERSION := v1.7.0
GO_TOOLCHAIN := go1.25.13

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v
	go test ./...
	cd desktop/frontend && npm test
	cd desktop/frontend && npm run build
	cd desktop && CGO_ENABLED=0 go test -tags server ./...

mindmap:
	mkdir -p build
	CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.version=$(VERSION)" -o build/mindmap ./cmd/mindmap

mindmap-dist:
	./scripts/build_tui.sh

desktop-test:
	cd desktop/frontend && npm ci && npm audit --audit-level=high && npm test && npm run build
	cd desktop && CGO_ENABLED=0 go test -tags server ./...

macos-preflight:
	./scripts/test_macos_app.sh

test-frontier-handoff: package
	PYTHONPATH=src python3 scripts/test_frontier_handoff.py

package:
	python3 scripts/build_plugins.py

validate: test package
	python3 scripts/check_packages.py
	python3 scripts/generate_notices.py --check
	python3 scripts/run_host_validators.py

audit:
	GOTOOLCHAIN=$(GO_TOOLCHAIN) go run golang.org/x/vuln/cmd/govulncheck@$(GOVULNCHECK_VERSION) ./...
	cd desktop && GOTOOLCHAIN=$(GO_TOOLCHAIN) CGO_ENABLED=0 go run golang.org/x/vuln/cmd/govulncheck@$(GOVULNCHECK_VERSION) -tags server ./...
	npm audit --prefix desktop/frontend --omit=dev --audit-level=low

.PHONY: validate-strict
validate-strict: test package
	python3 scripts/check_packages.py
	python3 scripts/generate_notices.py --check
	MINDMAP_REQUIRE_HOST_VALIDATORS=1 python3 scripts/run_host_validators.py

clean:
	python3 scripts/build_plugins.py --clean
