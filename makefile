VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
OPENAPI_CLIENT = $(VENV)/bin/openapi-python-client
LIB_DIR = resources/lib

$(VENV)/bin/activate:
	python3 -m venv $(VENV)

install: $(VENV)/bin/activate
	$(PIP) install openapi-python-client ruff
	mkdir -p $(LIB_DIR)
	touch $(LIB_DIR)/__init__.py
	$(PIP) install --target=$(LIB_DIR) -r requirements.txt

generate-openapi: $(VENV)/bin/activate
	$(OPENAPI_CLIENT) generate --path lrt-epika-api.yaml
	mv lrt-epika-api-client/lrt_epika_api_client $(LIB_DIR)/lrt_epika_api_client
	rm -rf lrt-epika-api-client

clean:
	rm -rf $(LIB_DIR)
	rm -rf $(VENV)

.PHONY: install generate-openapi clean
