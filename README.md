# Drinkulator

Scale single-drink measurements to quantities that fill a cooler (5 gallons by default).

This project is now a lightweight Flask web app with a simple GUI.

## Modern Python setup (uv)

This project uses [`uv`](https://docs.astral.sh/uv/) for environment and
dependency management.

### 1) Install uv

Use your package manager, or:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2) Create/sync the project environment

From the repository root:

```bash
uv sync
```

This creates a local virtual environment at `.venv` and installs dependencies.

### 3) Run the web app

```bash
uv run flask --app main run --debug
```

Then open <http://127.0.0.1:5000> in your browser.

## How to use

1. Add one or more ingredients with name, amount, and unit.
2. Pick an output unit for the final recipe.
3. Set cooler size (or keep the 5-gallon default), then click **Scale recipe**.

## Local developer checks

Install local hooks once:

```bash
make install-hooks
```

Run the same local checks manually:

```bash
make lint
make test
make check
```

## Run with Docker

Build the image:

```bash
docker build -t drinkulator:latest .
```

Run the container:

```bash
docker run --rm -p 5000:5000 \
  -e FLASK_APP=main \
  -e FLASK_ENV=production \
  -e PORT=5000 \
  drinkulator:latest
```

Then open <http://127.0.0.1:5000>.

## Example Kubernetes pod config

An example Pod + ConfigMap manifest is provided at:

`k8s/pod.example.yaml`

Apply it after setting the image to one you can pull:

```bash
kubectl apply -f k8s/pod.example.yaml
kubectl port-forward service/drink-calculator 5000:5000
```

The app is available at <http://127.0.0.1:5000>, and Prometheus-format metrics are
available at <http://127.0.0.1:5000/metrics>. The example manifest includes
Prometheus scrape annotations for `/metrics` on port `5000`.
