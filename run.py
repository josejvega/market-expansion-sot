"""Execute the project's ingestion and processing notebooks in order."""

from __future__ import annotations

import argparse
import os
from contextlib import contextmanager, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, Iterator

PROJECT_ROOT = Path(__file__).resolve().parent
NOTEBOOKS = ("01_ingesta.ipynb", "02_calidad.ipynb")
DEFAULT_TIMEOUT_SECONDS = 3600


@contextmanager
def _current_python_kernel(
    install_kernel: Callable[..., str],
) -> Iterator[str]:
    kernel_name = "market-expansion-runner"
    with TemporaryDirectory(prefix="market-expansion-kernel-") as directory:
        install_kernel(
            kernel_name=kernel_name,
            display_name="Python (market-expansion)",
            prefix=directory,
        )
        jupyter_data_dir = str(Path(directory) / "share" / "jupyter")
        previous_jupyter_path = os.environ.get("JUPYTER_PATH")
        jupyter_paths = [jupyter_data_dir]
        if previous_jupyter_path:
            jupyter_paths.append(previous_jupyter_path)
        os.environ["JUPYTER_PATH"] = os.pathsep.join(jupyter_paths)
        try:
            yield kernel_name
        finally:
            if previous_jupyter_path is None:
                os.environ.pop("JUPYTER_PATH", None)
            else:
                os.environ["JUPYTER_PATH"] = previous_jupyter_path


@contextmanager
def _local_only_environment() -> Iterator[None]:
    setting_names = ("SAVE_LOCALLY", "SAVE_S3", "S3_BUCKET")
    previous_settings = {
        name: os.environ.get(name)
        for name in setting_names
    }
    os.environ["SAVE_LOCALLY"] = "true"
    os.environ["SAVE_S3"] = "false"
    os.environ["S3_BUCKET"] = ""
    try:
        yield
    finally:
        for name, value in previous_settings.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def execute_notebooks(
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    local_only: bool = False,
) -> None:
    """Execute the ingestion and processing notebooks from the project root."""
    try:
        import nbformat
        from ipykernel.kernelspec import install
        from nbclient import NotebookClient
    except ImportError as error:
        raise RuntimeError(
            "Notebook execution dependencies are missing. "
            "Install them with 'python -m pip install -r requirements.txt'."
        ) from error

    storage_environment = (
        _local_only_environment() if local_only else nullcontext()
    )
    with storage_environment:
        with _current_python_kernel(install) as kernel_name:
            for notebook_name in NOTEBOOKS:
                notebook_path = PROJECT_ROOT / "notebooks" / notebook_name
                if not notebook_path.is_file():
                    raise FileNotFoundError(f"Notebook not found: {notebook_path}")

                print(
                    f"Executing {notebook_path.relative_to(PROJECT_ROOT)}...",
                    flush=True,
                )
                notebook = nbformat.read(notebook_path, as_version=4)
                client = NotebookClient(
                    notebook,
                    timeout=timeout,
                    kernel_name=kernel_name,
                    resources={"metadata": {"path": str(PROJECT_ROOT)}},
                )
                client.execute()
                print(f"Finished {notebook_path.name}.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the ingestion and processing notebooks in sequence."
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=(
            "Maximum time in seconds for each notebook cell "
            f"(default: {DEFAULT_TIMEOUT_SECONDS})."
        ),
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help=(
            "Force local persistence and disable S3 uploads and reads "
            "for this run."
        ),
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero.")

    execute_notebooks(timeout=args.timeout, local_only=args.local_only)


if __name__ == "__main__":
    main()