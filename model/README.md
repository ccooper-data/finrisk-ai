# Model artifact slot

`served-model.json` pins the model the inference image serves: the training run, its artifact,
and the file's SHA-256. `build-inference-image.yml` checks that the run is a successful
`Train boosted-tree benchmark` run on `main`, downloads that artifact, and fails unless the file's
SHA-256 matches the pin. Changing the served model therefore takes a reviewed commit to the pin.

The `.joblib` file is never committed; without it the image starts but `/health/ready` returns 503.
