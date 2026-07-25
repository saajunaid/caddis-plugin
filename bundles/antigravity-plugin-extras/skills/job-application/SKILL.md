---
name: job-application
description: Write tailored cover letters and job applications using a structured methodology. Analyzes job descriptions, maps experience, and generates personalized applications.
---

# Job Application Assistant

Generate cover letters and job applications that sound like you, not a template.

## When to Use

- Writing a cover letter for a specific job posting
- Tailoring a resume/CV for a role
- Preparing application materials
- Analyzing job descriptions for keyword alignment

---

## Steps

### Step 1: Gather Your Materials

Before generating any application, ensure you have:

#### Your CV/Resume

```
[Your name]
[Your title/headline]

EXPERIENCE
- [Job 1: Company, Title, Dates, Key achievements]
- [Job 2: Company, Title, Dates, Key achievements]

SKILLS
- [Technical: languages, frameworks, tools]
- [Soft: leadership, communication, problem-solving]

EDUCATION
- [Degree, School, Year]

CERTIFICATIONS (if any)
- [Cert name, Issuer, Year]
```

#### Cover Letter Examples You Like

Paste 1-2 cover letters you've written that worked well. These define your voice.

#### Your Voice & Preferences

- **Tone**: Professional but not stiff, confident without bragging
- **Emphasize**: What makes you unique, key achievements, leading skills
- **Avoid**: Generic phrases ("I'm a hard worker"), repeating the job description

### Step 2: Analyze the Job Description

For each application, systematically extract:

```markdown
## Job Analysis

**Company**: [Name]
**Role**: [Title]
**Level**: [Junior/Mid/Senior/Lead]

### Key Requirements
1. [Must-have skill 1] -> Your match: [specific experience]
2. [Must-have skill 2] -> Your match: [specific experience]
3. [Nice-to-have 1] -> Your match: [if any]

### Keywords to Include
- [Technical terms from the posting]
- [Soft skills mentioned]
- [Industry-specific language]

### Company Research
- Mission/values: [from their website]
- Recent news: [if relevant]
- Culture signals: [startup/enterprise, remote/hybrid]
```

### Step 3: Generate the Cover Letter

**Structure (under 400 words):**

1. **Opening (2-3 sentences)**: Why you're interested in THIS role at THIS company. Mention something specific about the company.

2. **Experience Match (2-3 paragraphs)**: Connect your experience to their requirements. Use specific metrics:
   - "Reduced API latency by 40% serving 2M daily requests"
   - "Led a team of 5 engineers shipping features for 500K users"

3. **Closing (2-3 sentences)**: Clear call to action. Express enthusiasm.

**Adapt tone to company:**
- Startup: casual, enthusiastic, show builder mentality
- Enterprise: formal, structured, show process expertise
- Agency: creative, adaptable, show breadth

### Step 4: Tailor the Resume

For each application, consider:

```markdown
## Resume Adjustments

1. **Headline**: Align with the role title
2. **Summary**: Customize 2-3 sentences to match the role
3. **Experience bullets**: Reorder to lead with most relevant
4. **Skills section**: Move matching skills to the top
5. **Keywords**: Ensure ATS-friendly keywords from the posting appear
```

### Step 5: Review and Refine

**Quality checks:**
- [ ] Is it under 400 words (cover letter)?
- [ ] Does it mention the company name and something specific about them?
- [ ] Are achievements quantified where possible?
- [ ] Does it match the posting's tone?
- [ ] No spelling or grammar errors?
- [ ] Does it avoid generic phrases?

---

## Patterns and Examples

### Strong Opening

```
I noticed [Company] is expanding its data platform to support real-time analytics
for [specific product]. Having built similar systems at [Previous Company] that
process 50M events daily, I'm excited about the opportunity to bring that
experience to your team as a Senior Data Engineer.
```

### Weak Opening (Avoid)

```
I am writing to apply for the Senior Data Engineer position at [Company].
I believe I am a good fit for this role because of my experience.
```

### Achievement Bullets (STAR Format)

```
- Architected event-driven pipeline (Kafka + Flink) reducing data latency
  from 4 hours to 30 seconds, enabling real-time dashboards for 200 analysts
- Led migration from monolith to microservices, cutting deployment time from
  2 weeks to 45 minutes and reducing incidents by 60%
```

---

## Output Format

When generating application materials:

```markdown
## Cover Letter: [Role] at [Company]

[Full cover letter text]

---

## Resume Adjustments
- Headline: [suggested change]
- Key bullets to highlight: [list]
- Keywords to add: [list]

## Application Notes
- [Any additional insights or warnings]
```

---

## Checklist

- [ ] CV/resume is provided and up to date
- [ ] Job description thoroughly analyzed
- [ ] Requirements mapped to specific experience
- [ ] Cover letter under 400 words
- [ ] Company-specific opening (not generic)
- [ ] Achievements quantified with metrics
- [ ] Tone matches company culture
- [ ] Resume bullets reordered for relevance
- [ ] ATS keywords included
- [ ] Proofread for errors
