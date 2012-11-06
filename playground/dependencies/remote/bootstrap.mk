MODULES_DIR=modules
DB_FILE=repos.json
DB_URL=file://$(PWD)/remote/$(DB_FILE)

WAF_FILE=waf
WAF_URL=file://$(PWD)/../../$(WAF_FILE)

main:
	mkdir -p $(MODULES_DIR)
	$(CURL) -o $(MODULES_DIR)/$(DB_FILE) $(DB_URL)
	$(CURL) -o $(WAF_FILE) $(WAF_URL)
	chmod +x $(WAF_FILE)
	@cat $(MODULES_DIR)/$(DB_FILE)

clean:
	rm -f $(MODULES_DIR)/$(DB_FILE)
	rm -f $(WAF_FILE)

.PHONY: main
