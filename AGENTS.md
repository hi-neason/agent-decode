# Project Guidelines

## Project Purpose

- agent-decode is a collection of learning notes that explain Agent principles through source code analysis.
- Analyze well-known open-source Agent frameworks to help readers understand both the underlying concepts and their practical implementation.
- Introduce the problem and core concepts first, then use source code to explain execution flows, key mechanisms, and design tradeoffs.

## Teaching Approach

- Write for programmers who already understand basic programming, HTTP, JSON, and common development workflows. Keep elementary explanations brief and spend the space on mechanisms, protocol details, failure cases, and engineering tradeoffs.
- Include interview-relevant technical questions and follow-up reasoning, grounded in the chapter's implementation. Interview preparation is one goal, not the limit of the curriculum; do not claim question frequency without evidence.
- Follow a problem-driven progression: scenario -> problem -> minimal solution -> implementation -> new problem.
- Start each chapter with a concrete limitation of the Agent built so far. Introduce only the mechanisms needed to address the current scenario.
- Maintain one small teaching Agent that evolves across chapters, starting with a single LLM call. Keep its code and execution flow coherent as capabilities are added.
- End each chapter by stating the capability gained, the remaining limitations, and the next chapter or optional branches that address them.
- Prefer chapter titles that express the reader's problem, with the technical concept as a subtitle or qualifier.
- Organize knowledge as a dependency graph while offering beginners a recommended reading sequence. Distinguish required prerequisites from optional related topics; do not force every topic into one linear chain.
- Introduce a topic at the depth needed for the current task and revisit it later for deeper mechanisms and engineering tradeoffs. Cross-link shared explanations instead of duplicating them.
- Treat the learning sequence as a teaching choice, not a universal architecture or mandatory evolution path for all Agents.

## Source Code Case Studies

- Structure topics around the problem, a minimal teaching implementation, verified source code cases, design comparisons, and unresolved questions.
- Explain the problem and minimal mechanism before claiming a general solution; do not present one framework's design as an industry-wide rule.
- Use OpenAI Codex as the primary source-code learning project across the curriculum. Trace its actual implementation at a pinned commit; use Pi, Hermes, and other projects only for meaningful contrasts or capabilities outside the verified Codex scope.
- Keep problem-driven explanations and simplified teaching examples distinct from Codex implementation details. Do not imply that Codex implements every API or architectural option covered by the curriculum.
- Choose a clear primary case for each topic and add contrasting cases only when they improve understanding. Do not require every chapter to cover every project.
- Compare solutions to the same technical problem, including their assumptions, behavior, constraints, and tradeoffs, rather than merely listing implementation differences.
- Provide project-level guides covering architecture, entry points, module boundaries, and an end-to-end task flow. Link these guides to the relevant topic analyses so readers can explore both by concept and by project.
- Keep the recommended learning route, technical topics, and project guides as complementary navigation paths over shared content.

## Website and Content Stack

- Use Docusaurus to build the educational documentation website.
- Write content in Markdown/MDX: use `.md` for regular chapters and `.mdx` for chapters that embed React components.
- Use documents for explanations, code snippets, images, and references; use React components for interactive diagrams and animated demonstrations.
- Add diagrams, GIFs, and interactive demonstrations where useful. Animation is not required in every article.
- For execution flows such as the Agent Loop, tool calls, and context changes, prefer demonstrations that support pausing and stepping through the process so readers can compare each step with the source code.
- Use Docusaurus for website navigation and publishing, keeping routine content authoring and maintenance simple.

## Writing Requirements

- Write this `AGENTS.md` file in English.
- Write the initial Markdown/MDX curriculum in Chinese. Add multilingual editions after the Chinese curriculum is complete; do not scaffold translations prematurely.
- Chapter 1 covers a single LLM interaction across OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages, including streaming transport, event aggregation, and completion/error semantics. Later chapters deepen tool-specific protocol behavior.
- Ground technical explanations in actual source code. Verify the implementation before drawing conclusions.
- Identify the upstream project and the version or commit being analyzed, and provide source code references.
- Clearly distinguish simplified teaching examples from the upstream project's actual implementation.

## Verification and Delivery

- After completing changes, run the tests and checks appropriate to the scope of the change.
- Once verification passes, automatically commit and push the task's changes without requesting confirmation again, unless the user explicitly asks otherwise.
- Include only files relevant to the task in each commit and preserve unrelated worktree changes.
- If verification or pushing fails, resolve the issue where possible and report any remaining blocker without claiming successful delivery.
- Verify that the remote branch contains the resulting commit and report the validation results and commit identifier.
