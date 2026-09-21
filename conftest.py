# Makes the vi_ml modules importable from tests (they use flat imports).
import os, sys
_ROOT = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_ROOT, "vi_ml"))
sys.path.insert(0, os.path.join(_ROOT, "hardware"))
