.PHONY: help build up down restart logs ps clean dev seed test lite full

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ── Quick Deploy ──
deploy: ## One-click deploy (interactive mode selection)
	@bash deploy.sh

# ── Lite Mode (SQLite, 2 containers) ──
lite: ## Start lite mode (SQLite)
	docker compose -f docker-compose.lite.yml up -d --build

lite-down: ## Stop lite mode
	docker compose -f docker-compose.lite.yml down

lite-logs: ## Tail lite mode logs
	docker compose -f docker-compose.lite.yml logs -f --tail=100

# ── Full Mode (PostgreSQL, 3 containers) ──
full: ## Start full mode (PostgreSQL)
	@test -f .env || (echo "Error: .env not found. Run 'make deploy' or copy .env.example" && exit 1)
	docker compose up -d --build

full-down: ## Stop full mode
	docker compose down

full-logs: ## Tail full mode logs
	docker compose logs -f --tail=100

# ── Common ──
build: ## Build all images (lite mode)
	docker compose -f docker-compose.lite.yml build

up: ## Alias for lite mode
	$(MAKE) lite

down: ## Stop lite mode
	$(MAKE) lite-down

restart: ## Restart all services (lite mode)
	docker compose -f docker-compose.lite.yml restart

logs: ## Tail logs (lite mode)
	$(MAKE) lite-logs

ps: ## Show running containers
	@docker compose -f docker-compose.lite.yml ps 2>/dev/null || docker compose ps 2>/dev/null

clean: ## Stop and remove ALL containers + volumes (⚠️ data loss!)
	@echo "⚠️  This will delete all data volumes!"
	@read -p "Are you sure? [y/N] " confirm && [[ $$confirm =~ ^[Yy] ]] || exit 1
	docker compose -f docker-compose.lite.yml down -v 2>/dev/null || true
	docker compose down -v 2>/dev/null || true

# ── Development (no Docker) ──
dev: ## Start local dev mode (SQLite, no Docker)
	bash start_dev.sh

seed: ## Seed database with sample data
	cd backend && USE_SQLITE=true python seed.py

test: ## Run API tests
	cd backend && USE_SQLITE=true python -m pytest test_api.py test_crud.py -v

# ── SSL Certificates ──
certs: ## Generate self-signed SSL certificates
	@bash generate-certs.sh
