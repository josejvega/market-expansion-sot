import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import run


class ExecuteNotebooksTests(unittest.TestCase):
    def test_executes_notebooks_in_order_from_project_root(self):
        notebook_client_class = MagicMock()
        client = notebook_client_class.return_value
        nbformat = types.ModuleType("nbformat")
        nbformat.read = MagicMock(side_effect=["ingestion", "processing"])
        nbclient = types.ModuleType("nbclient")
        nbclient.NotebookClient = notebook_client_class
        ipykernel = types.ModuleType("ipykernel")
        ipykernel.__path__ = []
        kernelspec = types.ModuleType("ipykernel.kernelspec")
        kernelspec.install = MagicMock()

        with patch.dict(
            sys.modules,
            {
                "nbformat": nbformat,
                "nbclient": nbclient,
                "ipykernel": ipykernel,
                "ipykernel.kernelspec": kernelspec,
            },
        ):
            run.execute_notebooks(timeout=120)

        self.assertEqual(nbformat.read.call_count, 2)
        first_path = nbformat.read.call_args_list[0].args[0]
        second_path = nbformat.read.call_args_list[1].args[0]
        self.assertEqual(first_path.name, "01_ingesta.ipynb")
        self.assertEqual(second_path.name, "02_calidad.ipynb")
        self.assertTrue(
            all(
                path.parent == run.PROJECT_ROOT / "notebooks"
                for path in (first_path, second_path)
            )
        )
        self.assertEqual(notebook_client_class.call_count, 2)
        self.assertEqual(client.execute.call_count, 2)
        self.assertEqual(
            notebook_client_class.call_args.kwargs,
            {
                "timeout": 120,
                "kernel_name": "market-expansion-runner",
                "resources": {"metadata": {"path": str(run.PROJECT_ROOT)}},
            },
        )
        self.assertEqual(kernelspec.install.call_count, 1)

    def test_fails_if_a_notebook_is_missing(self):
        ipykernel = types.ModuleType("ipykernel")
        ipykernel.__path__ = []
        kernelspec = types.ModuleType("ipykernel.kernelspec")
        kernelspec.install = MagicMock()
        nbclient = types.ModuleType("nbclient")
        nbclient.NotebookClient = MagicMock()
        with (
            patch.object(run, "NOTEBOOKS", ("missing.ipynb",)),
            patch.object(run, "PROJECT_ROOT", Path("missing-project")),
            patch.dict(
                sys.modules,
                {
                    "nbformat": types.ModuleType("nbformat"),
                    "nbclient": nbclient,
                    "ipykernel": ipykernel,
                    "ipykernel.kernelspec": kernelspec,
                },
            ),
        ):
            with self.assertRaises(FileNotFoundError):
                run.execute_notebooks()


if __name__ == "__main__":
    unittest.main()
