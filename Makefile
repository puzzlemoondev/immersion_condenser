executable_path := ./condense.py
install_path := ~/.local/bin/condense

install:
	cp $(executable_path) $(install_path) && chmod +x $(install_path)