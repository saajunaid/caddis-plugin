# Python / Streamlit Word Cloud — Implementation Reference

Two approaches:
1. **Server-side PNG** — Python `wordcloud` lib, matplotlib, Pillow
2. **Embedded HTML** — render the HTML template (references/html.md) inside `st.components.v1.html()`

Use approach 2 for full interactivity, animations, and theming. Use approach 1 for static image export or simpler use cases.

---

## Approach 1: Server-side PNG (wordcloud lib)

### Install
```bash
pip install wordcloud matplotlib pillow nltk numpy
```

### Full Example
```python
import streamlit as st
from wordcloud import WordCloud, STOPWORDS
import matplotlib.pyplot as plt
from PIL import Image
import numpy as np
import re
from collections import Counter

# ── Optional: Sentiment coloring ──
try:
    from nltk.sentiment import SentimentIntensityAnalyzer
    import nltk
    nltk.download('vader_lexicon', quiet=True)
    sia = SentimentIntensityAnalyzer()
    HAS_SENTIMENT = True
except Exception:
    HAS_SENTIMENT = False

POSITIVE_COLOR = '#4ade80'
NEGATIVE_COLOR = '#f87171'
VERB_COLOR     = '#c4b5fd'
NOUN_COLOR     = '#7dd3fc'
NEUTRAL_COLOR  = '#94a3b8'

def compute_word_frequencies(text: str, max_words: int = 120) -> dict[str, int]:
    stops = STOPWORDS | {'the','a','an','and','or','but','in','on','at','to','for','of'}
    words = re.findall(r"[a-zA-Z']{3,}", text.lower())
    counts = Counter(w for w in words if w not in stops)
    return dict(counts.most_common(max_words))

def sentiment_color_func(word, font_size, position, orientation, random_state=None, **kwargs):
    """Color words by sentiment."""
    if not HAS_SENTIMENT:
        return NOUN_COLOR
    score = sia.polarity_scores(word)['compound']
    if score >= 0.3:  return POSITIVE_COLOR
    if score <= -0.3: return NEGATIVE_COLOR
    return NEUTRAL_COLOR

def create_wordcloud_image(
    text: str,
    width: int = 900,
    height: int = 520,
    max_words: int = 120,
    background_color: str = '#0c0a09',
    font_path: str | None = None,
    mask_path: str | None = None,
    use_sentiment_colors: bool = True,
) -> plt.Figure:
    freqs = compute_word_frequencies(text, max_words)

    mask = None
    if mask_path:
        mask = np.array(Image.open(mask_path).convert('L'))
        mask = np.where(mask > 128, 255, 0).astype(np.uint8)

    wc = WordCloud(
        width=width,
        height=height,
        max_words=max_words,
        background_color=background_color,
        colormap=None if use_sentiment_colors else 'cool',
        color_func=sentiment_color_func if use_sentiment_colors else None,
        font_path=font_path,
        mask=mask,
        mode='RGBA' if mask is not None else 'RGB',
        prefer_horizontal=0.7,
        relative_scaling=0.55,
        min_font_size=10,
        max_font_size=None,
        collocations=False,
    ).generate_from_frequencies(freqs)

    fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)
    ax.imshow(wc, interpolation='bilinear')
    ax.axis('off')
    fig.patch.set_facecolor(background_color)
    plt.tight_layout(pad=0)
    return fig

# ── Streamlit App ──
st.set_page_config(page_title='Word Cloud', layout='wide')
st.markdown("""
<style>
  .stApp { background: #0c0a09; }
  h1 { color: #7dd3fc !important; font-family: serif; }
</style>
""", unsafe_allow_html=True)

st.title('✦ Word Cloud Generator')

col1, col2 = st.columns([3, 1])
with col2:
    max_words = st.slider('Max words', 30, 200, 100)
    theme = st.radio('Theme', ['Dark', 'Light'])
    use_sentiment = st.checkbox('Sentiment colors', value=True)

with col1:
    source = st.radio('Input source', ['Text input', 'Upload file'], horizontal=True)

    text = ''
    if source == 'Text input':
        text = st.text_area('Paste your text here', height=200)
    else:
        f = st.file_uploader('Upload PDF, DOCX, XLSX, PPTX, TXT...', 
                              type=['pdf','docx','xlsx','pptx','txt','csv'])
        if f:
            text = extract_text_from_file(f)  # see extraction section below
            st.success(f'Extracted {len(text):,} characters')

    if text.strip():
        bg = '#0c0a09' if theme == 'Dark' else '#fafaf9'
        fig = create_wordcloud_image(
            text, max_words=max_words,
            background_color=bg,
            use_sentiment_colors=use_sentiment,
        )
        st.pyplot(fig, use_container_width=True)
        
        # Download button
        import io
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=150, bbox_inches='tight', facecolor=bg)
        st.download_button('Download PNG', buf.getvalue(), 'wordcloud.png', 'image/png')
```

---

## Approach 2: Interactive HTML Component in Streamlit

Embed the full interactive HTML word cloud inside Streamlit:

```python
import streamlit.components.v1 as components

def render_interactive_cloud(word_data: list[dict], theme: str = 'dark'):
    """
    word_data: [{'word': str, 'count': int, 'category': str}, ...]
    """
    js_data = str([[d['word'], d['count'], d['category']] for d in word_data])
    
    html_content = f"""
    <!DOCTYPE html>
    <html data-theme="{theme}">
    <!-- Insert full template from references/html.md here -->
    <!-- Replace WORD_DATA = [...] with: -->
    <script>
    const WORD_DATA = {js_data};
    </script>
    <!-- rest of template... -->
    </html>
    """
    
    components.html(html_content, height=600, scrolling=False)
```

---

## File Extraction Utilities

```python
def extract_text_from_file(uploaded_file) -> str:
    """Extract text from any uploaded file type."""
    import io
    name = uploaded_file.name.lower()
    data = uploaded_file.read()
    
    if name.endswith('.txt') or name.endswith('.csv'):
        return data.decode('utf-8', errors='replace')
    
    elif name.endswith('.pdf'):
        import pdfplumber
        text = []
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t: text.append(t)
        return '\n'.join(text)
    
    elif name.endswith('.docx'):
        from docx import Document
        doc = Document(io.BytesIO(data))
        return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
    
    elif name.endswith('.xlsx') or name.endswith('.xls'):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        text = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                text.extend(str(c) for c in row if c is not None)
        return ' '.join(text)
    
    elif name.endswith('.pptx'):
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        text = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if hasattr(shape, 'text'):
                    text.append(shape.text)
        return '\n'.join(text)
    
    elif name.endswith('.html') or name.endswith('.htm'):
        from html.parser import HTMLParser
        class P(HTMLParser):
            def __init__(self): super().__init__(); self.parts = []
            def handle_data(self, d): self.parts.append(d)
        p = P(); p.feed(data.decode('utf-8', errors='replace'))
        return ' '.join(p.parts)
    
    return ''
```

---

## Install Requirements (requirements.txt)

```
streamlit>=1.32
wordcloud>=1.9
matplotlib>=3.8
Pillow>=10.0
pdfplumber>=0.10
python-docx>=1.1
openpyxl>=3.1
python-pptx>=0.6
nltk>=3.8
numpy>=1.26
```
