# NLP Keyword Lists — Word Cloud Reference

Use these lists for **Approach A** (no-dependency) sentiment and POS highlighting.
For browser or server NLP, see SKILL.md §4.

---

## Positive Sentiment Words
```js
const POSITIVE_WORDS = new Set([
  'achieve','achievement','advance','amazing','appreciate','awesome','beautiful',
  'benefit','best','better','bold','brilliant','celebrate','champion','clear',
  'collaborative','committed','confident','consistent','creative','delight',
  'dynamic','effective','efficient','empower','enable','energize','enhance',
  'excellent','exceptional','exciting','exemplary','expert','fantastic',
  'flourish','forward','gain','genuine','good','great','grow','growth',
  'happy','helpful','high','hope','ideal','impact','impressive','improve',
  'incredible','innovative','inspire','joy','kind','lead','leader','leading',
  'love','maximize','motivate','outstanding','overcome','passion','peak',
  'positive','powerful','productive','progress','proven','quality','remarkable',
  'resilient','rewarding','robust','safe','smart','strong','succeed','success',
  'successful','superb','support','sustainable','thrive','top','transform',
  'triumph','trust','trustworthy','unique','valuable','vibrant','visionary',
  'win','wonderful','worthy',
]);
```

## Negative Sentiment Words
```js
const NEGATIVE_WORDS = new Set([
  'abandon','abuse','adversity','afraid','aggravate','alarm','anger','angry',
  'anxiety','anxious','attack','awful','bad','blame','break','burden','chaos',
  'collapse','concern','confuse','conflict','crisis','critical','damage','danger',
  'dangerous','decline','defeat','delay','deny','destroy','difficult','disappoint',
  'disaster','doubt','drop','error','evil','fail','failure','fear','fragile',
  'frustrate','harm','hate','hazard','hostile','hurt','ignore','inadequate',
  'inefficient','instability','lack','liability','lose','loss','mistake','negative',
  'neglect','obstacle','offensive','oppose','pain','panic','penalty','pessimistic',
  'poor','problem','reject','risk','ruin','scared','serious','shortage','slow',
  'stagnant','struggle','suffer','terrible','threat','toxic','uncertain','unstable',
  'upset','urgent','vulnerable','waste','weak','wicked','worry','worsen','wrong',
]);
```

## Strong Verbs (action words worth highlighting)
```js
const STRONG_VERBS = new Set([
  'accelerate','achieve','activate','adapt','advance','amplify','analyze','apply',
  'build','capture','catalyze','challenge','change','collaborate','commit','compete',
  'complete','connect','create','define','deliver','deploy','design','develop',
  'digitize','disrupt','drive','enable','engage','evaluate','execute','expand',
  'explore','focus','generate','grow','guide','identify','implement','improve',
  'innovate','inspire','integrate','invest','launch','lead','leverage','manage',
  'measure','mobilize','optimize','plan','power','prioritize','produce','redesign',
  'refine','reinvent','scale','shape','solve','strengthen','streamline','support',
  'sustain','transform','unlock','validate',
]);
```

---

## Categorization Function (JS)

```js
function categorizeWord(word) {
  const w = word.toLowerCase();
  if (POSITIVE_WORDS.has(w)) return 'positive';
  if (NEGATIVE_WORDS.has(w)) return 'negative';
  if (STRONG_VERBS.has(w))   return 'verb';
  return 'neutral';
}

// Apply to word frequency array:
const categorized = wordFrequencies.map(({ text, value }) => ({
  text,
  value,
  category: categorizeWord(text),
}));
```

---

## Categorization Function (Python)

```python
POSITIVE = {
  'achieve','achievement','advance','amazing','appreciate','awesome','beautiful',
  'benefit','best','better','bold','brilliant','celebrate','champion','clear',
  'confident','creative','delight','dynamic','effective','efficient','empower',
  'enhance','excellent','exceptional','exciting','expert','fantastic','flourish',
  'gain','good','great','grow','growth','helpful','ideal','impact','impressive',
  'improve','incredible','innovative','inspire','lead','maximize','motivate',
  'outstanding','passion','positive','powerful','productive','progress','quality',
  'remarkable','resilient','robust','smart','strong','succeed','success',
  'sustainable','thrive','top','transform','trust','unique','valuable','vibrant',
  'win','wonderful',
}

NEGATIVE = {
  'abandon','abuse','adversity','afraid','aggravate','alarm','anger','angry',
  'anxiety','attack','awful','bad','blame','burden','chaos','collapse','concern',
  'conflict','crisis','damage','danger','decline','defeat','deny','destroy',
  'difficult','disappoint','disaster','doubt','drop','error','fail','failure',
  'fear','fragile','frustrate','harm','hate','hazard','hurt','inadequate',
  'lack','lose','loss','mistake','negative','neglect','obstacle','pain','panic',
  'poor','problem','reject','risk','ruin','struggle','suffer','terrible','threat',
  'toxic','uncertain','waste','weak','worry','wrong',
}

VERBS = {
  'accelerate','achieve','activate','adapt','advance','amplify','analyze','apply',
  'build','capture','catalyze','challenge','change','collaborate','commit',
  'compete','create','define','deliver','deploy','design','develop','drive',
  'enable','engage','evaluate','execute','expand','focus','generate','grow',
  'identify','implement','improve','innovate','integrate','launch','lead',
  'leverage','optimize','plan','prioritize','produce','redesign','refine',
  'reinvent','scale','shape','solve','strengthen','streamline','sustain',
  'transform','validate',
}

def categorize(word: str) -> str:
    w = word.lower()
    if w in POSITIVE: return 'positive'
    if w in NEGATIVE: return 'negative'
    if w in VERBS:    return 'verb'
    return 'neutral'
```
