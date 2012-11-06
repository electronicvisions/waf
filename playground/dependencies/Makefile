# simple Makefile to setup build environment
FILENAME=bootstrap.mk
URL=file://$(PWD)/remote/$(FILENAME)
CURL=curl
export CURL

main: $(FILENAME)
	$(MAKE) -f $< main

$(FILENAME):
	$(CURL) -o $@ $(URL)

clean:
	$(MAKE) -f $(FILENAME) clean
	rm -rf $(FILENAME)

.PHONY: clean main $(FILENAME)
