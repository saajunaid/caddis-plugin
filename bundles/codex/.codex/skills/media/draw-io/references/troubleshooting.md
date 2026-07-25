# Troubleshooting Guide

## PNG Not Generated

**Symptoms:** Script runs but no .png file created

**Solutions:**
1. Check if drawio CLI is installed:
   ```bash
   drawio --version
   ```
   
2. Install if missing:
   - macOS: `brew install drawio`
   - Linux: Download from https://github.com/jgraph/drawio-desktop/releases
   - Windows: Download from https://www.drawio.com/

3. Check file permissions:
   ```bash
   ls -l your-diagram.drawio
   chmod 644 your-diagram.drawio  # If needed
   ```

4. Verify .drawio file is valid XML:
   ```bash
   xmllint --noout your-diagram.drawio
   ```

## Elements Overlapping in PNG

**Symptoms:** Diagram looks good in draw.io app but elements overlap in PNG

**Solutions:**
1. Open .drawio in text editor
2. Check arrow placement - arrows must be after title, before other elements:
   ```xml
   <mxCell id="title" .../>     <!-- First -->
   <mxCell id="arrow1" .../>    <!-- Arrows next -->
   <mxCell id="box1" .../>      <!-- Elements last -->
   ```
3. Verify element z-order (elements later in file appear on top)
4. Adjust coordinates to create spacing
5. Re-export and verify

## Text Cut Off or Wrapped

**Symptoms:** Labels truncated or broken into multiple lines unexpectedly

**Solutions:**
1. Calculate required width:
   - English: chars × 10px + 20px padding
   - Example: "Application Server" (18 chars) = 180px + 20px = 200px

2. Update width in mxGeometry:
   ```xml
   <mxGeometry x="140" y="60" width="200" height="40" />
   ```

3. For multi-line text, increase height proportionally

## Script Permission Denied

**Symptoms:** `bash: permission denied: convert-drawio-to-png.sh`

**Solutions:**
```bash
# Make script executable
chmod +x scripts/convert-drawio-to-png.sh

# Or run with bash explicitly
bash scripts/convert-drawio-to-png.sh diagram.drawio
```

## AWS Icon Not Found

**Symptoms:** Search script returns no results

**Solutions:**
1. Check spelling:
   ```bash
   python scripts/find_aws_icon.py lambda
   ```

2. Try partial match:
   ```bash
   python scripts/find_aws_icon.py compute
   ```

3. List all available icons:
   ```bash
   python scripts/find_aws_icon.py --list-all
   ```

4. Some newer services may not be in aws4 icon set

## Transparent Background Not Working

**Symptoms:** PNG has white background despite `-t` flag

**Solutions:**
1. Remove background attribute from mxGraphModel:
   ```xml
   <!-- Remove this line -->
   <mxGraphModel background="#ffffff" ...>
   
   <!-- Keep page="0" -->
   <mxGraphModel page="0" ...>
   ```

2. Ensure `-t` flag is used in conversion:
   ```bash
   drawio -x -f png -s 2 -t -o output.png input.drawio
   ```

3. Check drawio CLI version (should be v20+):
   ```bash
   drawio --version
   ```
