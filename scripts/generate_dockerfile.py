import argparse
from pathlib import Path

DEFAULT_PYTHON_IMAGE = "python:3.12-slim"

DOCKERFILE_TEMPLATE = """FROM {python_image}

RUN apt-get update && \\
    apt-get install -y --no-install-recommends coinor-libipopt-dev && \\
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
COPY src/ src/
COPY configs/ configs/
COPY recipes/ recipes/
COPY dashboard/ dashboard/

RUN pip install --no-cache-dir . && \\
    pip install --no-cache-dir idaes-pse && \\
    idaes get-extensions --verbose

EXPOSE 4840
EXPOSE 8000

CMD ["python", "-m", "reactor"]
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a Dockerfile for the Reactor Digital Twin."
    )
    parser.add_argument(
        "-o",
        "--output",
        default="Dockerfile",
        help="Output path for the Dockerfile (default: Dockerfile).",
    )
    parser.add_argument(
        "--python-image",
        default=DEFAULT_PYTHON_IMAGE,
        help=f"Base Python image (default: {DEFAULT_PYTHON_IMAGE}).",
    )
    args = parser.parse_args()

    dockerfile_path = Path(args.output)
    content = DOCKERFILE_TEMPLATE.format(python_image=args.python_image)
    dockerfile_path.write_text(content, encoding="utf-8")
    print(f"Wrote {dockerfile_path}")


if __name__ == "__main__":
    main()
