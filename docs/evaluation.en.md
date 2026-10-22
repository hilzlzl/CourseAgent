# Assignment generation and delivery evaluation

[简体中文](evaluation.md) · English

## Experimental setup

The evaluation compares CourseAgent, direct generation by a general-purpose AI[^ai], and manual assignment preparation. Requests cover ordinary and programming questions for a data structures course; some include teacher-provided materials.

| Item | CourseAgent | Direct AI generation | Manual preparation |
| --- | --- | --- | --- |
| Experiment size | 20 requirements, 3 runs each; 60 tasks and 876 question occurrences | 20 requirements, 3 runs each; 60 tasks and 876 question occurrences | 20 requirements, 3 runs each; 60 tasks and 876 question occurrences |
| Workflow | Source retrieval, course matching, answer and programming verification, export and platform delivery | One request per task returns a script that generates the whole assignment; the script is then executed externally | Manual search, selection, arrangement and proofreading, without AI assistance |

CourseAgent and direct AI generation each have a 3,600-second limit per task. CourseAgent's default delivery workflow saves an unpublished exam to the platform and verifies it by readback; local generation is also supported. The teacher performs final publication. Completion rates below measure generated content.

[^ai]: This baseline used Codex. Each task uses one request with no retrieval, code-execution or file-writing tools, follow-up prompts or automatic retries.

## Results

| Metric | CourseAgent (20×3) | Direct AI generation (20×3) | Manual preparation |
| --- | --- | --- | --- |
| Complete assignments | 55/60 (91.67%) | 46/60 (76.67%) | 100% |
| Question completion | 852/876 (97.26%) | 800/876 (91.32%) | 100% |
| Ordinary / programming questions completed | 470/474, 382/402 | 440/474, 360/402 | 100% |
| Ordinary / programming overlap across runs[^overlap] | 40.09% / 36.78% | 80.09% / 86.78% | Not measured |
| Time P50 / P90 | **607 / 1,320 seconds** | 700 / 1,500 seconds | About 45 minutes per assignment on average |
| Model calls | 4,019 logical calls | 60 HTTP requests | Not applicable |
| Total reported tokens | 9,884,144 | 3,047,640 | Not applicable |
| Agent score[^score] | 29.95 / 25.32 / 14.45 / 14.44 / 8.57 → 92.73 | 28 / 21.47 / 10 / 12.38 / 6.3 → 78.15 | 27.79 / 26.73 / 14 / 14 / 8.6 → 91.12 |
| Manual operation | No additional intervention | Manual upload required | Manual upload required |

See the [experiment records (Chinese)](../evaluations/README.md) for data sources and aggregation scope. Logical calls and HTTP requests use different counting units.

[^overlap]: Compare complete assignments for the same requirement in pairs. For each pair, divide the number of identical questions matched one-to-one by the smaller assignment's question count. Average pairs within each requirement, then average across requirements.

[^score]: Components are scope alignment / answer and judging correctness / statement completeness / teaching suitability / assignment coverage and complementarity, with maxima of 30 / 30 / 15 / 15 / 10. The number after the arrow is the total out of 100. The author supplied these scores; the corresponding review counts, question counts and individual labels have not yet been archived in the repository. Components and totals are rounded independently.

## Quality scoring rubric

The Agent score uses five dimensions. The fifth evaluates coverage and complementarity.

| Dimension | Maximum | What is evaluated |
| --- | ---: | --- |
| Scope alignment | 30 | Topics match the request and course materials |
| Answer and judging correctness | 30 | Ordinary-question answers, programming input/output and judging are correct |
| Statement completeness and answerability | 15 | Conditions, constraints, input/output specifications and examples are complete and consistent |
| Teaching suitability | 15 | Difficulty, prerequisites and expected workload suit the students |
| Assignment coverage and complementarity | 10 | Teaching objectives are covered without excessive concentration on the same question pattern |

The first four dimensions are labeled per question; the last is labeled per assignment. Labels are 0 for failing requirements, 1 for usable after revision, and 2 for directly usable. Insufficient information is marked “unassessed.” Each dimension's score is its mean valid label divided by 2 and multiplied by its weight, giving a total out of 100. Ordinary and programming questions are aggregated separately, then combined using question-type weights fixed before evaluation. No total is produced when any dimension lacks an assessment.

Out-of-scope content, wrong answers, missing necessary conditions, contradictory input/output and leaked hidden tests are serious defects. Count each affected question once and divide by the number of reviewed questions to calculate the defect rate. Reports must identify review counts, question counts and evaluation sources. Teacher scores and assistant reference assessments are reported separately; unreviewed questions are not counted as correct.
