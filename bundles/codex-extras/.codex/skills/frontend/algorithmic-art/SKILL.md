---
name: algorithmic-art
description: Create browser-based visual art using p5.js — generative art, interactive visualizations, animations, 3D scenes (WebGL), audio-reactive visuals, and data visualizations. 7 production modes with export to HTML, PNG, GIF, MP4, SVG. Use for generative art, algorithmic art, flow fields, particle systems, creative coding, or any p5.js visual.
source: NousResearch/hermes-agent
---

# Algorithmic Art (p5.js)

Create browser-based visual art and interactive experiences using p5.js. The canvas is the medium; the algorithm is the brush.

**Creative standard**: work should be visually striking, not tutorial-like or generic. Articulate the creative vision before writing code.

## 7 Modes

| Mode | Use for |
|------|---------|
| **Generative** | Procedural composition — noise fields, recursive patterns, L-systems |
| **Data Viz** | Interactive charts and data-driven visuals |
| **Interactive** | User-driven experiences (mouse, keyboard, touch) |
| **Animation** | Timed sequences, motion graphics, frame-by-frame |
| **3D / WebGL** | Three-dimensional geometry, GLSL shaders |
| **Image Processing** | Pixel manipulation, image filters |
| **Audio-Reactive** | Sound-driven visuals using FFT analysis |

## Setup Template

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <style>
    body { margin: 0; overflow: hidden; background: #000; }
    canvas { display: block; }
  </style>
</head>
<body>
<script src="https://cdn.jsdelivr.net/npm/p5@1.11.3/lib/p5.min.js"></script>
<!-- For audio-reactive: -->
<!-- <script src="https://cdn.jsdelivr.net/npm/p5@1.11.3/lib/addons/p5.sound.min.js"></script> -->
<script>
p5.disableFriendlyErrors = true; // production: always disable FES

const SEED = 42;

function setup() {
  createCanvas(800, 800); // or createCanvas(windowWidth, windowHeight)
  randomSeed(SEED);
  noiseSeed(SEED);
  colorMode(HSB, 360, 100, 100, 100); // HSB for intuitive color
  // noLoop(); // uncomment for static pieces
}

function draw() {
  // ...
}

function windowResized() {
  resizeCanvas(windowWidth, windowHeight);
}
</script>
</body>
</html>
```

## Core Patterns

### Seeded Randomness (reproducibility — always do this)
```javascript
const SEED = 42;
randomSeed(SEED);
noiseSeed(SEED);
// Now random() and noise() produce the same output every run
```

### Flow Fields
```javascript
let cols, rows, scale = 20;
let particles = [];
let flowfield;

function setup() {
  createCanvas(800, 800);
  randomSeed(42); noiseSeed(42);
  cols = floor(width / scale);
  rows = floor(height / scale);
  flowfield = new Array(cols * rows);
  for (let i = 0; i < 1000; i++) particles.push(new Particle());
}

function draw() {
  let yoff = 0;
  for (let y = 0; y < rows; y++) {
    let xoff = 0;
    for (let x = 0; x < cols; x++) {
      let angle = noise(xoff, yoff) * TWO_PI * 4;
      flowfield[x + y * cols] = p5.Vector.fromAngle(angle);
      xoff += 0.1;
    }
    yoff += 0.1;
  }
  particles.forEach(p => { p.follow(flowfield); p.update(); p.show(); });
}

class Particle {
  constructor() {
    this.pos = createVector(random(width), random(height));
    this.vel = createVector(0, 0);
    this.acc = createVector(0, 0);
    this.maxSpeed = 4;
  }
  follow(ff) {
    let x = floor(this.pos.x / scale);
    let y = floor(this.pos.y / scale);
    this.acc.add(ff[x + y * cols]);
  }
  update() {
    this.vel.add(this.acc);
    this.vel.limit(this.maxSpeed);
    this.pos.add(this.vel);
    this.acc.mult(0);
    if (this.pos.x < 0) this.pos.x = width;
    if (this.pos.x > width) this.pos.x = 0;
    if (this.pos.y < 0) this.pos.y = height;
    if (this.pos.y > height) this.pos.y = 0;
  }
  show() {
    stroke(200, 60, 90, 8);
    strokeWeight(1.5);
    point(this.pos.x, this.pos.y);
  }
}
```

### Particle Systems
```javascript
class Particle {
  constructor(x, y) {
    this.pos = createVector(x, y);
    this.vel = p5.Vector.random2D().mult(random(1, 3));
    this.acc = createVector(0, 0);
    this.life = 255;
  }
  update() {
    this.vel.add(this.acc);
    this.pos.add(this.vel);
    this.life -= 3;
    this.acc.mult(0);
  }
  isDead() { return this.life <= 0; }
  show() {
    stroke(random(360), 80, 90, this.life);
    strokeWeight(2);
    point(this.pos.x, this.pos.y);
  }
}
```

### Recursive Trees
```javascript
function branch(len) {
  line(0, 0, 0, -len);
  translate(0, -len);
  if (len > 4) {
    push(); rotate(PI / 6); branch(len * 0.67); pop();
    push(); rotate(-PI / 6); branch(len * 0.67); pop();
  }
}
```

### Offscreen Buffers (layer composition)
```javascript
let layer1, layer2;
function setup() {
  createCanvas(800, 800);
  layer1 = createGraphics(800, 800);
  layer2 = createGraphics(800, 800);
}
function draw() {
  layer1.background(0, 0, 0, 10); // trails effect
  image(layer1, 0, 0);
  image(layer2, 0, 0);
}
```

## 3D / WebGL Mode

```javascript
function setup() {
  createCanvas(800, 800, WEBGL);
  colorMode(HSB, 360, 100, 100);
}
function draw() {
  background(0);
  orbitControl();
  rotateX(frameCount * 0.01);
  rotateY(frameCount * 0.013);
  noStroke();
  fill(200, 80, 90);
  sphere(100);
}
```

## Audio-Reactive Mode

```javascript
let fft, mic;
function setup() {
  createCanvas(800, 800);
  colorMode(HSB);
  userStartAudio(); // required — must call on user gesture
  mic = new p5.AudioIn();
  mic.start();
  fft = new p5.FFT(0.8, 256);
  fft.setInput(mic);
}
function draw() {
  background(0, 0, 0, 20);
  let spectrum = fft.analyze();
  for (let i = 0; i < spectrum.length; i++) {
    let x = map(i, 0, spectrum.length, 0, width);
    let h = map(spectrum[i], 0, 255, 0, height / 2);
    fill(map(i, 0, spectrum.length, 0, 360), 80, 90);
    rect(x, height / 2, width / spectrum.length, -h);
  }
}
```

## Color Palettes

```javascript
// Curated palette
const palette = ['#264653', '#2a9d8f', '#e9c46a', '#f4a261', '#e76f51'];
fill(random(palette));

// HSB procedural — analogous colors
colorMode(HSB, 360, 100, 100, 100);
let baseHue = 200;
fill((baseHue + random(-30, 30)) % 360, 80, 90, 80);

// Blend modes for layering
blendMode(ADD);    // additive — good for particles on black
blendMode(SCREEN);
blendMode(BLEND);  // reset to normal
```

## Export

```javascript
// PNG
save('artwork.png');

// GIF via CCapture.js
// <script src="https://cdn.jsdelivr.net/npm/ccapture.js/build/CCapture.all.min.js"></script>
let capturer;
function setup() {
  capturer = new CCapture({ format: 'gif', framerate: 30, seconds: 3 });
  capturer.start();
}
function draw() {
  capturer.capture(document.querySelector('canvas'));
  if (frameCount > 90) { capturer.stop(); capturer.save(); noLoop(); }
}
```

## Quick Reference

```javascript
// Canvas
createCanvas(w, h)            // 2D
createCanvas(w, h, WEBGL)     // 3D

// Color
colorMode(HSB, 360, 100, 100, 100)
fill(h, s, b, a) / stroke(h, s, b, a)
noFill() / noStroke()
blendMode(ADD | SCREEN | BLEND)

// Noise & Random
noise(x, y, z)                // 0–1 Perlin noise
noiseSeed(n) / randomSeed(n)  // reproducibility
map(val, in1, in2, out1, out2)
lerp(start, end, amt)

// Shapes
point(x, y) / line(x1,y1,x2,y2)
rect(x, y, w, h, [r]) / ellipse(x, y, w, h)
beginShape() / vertex(x, y) / endShape(CLOSE)

// Transforms — always use push/pop
push() / pop()
translate(x, y) / rotate(angle) / scale(s)
```
