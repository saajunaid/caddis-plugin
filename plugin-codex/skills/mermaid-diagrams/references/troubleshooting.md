# Mermaid Troubleshooting Guide

Common issues and solutions when working with Mermaid diagrams.

## Diagram Won't Render

### Issue: Blank output or error message

**Symptoms:**
- GitHub shows blank space where diagram should be
- Mermaid Live shows "Syntax Error"
- VS Code preview doesn't display diagram

**Solutions:**

1. **Check diagram type declaration:**
   ```mermaid
   ❌ classdiagram          # Wrong - typo
   ❌ class-diagram         # Wrong - hyphen
   ✅ classDiagram          # Correct
   ```

2. **Verify syntax at mermaid.live:**
   - Copy your diagram code
   - Paste at https://mermaid.live
   - Check error messages in the editor

3. **Check for special characters:**
   ```mermaid
   ❌ class User {name}     # Braces break syntax
   ✅ class User {+name}    # Add visibility modifier
   
   ❌ A[Order {id}]         # Braces in label
   ✅ A["Order {id}"]       # Quote the label
   ```

4. **Ensure proper indentation (especially in YAML/Markdown):**
   ````markdown
   ❌ Wrong:
   ```mermaid
   classDiagram
   class User
   ```
   
   ✅ Correct:
   ```mermaid
   classDiagram
       class User
   ```
   ````

## Arrows Not Connecting

### Issue: Arrows don't connect to nodes

**Symptoms:**
- Arrow appears but doesn't touch nodes
- Error: "Node not found"
- Disconnected elements

**Solutions:**

1. **Match node IDs exactly (case-sensitive):**
   ```mermaid
   ❌ flowchart TD
       Start --> process    # 'process' doesn't exist
       Process[Do work]     # 'Process' defined (capital P)
   
   ✅ flowchart TD
       Start --> Process
       Process[Do work]
   ```

2. **Define nodes before connecting:**
   ```mermaid
   ❌ sequenceDiagram
       User->>API           # API not defined
   
   ✅ sequenceDiagram
       participant User
       participant API
       User->>API
   ```

3. **Use correct arrow syntax for diagram type:**
   ```mermaid
   # Flowchart
   A --> B              # Standard connection
   
   # Sequence diagram
   A->>B                # Sync message
   A-->>B               # Response
   
   # Class diagram
   A --> B              # Association
   A --|> B             # Inheritance
   A --* B              # Composition
   ```

## Layout Issues

### Issue: Diagram layout looks wrong or crowded

**Solutions:**

1. **Try different direction:**
   ```mermaid
   flowchart TD    # Top to bottom (default)
   flowchart LR    # Left to right
   flowchart RL    # Right to left
   flowchart BT    # Bottom to top
   ```

2. **Use subgraphs to group elements:**
   ```mermaid
   flowchart TD
       subgraph Frontend
           A[React App]
           B[Redux Store]
       end
       
       subgraph Backend
           C[API Server]
           D[Database]
       end
       
       A --> C
       C --> D
   ```

3. **Split complex diagrams:**
   ```mermaid
   # Instead of one massive diagram
   # Create multiple focused diagrams:
   # - diagram-overview.mmd
   # - diagram-auth-flow.mmd
   # - diagram-payment-flow.mmd
   ```

4. **Add invisible links to force layout:**
   ```mermaid
   flowchart LR
       A --> B
       B --> C
       A ~~~ D    # Invisible link to align D with A
   ```

## Syntax Errors

### Issue: Specific syntax not working

**Common mistakes:**

1. **Missing spaces around arrows:**
   ```mermaid
   ❌ A-->B             # Works but harder to read
   ✅ A --> B           # Better
   ```

2. **Wrong relationship syntax (class diagrams):**
   ```mermaid
   ❌ User -> Order     # Wrong syntax
   ✅ User --> Order    # Association
   ✅ User --|> Order   # Inheritance
   ```

3. **Incorrect cardinality (ERD):**
   ```mermaid
   ❌ USER 1--* ORDER   # Wrong
   ✅ USER ||--o{ ORDER # One to many
   ```

4. **Missing participant declaration (sequence):**
   ```mermaid
   ❌ sequenceDiagram
       User->>API       # Implicit participant (works but not best practice)
   
   ✅ sequenceDiagram
       participant User
       participant API
       User->>API
   ```

## Rendering Performance

### Issue: Diagram is slow to render or times out

**Solutions:**

1. **Reduce complexity:**
   - Limit to 15-20 nodes per diagram
   - Split into multiple diagrams
   - Remove unnecessary details

2. **Avoid deep nesting:**
   ```mermaid
   ❌ flowchart TD
       A --> B
           B --> C
               C --> D
                   D --> E
                       # Too deep!
   
   ✅ flowchart TD
       A --> B --> C
       C --> D --> E
   ```

3. **Use ELK layout for complex diagrams:**
   ```mermaid
   %%{init: {"flowchart": {"defaultRenderer": "elk"}} }%%
   flowchart TD
       # Complex diagram
   ```

## Labels and Text Issues

### Issue: Text not displaying correctly

**Solutions:**

1. **Quote labels with special characters:**
   ```mermaid
   ❌ A[User: Admin]        # Colon breaks it
   ✅ A["User: Admin"]      # Quote it
   
   ❌ B[Price: $100]        # Dollar sign breaks it
   ✅ B["Price: $100"]      # Quote it
   ```

2. **Use HTML entities for special characters:**
   ```mermaid
   A["Price: #36;100"]      # $ = #36;
   B["Name: #60;User#62;"]  # < and > = #60; #62;
   ```

3. **Use `<br>` for line breaks:**
   ```mermaid
   A["First Line<br>Second Line<br>Third Line"]
   ```

4. **Escape backticks in code labels:**
   ```mermaid
   A["`function() { return 'code'; }`"]
   ```

## Export Issues

### Issue: Exported diagram looks different from preview

**Solutions:**

1. **Use Mermaid Live for consistent exports:**
   - Go to https://mermaid.live
   - Paste your diagram
   - Export as PNG or SVG

2. **Use Mermaid CLI for batch exports:**
   ```bash
   npm install -g @mermaid-js/mermaid-cli
   mmdc -i diagram.mmd -o diagram.png
   ```

3. **Specify theme in diagram:**
   ```mermaid
   %%{init: {'theme':'base'}}%%
   flowchart TD
       A --> B
   ```

## GitHub/GitLab Rendering

### Issue: Diagram doesn't render on GitHub

**Solutions:**

1. **Ensure proper code fence:**
   ````markdown
   ❌ '''mermaid          # Wrong quote type
   
   ✅ ```mermaid          # Correct
   classDiagram
   ```
   ````

2. **Check file extension:**
   - `.md` or `.markdown` files render automatically
   - `.mmd` files need to be viewed raw

3. **Verify syntax in Mermaid Live first:**
   - GitHub's Mermaid version may lag behind
   - Test at https://mermaid.live

## Version Compatibility

### Issue: Diagram works locally but not in production

**Solutions:**

1. **Check Mermaid version:**
   - Different platforms support different versions
   - GitHub: ~v9.x-10.x
   - GitLab: ~v9.x
   - Notion: ~v8.x

2. **Use stable syntax:**
   - Avoid newest features if targeting older platforms
   - Stick to core syntax that works everywhere

3. **Test on target platform:**
   - Create test file in actual environment
   - Validate before committing

## Quick Debugging Checklist

When a diagram breaks, check:

- [ ] Diagram type spelled correctly (case-sensitive)
- [ ] All node IDs match exactly (case-sensitive)
- [ ] Arrows use correct syntax for diagram type
- [ ] Special characters are quoted or escaped
- [ ] No typos in relationship symbols (-->, --|>, etc.)
- [ ] Syntax validates at https://mermaid.live
- [ ] Code fence uses triple backticks: ```mermaid
- [ ] Indentation is consistent
- [ ] No unescaped braces {} in labels
- [ ] All participants declared (sequence diagrams)

## Still Stuck?

1. **Copy error-free example** from this skill's references
2. **Modify incrementally** to match your needs
3. **Test after each change** to isolate the problem
4. **Check official docs:** https://mermaid.js.org
5. **Search GitHub issues:** https://github.com/mermaid-js/mermaid/issues
