# Makes the vi_ml modules importable from tests (they use flat imports).
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "vi_ml"))
