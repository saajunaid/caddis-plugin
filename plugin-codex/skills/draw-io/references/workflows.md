# Workflow Examples

## Example 1: Create AWS Architecture Diagram

```bash
# 1. Create diagram file
touch aws-architecture.drawio

# 2. Find required AWS icons
python scripts/find_aws_icon.py ec2
python scripts/find_aws_icon.py rds
python scripts/find_aws_icon.py lambda

# 3. Edit diagram in draw.io app or as XML
# Add: VPC boundary, subnets, services with icons

# 4. Convert to PNG
bash scripts/convert-drawio-to-png.sh aws-architecture.drawio

# 5. Verify output
open aws-architecture.drawio.png  # macOS
```

## Example 2: Fix Overlapping Elements

```bash
# 1. Identify issue
open diagram.drawio.png

# 2. Edit XML
vim diagram.drawio

# 3. Calculate and align element centers
# Box 1: y=100, height=80 → center = 140
# Box 2: Adjust to y=120, height=40 → center = 140

# 4. Move arrows to back layer (after title in XML)

# 5. Regenerate PNG
bash scripts/convert-drawio-to-png.sh diagram.drawio

# 6. Verify fix
open diagram.drawio.png
```

## Example 3: Batch Convert Multiple Diagrams

```bash
# Convert all diagrams in directory
bash scripts/convert-drawio-to-png.sh diagrams/*.drawio

# Or use find
find . -name "*.drawio" -type f -exec \
  bash scripts/convert-drawio-to-png.sh {} \;
```

## Example 4: Progressive Disclosure Architecture Set

```bash
# Create staged diagrams for complex system
touch 01-context.drawio        # External view (users, external systems)
touch 02-system.drawio         # Main components (services, databases)
touch 03-component.drawio      # Technical details (APIs, integrations)
touch 04-deployment.drawio     # Infrastructure (VPCs, regions, AZs)

# Edit each diagram appropriately for its audience

# Convert all
bash scripts/convert-drawio-to-png.sh 0*.drawio
```

## Example 5: CI/CD Integration

Add to `.github/workflows/diagrams.yml`:

```yaml
name: Generate Diagrams

on: [push]

jobs:
  convert:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Install drawio
        run: |
          wget https://github.com/jgraph/drawio-desktop/releases/download/v21.6.5/drawio-amd64-21.6.5.deb
          sudo apt install ./drawio-amd64-21.6.5.deb
      
      - name: Convert diagrams
        run: |
          find . -name "*.drawio" -exec drawio -x -f png -s 2 -t -o {}.png {} \;
      
      - name: Commit PNGs
        run: |
          git config user.name github-actions
          git config user.email github-actions@github.com
          git add "*.png"
          git commit -m "Auto-generate diagram PNGs" || echo "No changes"
          git push
```
