# Word Cloud — Agent Interface Reference

How to invoke the word-cloud skill from orchestrator agents or multi-step pipelines.

---

## Task Description (for orchestrators)

When spawning a word-cloud subagent, provide a task like:

```
Generate a word cloud component using the word-cloud skill.

Input:
- file_path: /path/to/document.pdf   (or provide `text` directly)
- text: "..." (plain text, if no file)
- options: {
    stack: "react",
    max_words: 100,
    animation: "entrance",
    highlight: ["sentiment"],
    theme: "auto",
    palette: "obsidian",
    shape: "circle",
    width: 900,
    height: 520
  }

Output: JSON conforming to the word-cloud output schema (see SKILL.md §7)
```

---

## Input Schema (strict)

```typescript
interface WordCloudInput {
  // ONE of these required:
  text?: string;         // raw plain text
  file_path?: string;    // path to file (PDF, DOCX, XLSX, PPTX, HTML, TXT, CSV)

  options?: {
    max_words?: number;                    // default: 100
    shape?: 'circle' | 'star' | 'speech_bubble' | 'heart' | 'diamond' | 'none';
    custom_shape_svg?: string;             // SVG <path d="..."> string
    animation?: 'none' | 'entrance' | 'float' | 'cinematic';  // default: entrance
    highlight?: Array<'sentiment' | 'verbs' | 'nouns' | 'custom'>;
    custom_highlight_words?: string[];     // words to highlight in accent color
    theme?: 'auto' | 'light' | 'dark';    // default: auto
    palette?: 'obsidian' | 'ivory' | 'aurora' | 'parchment' | 
              'midnight_ocean' | 'neon_noir' | 'botanical' | 'rose_gold';
    stack?: 'react' | 'html' | 'python' | 'streamlit';  // default: html
    width?: number;                        // default: 900
    height?: number;                       // default: 520
    font_family?: string;                  // default: 'Syne, sans-serif'
    min_word_length?: number;              // default: 3
    custom_stopwords?: string[];           // additional words to exclude
  };
}
```

---

## Output Schema (strict)

```typescript
interface WordCloudOutput {
  component_code: string;   // complete, runnable component code (React JSX / HTML / Python)
  word_frequencies: Array<{
    word: string;
    count: number;
    category: 'positive' | 'negative' | 'verb' | 'noun' | 'neutral';
  }>;
  stack: 'react' | 'html' | 'python';
  theme_vars: Record<string, string>;    // CSS custom properties used
  preview_notes: string;                 // brief human-readable notes about the output
  word_count: number;                    // total unique words in cloud
  top_words: string[];                   // top 10 words by frequency
}
```

---

## Example Agent Call (Python orchestrator)

```python
import anthropic
import json

client = anthropic.Anthropic()

def generate_word_cloud(text: str, options: dict = {}) -> dict:
    task_input = json.dumps({"text": text, "options": options})
    
    response = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=8192,
        system="""You are a word cloud generation agent. 
        You have access to the word-cloud skill at /mnt/skills/word-cloud/SKILL.md.
        Always read the skill before proceeding.
        Return ONLY valid JSON matching the output schema.""",
        messages=[{
            "role": "user",
            "content": f"Generate a word cloud from this input:\n{task_input}"
        }]
    )
    
    raw = response.content[0].text
    # Strip markdown fences if present
    clean = raw.strip().lstrip('```json').lstrip('```').rstrip('```').strip()
    return json.loads(clean)

# Usage:
result = generate_word_cloud(
    text="Your long document text here...",
    options={
        "stack": "react",
        "palette": "aurora",
        "animation": "cinematic",
        "highlight": ["sentiment", "verbs"],
        "max_words": 120,
    }
)

print(result['component_code'])  # paste into your React app
print(result['top_words'])
```

---

## Pipeline Example: PDF → Word Cloud → React Page

```python
# Step 1: Extract text from PDF
def extract_pdf(path: str) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return '\n'.join(p.extract_text() or '' for p in pdf.pages)

# Step 2: Generate word cloud
text = extract_pdf('report.pdf')
result = generate_word_cloud(text, {
    "stack": "react",
    "palette": "midnight_ocean",
    "shape": "circle",
    "animation": "entrance",
    "highlight": ["sentiment"],
})

# Step 3: Write to file
with open('WordCloud.tsx', 'w') as f:
    f.write(result['component_code'])

print(f"Generated cloud with {result['word_count']} words")
print(f"Top words: {', '.join(result['top_words'])}")
```

---

## Defaults for Agentic Mode

In agentic mode, never ask clarifying questions. Use these defaults:

| Option | Default |
|--------|---------|
| stack | `html` (most portable) |
| max_words | `100` |
| shape | `circle` |
| animation | `entrance` |
| highlight | `['sentiment']` |
| theme | `auto` |
| palette | `obsidian` |
| font_family | `'Syne, sans-serif'` |
| width | `900` |
| height | `520` |
