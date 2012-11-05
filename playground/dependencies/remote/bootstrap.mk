MODULES_DIR=modules
DB_FILE=repos.json
DB_URL=file://$(PWD)/remote/$(DB_FILE)

main:
	mkdir -p $(MODULES_DIR)
	$(CURL) -o $(MODULES_DIR)/$(DB_FILE) $(DB_URL)
	@cat $(MODULES_DIR)/$(DB_FILE)

clean:

.PHONY: main
