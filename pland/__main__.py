import argparse

from . import __version__

parser = argparse.ArgumentParser(prog="pland", description="PlanD bootstrap")
parser.add_argument("--version", action="version", version=__version__)
parser.parse_args()
