# Project Guidelines

## Project Purpose

- agent-decode is a collection of learning notes that explain Agent principles through source code analysis.
- Analyze well-known open-source Agent frameworks to help readers understand both the underlying concepts and their practical implementation.
- Introduce the problem and core concepts first, then use source code to explain execution flows, key mechanisms, and design tradeoffs.

## Website and Content Stack

- Use Docusaurus to build the educational documentation website.
- Write content in Markdown/MDX: use `.md` for regular chapters and `.mdx` for chapters that embed React components.
- Use documents for explanations, code snippets, images, and references; use React components for interactive diagrams and animated demonstrations.
- Add diagrams, GIFs, and interactive demonstrations where useful. Animation is not required in every article.
- For execution flows such as the Agent Loop, tool calls, and context changes, prefer demonstrations that support pausing and stepping through the process so readers can compare each step with the source code.
- Use Docusaurus for website navigation and publishing, keeping routine content authoring and maintenance simple.

## Writing Requirements

- Write this `AGENTS.md` file in English.
- Ground technical explanations in actual source code. Verify the implementation before drawing conclusions.
- Identify the upstream project and the version or commit being analyzed, and provide source code references.
- Clearly distinguish simplified teaching examples from the upstream project's actual implementation.
