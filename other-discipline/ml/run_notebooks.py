"""Выполнить три блокнота с чистыми ядрами и сохранить результаты рядом с ними."""
from pathlib import Path
import json
import os
import sys
import tempfile

import nbformat
from nbclient import NotebookClient


def main():
    root = Path(__file__).resolve().parent
    # Временное описание ядра использует именно Python текущего окружения.
    with tempfile.TemporaryDirectory(prefix="ml-kernel-") as tmp:
        kernel = Path(tmp) / "kernels" / "ml-lab"
        kernel.mkdir(parents=True)
        (kernel / "kernel.json").write_text(json.dumps({
            "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "ML practical", "language": "python",
            "env": {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                    "MKL_NUM_THREADS": "1", "MPLBACKEND": "module://matplotlib_inline.backend_inline"},
        }))
        os.environ["JUPYTER_PATH"] = os.pathsep.join(filter(None, [tmp, os.environ.get("JUPYTER_PATH")]))
        names = ["k_neighbor_classification.ipynb", "decision_tree.ipynb", "regression_task_1.ipynb"]
        selected = sys.argv[1:] or names
        if any(name not in names for name in selected):
            raise SystemExit("Укажите имена одного или нескольких из трёх блокнотов")
        for name in selected:
            print(f"Выполняется {name}", flush=True)
            path = root / name
            notebook = nbformat.read(path, as_version=4)
            NotebookClient(notebook, kernel_name="ml-lab", timeout=1800, allow_errors=False,
                           resources={"metadata": {"path": str(root)}}).execute()
            nbformat.validate(notebook)
            assert not any(o.output_type == "error" for c in notebook.cells
                           if c.cell_type == "code" for o in c.outputs)
            temporary = path.with_suffix(".ipynb.tmp")
            nbformat.write(notebook, temporary)
            os.replace(temporary, path)
            print(f"Готово: {name}", flush=True)


if __name__ == "__main__":
    main()
