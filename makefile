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
	$(OPENAPI_CLIENT) generate --path lrt-epika-api.yaml --overwrite
	rm -rf $(LIB_DIR)/lrt_epika_api_client
	mv lrt-epika-api-client/lrt_epika_api_client $(LIB_DIR)/lrt_epika_api_client
	rm -rf lrt-epika-api-client

clean:
	rm -rf $(LIB_DIR)
	rm -rf $(VENV)

zip: install generate-openapi
	$(eval ADDON_ID := $(shell awk '/<addon/,/>/' addon.xml | grep -oP '(?<=id=")[^"]*' | head -1))
	$(eval ADDON_VERSION := $(shell awk '/<addon/,/>/' addon.xml | grep -oP '(?<=version=")[^"]*' | head -1))
	$(eval ZIP_NAME := $(ADDON_ID)-$(ADDON_VERSION).zip)
	$(eval EXCLUDE_FILES := \*.pyc \*.pyo \*.zip)
	$(eval INCLUDE_FILES := addon.xml main.py LICENSE.txt Readme.md movies.json resources/)
	$(eval INCLUDE_PATHS := $(patsubst %,$(ADDON_ID)/%,$(INCLUDE_FILES)))
	@echo "Building $(ZIP_NAME)"
	@rm -f $(ZIP_NAME)
	@rm -f ../$(ZIP_NAME)
	@rm -rf ../$(ADDON_ID)
	@mkdir -p ../$(ADDON_ID)
	@cp -r $(INCLUDE_FILES) ../$(ADDON_ID)/
	cd .. && zip -r $(ZIP_NAME) $(ADDON_ID) -x $(EXCLUDE_FILES)
	@mv ../$(ZIP_NAME) ./
	@rm -rf ../$(ADDON_ID)
	@echo "Successfully created $(ZIP_NAME)"

.PHONY: install generate-openapi clean zip
