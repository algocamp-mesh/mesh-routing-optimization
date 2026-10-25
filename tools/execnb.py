import nbformat, sys, time
from nbclient import NotebookClient
sys.stdout.reconfigure(encoding="utf-8")
import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
p = os.path.join(ROOT, sys.argv[1] if len(sys.argv) > 1 else "mesh_routing_aodv.ipynb")
nb = nbformat.read(p, as_version=4)
t0 = time.time()
NotebookClient(nb, timeout=1800, kernel_name="python3", resources={"metadata": {"path": ROOT}}).execute()
nbformat.write(nb, p)
errs = [o for c in nb.cells if c.cell_type == "code" for o in c.get("outputs", []) if o.get("output_type") == "error"]
print("done", round(time.time() - t0), "s, errors:", len(errs))
