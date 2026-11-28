"""The oldest platforms Data Noodler runs on. One home for each number.

The docs state these floors in prose, and tests/test_doc_gates.py fails when
a doc's number differs from the value here. Standard library only, like
security_floors.py, so anything can import it.

MACOS_MAJOR: the launchers need `plutil -extract ... raw`, which arrived in
macOS 12. They are shell scripts and can't import this file, so the same
test also checks that both launchers compare against this number.

PYTHON: the lowest Python upgrade.py accepts as the base for a new venv.
"""

MACOS_MAJOR = 12
PYTHON = (3, 10)
