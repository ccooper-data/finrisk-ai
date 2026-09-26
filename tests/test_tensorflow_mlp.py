import importlib.util
import pytest
pytestmark=pytest.mark.skipif(importlib.util.find_spec("tensorflow") is None,reason="TensorFlow optional in core CI")

def test_tensorflow_module_imports_when_available():
    from finrisk.modeling.tensorflow_mlp import _tf
    tf=_tf()
    assert tf.__name__=="tensorflow"
    assert hasattr(tf.keras.layers,"Dense")
