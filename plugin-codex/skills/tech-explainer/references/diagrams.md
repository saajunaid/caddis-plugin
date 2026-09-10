# Diagram vocabulary for explainers

Four Mermaid patterns cover almost every explainer. Reusing a small set is deliberate: the reader
learns the visual grammar once, in §3, and reads every later diagram faster because of it. A document
where each diagram is a different Mermaid type makes the reader re-learn the notation five times.

## Contents

- [Rule zero: does this diagram earn its place?](#rule-zero-does-this-diagram-earn-its-place)
- [Pattern 1 — the pipeline (`flowchart LR`)](#pattern-1--the-pipeline-flowchart-lr)
- [Pattern 2 — the layer stack (`flowchart TB` + subgraphs)](#pattern-2--the-layer-stack-flowchart-tb--subgraphs)
- [Pattern 3 — the ranked-effect diagram (the important one)](#pattern-3--the-ranked-effect-diagram-the-important-one)
- [Pattern 4 — the check loop](#pattern-4--the-check-loop)
- [Pattern 5 — proportion (`pie showData`)](#pattern-5--proportion-pie-showdata)
- [Pattern 6 — the next-steps chain](#pattern-6--the-next-steps-chain)
- [Syntax notes that bite](#syntax-notes-that-bite)

## Rule zero: does this diagram earn its place?

Delete the diagram if a table says it better. Diagrams carry **shape and relationship**; tables carry
**detail and comparison**. A diagram listing five options with three attributes each is a table drawn
badly.

Four to six diagrams across a long document is right. Every one should answer a different question.

## Pattern 1 — the pipeline (`flowchart LR`)

For §3, "what we are building". Left to right, one path, database shapes for stores. Put the size of
the data on the arrows or in the nodes — the reader's first question about a pipeline is "how big".

````markdown
```mermaid
flowchart LR
    DB[("Customer<br/>database")] --> P["Build the prompt<br/>about 16,400 tokens"]
    P --> S["LLM server<br/>on the H100 GPU"]
    S --> J["JSON summary<br/>about 2,400 tokens"]
    J --> O[("Stored<br/>summary")]
```
````

Keep it to five or six nodes. A pipeline diagram with fifteen boxes is an architecture diagram, and
the reader stops tracing it.

## Pattern 2 — the layer stack (`flowchart TB` + subgraphs)

For §5, "what sits on what". One subgraph per layer, numbered and named. Peers go side by side inside
their layer with `direction LR`. Mark what you do **not** have — the absence is often the reader's
actual question.

````markdown
```mermaid
flowchart TB
    subgraph programs["LAYER 1 — Programs (the wrapper you install)"]
        direction LR
        A["<b>Ollama</b><br/>installed and used"]
        B["<b>llama-server</b><br/>installed and used"]
        C["<b>LM Studio</b><br/>NOT installed"]
    end

    subgraph engine["LAYER 2 — Engine (this does the real work)"]
        D["<b>llama.cpp / ggml</b><br/>CUDA calculation code"]
    end

    subgraph driver["LAYER 3 — Driver"]
        E["NVIDIA driver, TCC mode"]
    end

    subgraph hardware["LAYER 4 — Hardware"]
        F["H100 NVL GPU<br/>94 GB memory"]
    end

    A --> D
    B --> D
    C -.->|"would use the<br/>same engine"| D
    D --> E
    E --> F
```
````

Two techniques here do real work:

- **The dotted arrow with a label** (`C -.->|"would use the same engine"| D`) shows a hypothetical
  without asserting it exists. This is how you answer "what if we used X?" inside the diagram.
- **The parenthetical in each subgraph title** ("the wrapper you install", "this does the real work")
  tells the reader what the layer *is for*, which is what they actually lack.

Follow the diagram with the one-line consequence: *"Layer 1 is easy to change. Layer 2 decides the
speed."*

## Pattern 3 — the ranked-effect diagram (the important one)

For §8, "what limits the result". This is the diagram the document exists to deliver. It is the layer
stack again, but **ordered by size of effect and labelled with the magnitude**.

````markdown
```mermaid
flowchart TB
    subgraph L1["LAYER 1 — The model — LARGEST EFFECT — about 3x"]
        M["<b>gpt-oss:120b writes 6,000 to 9,000 tokens.</b><br/>gpt-4o writes 2,373 tokens for the same job.<br/>The local model does about 3 times more work."]
    end
    subgraph L2["LAYER 2 — The engine — MEDIUM EFFECT — tens of percent"]
        E["<b>llama.cpp has no Hopper-specific code.</b><br/>It cannot use the H100 FP8 units.<br/>Faster engines (vLLM, TensorRT-LLM) do not run on Windows."]
    end
    subgraph L3["LAYER 3 — The program — SMALL EFFECT — under 5%"]
        W["<b>Ollama or llama-server or LM Studio.</b><br/>All contain the same engine.<br/>Measured difference is small."]
    end
    subgraph L4["LAYER 4 — The operating system — NO EFFECT"]
        O["<b>Windows against Linux.</b><br/>For work held fully in GPU memory,<br/>measured difference is about zero."]
    end
    L1 --> L2 --> L3 --> L4
```
````

Construction rules:

- **Title format:** `LAYER n — <the thing> — <EFFECT SIZE IN CAPS> — <the number>`. The caps and the
  number are what the reader takes away; the layer number just keeps the ordering legible.
- **Node body:** bold first line = the claim. Following lines = the evidence and the comparison. Three
  lines per node is the ceiling.
- **The arrows mean rank, not flow.** `L1 --> L2 --> L3 --> L4` reads as descending importance. Say so
  in the sentence above the diagram so nobody reads it as a data path.
- **Include the reader's preferred fix even when it ranks last.** Omitting it looks like evasion;
  ranking it with a measured number is the argument.
- **A layer you did not measure says so** — "NOT MEASURED" is an honest rank. An invented one is the
  fastest way to lose the reader who happens to know that layer.

Always follow it with the reading instruction:

> **Read the diagram this way.** If we change the program (Layer 3), we gain a few percent. If we
> change the model (Layer 1), we can gain about 3 times. Layer 1 is where the work must go.

### The same move outside the "stack" case

Nothing here depends on the causes forming a real stack. When they do not, call them causes and rank
them by measured share — the diagram does exactly the same job:

````markdown
```mermaid
flowchart TB
    subgraph L1["CAUSE 1 — The Salesforce rate limit — LARGEST EFFECT — 192 of 300 minutes, 64.0%"]
        A["<b>19,000 accounts at 100 requests per minute needs 190 minutes.</b><br/>The extract took 192 minutes.<br/>It already runs at 99% of the permitted rate."]
    end
    subgraph L2["CAUSE 2 — The dbt tests — SECOND EFFECT — 45 of 300 minutes, 15.0%"]
        B["<b>780 tests run after every load.</b><br/>Not yet split by severity."]
    end
    subgraph L3["CAUSE 3 — The load into Snowflake — SMALLEST EFFECT — 22 of 300 minutes, 7.3%"]
        C["<b>This is the step people call 'copying the data'.</b><br/>It is 7.3% of the run."]
    end
    L1 --> L2 --> L3
```
````

Note the third node: the reader's own mental model ("it's just copying data") is named and ranked
rather than dismissed. That is the move, in one box.

## Pattern 4 — the check loop

For §6, "why the work took so long" — the procedure that catches bad results. A decision diamond with
a failure branch that loops back.

````markdown
```mermaid
flowchart LR
    A["Change one thing"] --> B["Measure it"]
    B --> C{"Does the number agree<br/>with a second,<br/>independent number?"}
    C -->|"No"| D["The instrument is wrong.<br/>Repair the test."]
    D --> B
    C -->|"Yes"| E["Record the result"]
```
````

The loop-back arrow is the content. It shows that the failure path is normal and expected, which is
what makes the withdrawn-results list read as rigour instead of incompetence.

## Pattern 5 — proportion (`pie showData`)

For §7, "where the time goes". Use it when the reader is about to optimise the small slice.

````markdown
```mermaid
pie showData
    title Time in one call
    "Decode — write the answer" : 91.6
    "Prefill — read the prompt" : 8.4
```
````

- `showData` prints the values — always use it; an unlabelled pie is a decoration.
- Up to five slices. Above five, use a table — the labels stop fitting and the small slices become
  indistinguishable. If the natural breakdown is four or five stages, the pie is still the right
  visual; do not split it artificially.
- **Say what the numbers are drawn from**, in the sentence above: a sample count where you have one
  (*"We measured 223 samples of each stage"*), otherwise the single run and its date (*"From the run
  of 2026-08-06"*). A one-run pie is honest as long as it says it is one run — a pie with no stated
  basis is the single easiest thing in the document to misquote.
- Follow with the consequence: *"Earlier work tried to make prompt reading faster. That work can only
  improve 8.4% of the time."*

## Pattern 6 — the next-steps chain

For §11. Numbered steps, top to bottom, each with its method and its acceptance in the node.

````markdown
```mermaid
flowchart TB
    A["<b>Step 1 — Test other models</b><br/>Find a model that writes shorter answers.<br/>Measure tokens per call, not tokens per second."] --> B
    B["<b>Step 2 — Quality gate</b><br/>Check that the local model writes<br/>summaries that are good enough.<br/>15 test cases."] --> C
    C["<b>Step 3 — Make it a service</b><br/>Run the server with NSSM.<br/>Confirm the GPU works from a service."]
```
````

Name the step that matters most immediately below, with the reason: *"Step 1 is the most important
step. The model decides about 3 times the work. No change to the server software can equal that."*

## Syntax notes that bite

| Need                    | Write                                        | Note                                                                 |
| ----------------------- | -------------------------------------------- | -------------------------------------------------------------------- |
| Line break in a node    | `<br/>`                                      | Not `\n`. Renderers differ on `<br>` without the slash.              |
| Bold inside a node      | `["<b>Claim.</b><br/>Evidence."]`            | Markdown `**` does not render inside Mermaid nodes.                  |
| Any label with punctuation | Wrap in double quotes: `A["a, b: c"]`     | Unquoted `(`, `,`, `:`, `-` break the parser.                        |
| Database / store shape  | `DB[("Customer<br/>database")]`              |                                                                      |
| Decision                | `C{"Does it agree?"}`                        |                                                                      |
| Hypothetical / optional | `C -.->|"would use"| D`                      | Dotted = does not exist today.                                       |
| Peers side by side      | `direction LR` inside the `subgraph`         | Without it, subgraph children stack vertically.                      |
| Subgraph with a title   | `subgraph id["The title text"]`              | The bare form `subgraph The title` mangles punctuation.              |

Check every diagram renders before shipping — a broken Mermaid block shows the reader raw source and
costs more credibility than the diagram was worth. In order of preference:

1. **Paste into `mermaid.live`** — authoritative, and it points at the failing line.
2. **VS Code / GitHub / GitLab preview** — all render every pattern above.
3. **If you are offline**, read each block against the table above. Nearly every failure is one of
   four things: an unquoted label containing `(`, `,`, `:` or `-`; a `<br>` without the slash;
   markdown `**bold**` inside a node; or a `subgraph` title that is not bracketed and quoted.

Do not ship a diagram you have not checked by one of these three.
