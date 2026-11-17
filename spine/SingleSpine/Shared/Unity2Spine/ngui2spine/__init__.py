# -*- coding: utf-8 -*-
"""Legacy package name. The real library lives in src/unity2spine/.

`import ngui2spine.xxx` is forwarded to src/unity2spine_compat/xxx.py, which
points sys.modules at the real module, so private (underscore) names work too.
"""
import os
import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:            # 让兼容转发能 import 到新库
    sys.path.insert(0, _SRC)
__path__ = [os.path.join(_SRC, "unity2spine_compat")]
