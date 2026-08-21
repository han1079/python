VENV_NAME=venv

if [ ! -d "$VENV_NAME" ]; then
	python3 -m venv $VENV_NAME
fi

source "$VENV_NAME/bin/activate"

pip install --upgrade pip
pip install -r requirements.txt
pip install --upgrade -r requirements.txt

pip install -e Notebooks
cat > "$VENV_NAME/bin/incgrph" << EOF
#!/bin/bash
python3 "$PWD/tools/cincludegraph/incgrph.py" "\$@"
EOF
chmod +x "$VENV_NAME/bin/incgrph"

export PATH="$PWD/tools/cincludegraph:$PATH"

echo "[bootstrap.sh] Development environment ready."
