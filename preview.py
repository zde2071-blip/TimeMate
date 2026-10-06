"""Local preview launcher; private development setup lives in tools/."""
import runpy

if __name__ == "__main__":
    runpy.run_module("tools.preview", run_name="__main__")
