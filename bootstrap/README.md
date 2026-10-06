# Portable Python environment bootstrap

`virtualenv.pyz` is the official self-contained virtualenv zipapp downloaded from
`https://bootstrap.pypa.io/virtualenv.pyz` on 6 October 2026. It reports
virtualenv 21.14.5 and supports Python 3.9 and later. Its SHA-256 is
`9096efa6e3a8457cc3ec56e749a2d1e17505b756ee3cb2b7e889526367efc187`.
`Launcher.ps1` verifies that hash before executing it. The archive contains
virtualenv's license and third-party notices in its `.dist-info/licenses` folder.

Setup runs this archive with the selected Python using `--no-download` and
`--no-periodic-update`. This creates `.venv` and seeds its pip without modifying
the base Python installation or requiring administrator rights. Project packages
are subsequently installed into `.venv` from the configured package index.
