"""Allow `python -m pipeline` to run the analysis pipeline."""
import runpy

runpy.run_module("pipeline.main", run_name="__main__", alter_sys=True)
