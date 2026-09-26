import importlib.util
import pytest
pytestmark=pytest.mark.skipif(importlib.util.find_spec("torch") is None,reason="PyTorch optional in core CI")

def test_pytorch_mlp_module_imports_when_torch_available():
    from finrisk.modeling.pytorch_mlp import _torch
    torch,nn=_torch()
    assert torch.__name__=="torch"
    assert hasattr(nn,"Linear")
