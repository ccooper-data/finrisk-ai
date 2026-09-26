from finrisk.evidence.reproducibility import environment_manifest

def test_manifest_records_code_and_artifacts():
    m=environment_manifest("abc",{"cohort":"sha256:x"},42)
    assert m["code_sha"]=="abc" and m["artifacts"]["cohort"]=="sha256:x" and m["seed"]==42
    assert "python" in m and "packages" in m
