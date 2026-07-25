---
name: ascii-art
description: Create text-based ASCII art using the right tool for the job — banners, borders, image conversion, pre-made art, and LLM-generated custom art. Decision-routing framework across pyfiglet, cowsay, TOIlet, boxes, and more.
source: NousResearch/hermes-agent
---

# ASCII Art

A decision-routing framework for text-based ASCII art. Each request type maps to a different tool — this skill picks the right one.

## Tool Decision Tree

```
What do you need?
├── Large text banner from a string
│   ├── Need 500+ font choices, no install → asciified API (remote)
│   ├── Local Python available → pyfiglet (local, 571 fonts)
│   └── Want color/ANSI effects → TOIlet (Linux/WSL only)
│
├── Speech bubble or fun ASCII character
│   └── cowsay (50+ characters)
│
├── Decorative border around text block
│   └── boxes (70+ border styles)
│
├── Convert an image to ASCII
│   ├── Supports color, braille, URLs → ascii-image-converter
│   └── Lightweight JPEG only → jp2a
│
├── Browse pre-made art by subject
│   └── ascii.co.uk (searchable collection)
│
├── QR code, weather art, GitHub Octocat
│   └── Fun APIs: qrenco.de, wttr.in, github.com/octocat
│
└── Custom / conceptual art (not covered above)
    └── LLM-generated using Unicode palette (see below)
```

## Tool Reference

### pyfiglet (local — Python)
```bash
pip install pyfiglet
python -c "import pyfiglet; print(pyfiglet.figlet_format('Hello', font='slant'))"
# List available fonts:
python -c "import pyfiglet; print('\n'.join(pyfiglet.FigletFont.getFonts()[:20]))"
```
571 built-in fonts. Good defaults: `slant`, `banner3`, `big`, `doom`, `isometric1`, `roman`.

### asciified API (remote — no install)
```bash
curl "https://asciified.thelicato.io/api/v2/ascii?text=Hello&font=slant"
```
250+ FIGlet fonts, free REST endpoint, works anywhere curl is available.

### TOIlet (local — Linux/WSL only)
```bash
# Install: sudo apt install toilet
toilet -f mono9 -F border "Hello"
toilet -f future --gay "Hello"    # rainbow ANSI
toilet --list                     # show available fonts
```
**Windows note**: Requires WSL. Not available in native PowerShell/CMD.

### cowsay (local)
```bash
# Install: brew install cowsay / sudo apt install cowsay
cowsay "Hello, World"
cowsay -f dragon "Rawr"
cowsay -l               # list 50+ characters
cowsay -e "@@" -T "U"   # custom eyes and tongue
```
Characters include: cow, dragon, tux, ghostbusters, stegosaurus, vader, and 45+ more.

### boxes (local)
```bash
# Install: brew install boxes / sudo apt install boxes
echo "Hello" | boxes -d stone
echo "Hello" | boxes -d dog -a c    # centered
boxes -l                             # list 70+ designs
```
Good designs: `stone`, `simple`, `parchment`, `dog`, `scroll`, `columns`, `peek`.

### ascii-image-converter (local)
```bash
# Install: go install github.com/TheZoraiz/ascii-image-converter@latest
ascii-image-converter image.jpg
ascii-image-converter image.jpg --color        # ANSI color
ascii-image-converter image.jpg --braille      # braille charset
ascii-image-converter "https://url/image.jpg"  # from URL
ascii-image-converter image.jpg -W 80          # 80-char width
```

### jp2a (local — JPEG only)
```bash
# Install: brew install jp2a / sudo apt install jp2a
jp2a image.jpg
jp2a --width=60 image.jpg
```

### Fun APIs (remote)
```bash
# QR code
curl "qrenco.de/https://example.com"

# Weather art
curl "wttr.in/London"
curl "wttr.in/London?format=3"      # compact

# GitHub Octocat with quote
curl "https://api.github.com/octocat"
```

## LLM-Generated Custom Art

When no tool fits (conceptual art, diagrams, logos from text), generate directly using this character palette:

**Block characters**: `█ ▓ ▒ ░`  
**Box drawing**: `─ │ ┌ ┐ └ ┘ ├ ┤ ┬ ┴ ┼ ═ ║ ╔ ╗ ╚ ╝`  
**Geometric**: `▲ ▼ ◆ ● ○ ◉ ★ ☆`  
**Braille dots**: `⠁ ⠂ ⠃ ⠄ ⠅ ⠆ ⠇ ⠈ ⠉ ⠊`  
**Lines/arrows**: `← → ↑ ↓ ↔ ↕ ⟵ ⟶ ⇒ ⟹`  
**Math/misc**: `∞ ∑ ∏ √ ∂ ∫ ≈ ≠ ≤ ≥`

Best practices for LLM-generated art:
- Use monospace mental model: each character is equal width
- Plan on paper/mentally before drawing
- Start with the outline, fill interior second
- Keep width ≤ 80 chars for readability in most terminals
- Use `pre` or code blocks when displaying in Markdown

## Platform Notes

| Tool | Windows | macOS | Linux |
|------|---------|-------|-------|
| pyfiglet | ✓ (pip) | ✓ | ✓ |
| asciified API | ✓ (curl) | ✓ | ✓ |
| TOIlet | WSL only | brew | apt |
| cowsay | WSL/chocolatey | brew | apt |
| boxes | WSL only | brew | apt |
| ascii-image-converter | ✓ (go) | ✓ | ✓ |
| jp2a | WSL/pre-built | brew | apt |
| Fun APIs | ✓ (curl/pwsh) | ✓ | ✓ |
