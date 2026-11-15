# Recoverable storage implementation

The legacy anchor commit 8cd8dc2 replaced ledger and corpora packages with links into ignored tenant state. These source files were recovered byte-for-byte from the live packages and compared with the preceding tracked Git revision. Only Python source/tests belong here; tenant records, traces, keys and corpus contents do not.

Isolated execution places this directory before the release root in PYTHONPATH. WorkingDirectory is the writable application state root. Ledger writer uses OPENTRACY_STATE_ROOT rather than deriving writable state from its immutable source path. The legacy user services and their import paths are unchanged until explicit isolated activation.
