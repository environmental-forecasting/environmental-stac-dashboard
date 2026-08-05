TAG ?= "dev"
IMAGE_NAME = "icenet-dashboard/plotly-dash-web-dashboard:$(TAG)"

.PHONY: build run run-dev remove-image docs-install docs docs-build

build:
	docker build -t $(IMAGE_NAME) .

run:
	python src/app.py

run-dev: build
	docker run -it --rm -p 8001:8001 $(IMAGE_NAME)

remove-image:
	docker rmi ${IMAGE_NAME}

docs-install:
	uv sync --group docs --no-install-project

docs:
	uv run --group docs zensical serve

docs-build:
	uv run --group docs zensical build
