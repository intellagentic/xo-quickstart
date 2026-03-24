mkdir -p bcrypt-layer/python

pip install bcrypt PyJWT \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version 3.11 \
  --only-binary=:all: \
  -t bcrypt-layer/python/

cd bcrypt-layer
zip -r ../bcrypt-layer.zip python/
cd ..

aws lambda publish-layer-version \
  --layer-name bcrypt-jwt-layer \
  --zip-file fileb://bcrypt-layer.zip \
  --compatible-runtimes python3.11 python3.12 \
  --region eu-west-2
