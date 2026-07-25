# Stopwords — Word Cloud Reference

Words that should be filtered out before computing frequencies.
This list covers common English stopwords plus common document/presentation filler words.

## JavaScript Set

```js
const STOPWORDS = new Set([
  // Articles & prepositions
  'a','an','the','of','in','on','at','to','for','by','with','from','into',
  'through','during','before','after','above','below','between','out','off',
  'over','under','again','then','once','here','there','when','where','why',
  'how','all','both','each','few','more','most','other','some','such','no',
  'nor','not','only','own','same','so','than','too','very','just','because',
  'as','until','while','about','against','among','throughout','despite',
  'towards','upon','concerning','regarding',
  
  // Conjunctions & pronouns
  'and','but','or','nor','if','unless','since','although','though',
  'however','therefore','thus','hence','whereas','meanwhile',
  'i','me','my','myself','we','our','ours','ourselves','you','your',
  'yours','yourself','he','him','his','himself','she','her','hers',
  'herself','it','its','itself','they','them','their','theirs',
  'themselves','what','which','who','whom','this','that','these','those',
  
  // Common verbs (auxiliary + linking)
  'am','is','are','was','were','be','been','being',
  'have','has','had','having','do','does','did','doing',
  'will','would','could','should','shall','may','might','must','can',
  'need','dare','ought','used',
  
  // Common adverbs & filler
  'also','already','always','never','often','sometimes','usually','still',
  'even','ever','now','then','soon','later','today','yesterday','tomorrow',
  'here','there','away','back','forward','up','down','well','much','many',
  'any','every','another','either','neither','whether','quite','rather',
  'almost','enough','yet','else','instead','perhaps','maybe','certainly',
  'simply','actually','really','truly','however','therefore','although',
  'though','despite','whereas','meanwhile','since','unless','until',
  
  // Numbers (spelled out)
  'one','two','three','four','five','six','seven','eight','nine','ten',
  'first','second','third','fourth','fifth','last','next','previous',
  
  // Business/presentation filler
  'slide','page','section','chapter','figure','table','example','note',
  'please','thank','thanks','dear','regards','sincerely','best',
  'company','companies','organization','team','teams','group','groups',
  'year','years','month','months','day','days','time','times','date',
  'etc','ie','eg','vs','per','new','old','said','says','see','get','got',
  'make','made','take','took','use','used','come','came','go','went',
  'know','knew','think','thought','want','wanted','need','needed',
  'feel','felt','look','looks','looking','put','puts','set','sets',
  'keep','kept','give','gave','given','show','shows','shown',
]);
```

---

## Python Set

```python
STOPWORDS_EN = {
    # Articles & prepositions
    'a','an','the','of','in','on','at','to','for','by','with','from','into',
    'through','during','before','after','above','below','between','out','off',
    'over','under','again','then','once','here','there','when','where','why',
    'how','all','both','each','few','more','most','other','some','such','no',
    'nor','not','only','own','same','so','than','too','very','just','because',
    'as','until','while','about','against','among',
    # Pronouns
    'i','me','my','we','our','you','your','he','him','his','she','her',
    'it','its','they','them','their','who','what','which','this','that',
    'these','those','myself','yourself','himself','herself','itself',
    'ourselves','themselves',
    # Auxiliaries
    'am','is','are','was','were','be','been','being',
    'have','has','had','do','does','did','will','would','could','should',
    'shall','may','might','must','can','need','ought',
    # Common filler
    'also','always','never','often','still','even','now','well','much',
    'many','any','every','another','quite','rather','almost','enough',
    'yet','else','perhaps','maybe','simply','actually','really','truly',
    # Numbers
    'one','two','three','four','five','six','seven','eight','nine','ten',
    'first','second','third','fourth','fifth','last','next',
    # Business filler
    'slide','page','section','chapter','figure','table','example','note',
    'please','thank','thanks','company','team','year','month','day','time',
    'etc','new','old','said','see','get','make','take','use','come','go',
    'know','think','want','need','feel','look','put','set','keep','give','show',
}

# Combine with wordcloud's built-in stopwords:
from wordcloud import STOPWORDS as WC_STOPS
ALL_STOPS = STOPWORDS_EN | WC_STOPS
```

---

## Custom Domain Stopwords

For specific document types, extend with domain words:

```js
// Legal documents
const LEGAL_STOPS = new Set(['shall','herein','thereof','pursuant','whereas','hereby']);

// Financial reports
const FINANCE_STOPS = new Set(['quarter','fiscal','annual','report','million','billion','percent']);

// Technical docs
const TECH_STOPS = new Set(['click','select','navigate','following','below','above','shown']);
```
