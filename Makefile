TAG = "dev"
IMAGE_NAME = "icenet-dashboard/plotly-dash-web-dashboard:$(TAG)"

build:
	docker build -t $(IMAGE_NAME) .

run:
	python src/app.py

run-dev: build
	docker run -it --rm -p 8001:8001 $(IMAGE_NAME)

remove-image:
	docker rmi ${IMAGE_NAME}
