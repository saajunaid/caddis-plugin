# Excalidraw Scripts

Scripts for working with Excalidraw diagrams and libraries. Run from the skill folder or pass paths as arguments.

## add-arrow.py

Adds a straight arrow between two points in an existing `.excalidraw` diagram. Supports optional labels and line styles.

**Usage:**
```bash
python add-arrow.py <diagram-path> <from-x> <from-y> <to-x> <to-y> [OPTIONS]
```

**Options:** `--style {solid|dashed|dotted}`, `--color HEX`, `--label TEXT`, `--use-edit-suffix` / `--no-use-edit-suffix`

**Examples:**
```bash
python add-arrow.py diagram.excalidraw 300 200 500 300
python add-arrow.py diagram.excalidraw 300 200 500 300 --label "HTTPS"
python add-arrow.py diagram.excalidraw 400 350 600 400 --style dashed --color "#7950f2"
```

## add-icon-to-diagram.py

Adds an icon from a split Excalidraw library into an existing diagram. Requires a library directory created by `split-excalidraw-library.py`.

**Usage:**
```bash
python add-icon-to-diagram.py <diagram-path> <icon-name> <x> <y> [OPTIONS]
```

**Options:** `--library-path PATH`, `--label TEXT`, `--use-edit-suffix` / `--no-use-edit-suffix`

**Examples:**
```bash
python add-icon-to-diagram.py diagram.excalidraw EC2 500 300
python add-icon-to-diagram.py diagram.excalidraw EC2 500 300 --label "Web Server"
python add-icon-to-diagram.py diagram.excalidraw VPC 200 150 --library-path path/to/libraries/gcp-icons
```

Default library path: `../libraries/aws-architecture-icons` relative to this script (create it with `split-excalidraw-library.py` first).

## split-excalidraw-library.py

Splits an Excalidraw library file (`*.excalidrawlib`) into individual icon JSON files and a `reference.md` for lookup.

**Usage:**
```bash
python split-excalidraw-library.py <path-to-library-directory>
```

**Workflow:**
1. Create a directory for the library (e.g. `libraries/aws-architecture-icons`).
2. Download a `.excalidrawlib` from [Excalidraw Libraries](https://libraries.excalidraw.com/) and place it in that directory.
3. Run the script on that directory. It creates an `icons/` subfolder and `reference.md`.

**Example:**
```bash
python split-excalidraw-library.py path/to/libraries/aws-architecture-icons/
```
