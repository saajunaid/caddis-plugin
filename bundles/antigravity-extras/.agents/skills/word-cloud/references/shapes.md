# Word Cloud — Shape Masking Reference

All shapes are defined as SVG paths normalized to a 200×200 viewBox.
Scale them to your canvas size using `transform="scale(W/200, H/200)"`.

---

## Circle (default)
```svg
<circle cx="100" cy="100" r="95" />
```

## Speech Bubble
```svg
<path d="M10,10 Q10,5 15,5 L185,5 Q190,5 190,10 L190,130 Q190,135 185,135 L120,135 L100,165 L80,135 L15,135 Q10,135 10,130 Z" />
```

## Star (5-point burst)
```svg
<polygon points="100,5 120,68 185,68 133,107 153,170 100,130 47,170 67,107 15,68 80,68" />
```

## Diamond
```svg
<polygon points="100,5 195,100 100,195 5,100" />
```

## Cloud Silhouette
```svg
<path d="M30,140 Q5,140 5,115 Q5,95 20,90 Q15,75 30,65 Q40,50 60,55 Q65,35 85,30 Q105,20 125,35 Q140,20 160,30 Q180,35 185,55 Q200,55 200,75 Q200,95 185,100 Q195,110 195,125 Q195,145 175,148 Q165,160 150,155 Q140,165 125,160 Q115,170 100,165 Q85,170 75,160 Q60,165 50,155 Q35,160 30,148 Z" />
```

## Heart
```svg
<path d="M100,175 L15,90 Q-10,60 20,35 Q50,10 80,40 L100,60 L120,40 Q150,10 180,35 Q210,60 185,90 Z" />
```

## Arrow (pointing right)
```svg
<polygon points="5,70 110,70 110,40 195,100 110,160 110,130 5,130" />
```

## Hexagon
```svg
<polygon points="100,5 185,50 185,150 100,195 15,150 15,50" />
```

---

## Applying Shapes in React (SVG clipPath)

```tsx
const SHAPES: Record<string, string> = {
  circle: 'M100,5 A95,95 0 1,1 99.9,5Z',
  speech_bubble: 'M10,10 Q10,5 15,5 L185,5 Q190,5 190,10 L190,130 Q190,135 185,135 L120,135 L100,165 L80,135 L15,135 Q10,135 10,130 Z',
  star: 'M100,5 L120,68 L185,68 L133,107 L153,170 L100,130 L47,170 L67,107 L15,68 L80,68 Z',
  diamond: 'M100,5 L195,100 L100,195 L5,100 Z',
  cloud: 'M30,140 Q5,140 5,115 Q5,95 20,90 ...',
  heart: 'M100,175 L15,90 Q-10,60 20,35 Q50,10 80,40 L100,60 L120,40 Q150,10 180,35 Q210,60 185,90 Z',
};

// In your SVG:
<defs>
  <clipPath id="wc-shape">
    <path
      d={SHAPES[shape]}
      transform={`scale(${dims.width / 200}, ${dims.height / 200})`}
    />
  </clipPath>
</defs>
<g clipPath="url(#wc-shape)" transform={`translate(${dims.width/2},${dims.height/2})`}>
  {/* word <text> elements */}
</g>
```

---

## Applying Shapes in Python (wordcloud lib)

```python
from PIL import Image, ImageDraw
import numpy as np

def create_shape_mask(shape: str, width: int, height: int) -> np.ndarray:
    """Create a binary mask for the given shape name."""
    img = Image.new('L', (width, height), 0)  # black = blocked
    draw = ImageDraw.Draw(img)
    
    if shape == 'circle':
        draw.ellipse([10, 10, width-10, height-10], fill=255)
    elif shape == 'diamond':
        cx, cy = width//2, height//2
        draw.polygon([(cx, 10), (width-10, cy), (cx, height-10), (10, cy)], fill=255)
    elif shape == 'star':
        import math
        cx, cy = width//2, height//2
        points = []
        for i in range(10):
            r = min(cx,cy)*0.9 if i%2==0 else min(cx,cy)*0.4
            a = math.radians(i*36 - 90)
            points.append((cx + r*math.cos(a), cy + r*math.sin(a)))
        draw.polygon(points, fill=255)
    else:
        # Default: full rectangle
        draw.rectangle([0, 0, width, height], fill=255)
    
    # wordcloud expects: white = word area, black = empty
    arr = np.array(img)
    # Invert: where white (255) → 0 (word area), where black (0) → 255 (no words)
    return 255 - arr

# Usage:
mask = create_shape_mask('star', 900, 520)
wc = WordCloud(mask=mask, background_color=None, mode='RGBA').generate_from_frequencies(freqs)
```

---

## Custom SVG from User

If the user provides a custom SVG path:
1. Parse the `<path d="...">` attribute
2. In React: use directly in `<clipPath>`
3. In Python: rasterize with `cairosvg` → PIL Image → numpy mask

```python
import cairosvg
from io import BytesIO

def svg_path_to_mask(svg_path_d: str, width: int, height: int) -> np.ndarray:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="{width}" height="{height}"><path d="{svg_path_d}" fill="white"/></svg>'
    png = cairosvg.svg2png(bytestring=svg.encode())
    img = Image.open(BytesIO(png)).convert('L')
    return 255 - np.array(img)
```
