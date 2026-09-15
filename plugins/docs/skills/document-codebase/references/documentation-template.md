# Project Documentation Template

> A reusable, question-driven documentation template for any software, hardware, data, infrastructure, or mixed-technology project.
>
> **Model instruction:** Answer every question in this file using evidence from the project repository, source code, configuration, tests, issue tracker, and deployment artifacts where available. Do not invent facts. If evidence is unavailable, write `Unknown — evidence required` and identify what must be checked.

## Contents

- Documentation-wide review
- 1. Getting Started
- 2. Architecture
- 3. Usage and Operations
- 4. Development and Contribution
- 5. Appendix
- Final Review Checklist

## How to use this template

1. Replace each `Answer:` placeholder with evidence-based documentation.
2. Preserve the question headings until review is complete.
3. Link claims to source files, tests, configuration, requirements, or external references.
4. Distinguish confirmed facts, reasonable inferences, and unresolved questions.
5. Remove unanswered questions only after a reviewer confirms that they are not applicable.
6. Keep examples representative, safe, and free of credentials or sensitive data.

## Documentation-wide review

### Required model answers

1. What project, product, service, or system does this documentation describe?
2. What version, revision, release, or date does it apply to?
3. Who are the intended audiences for each section?
4. What documentation sources and repository artifacts were used?
5. Are all important claims supported by evidence?
6. Which information is confirmed, inferred, outdated, missing, or awaiting approval?
7. Does the documentation cover the complete user, operator, developer, and maintainer lifecycle?
8. Are terminology, links, examples, version references, and commands consistent throughout?

**Answer:**

---

# 1. Getting Started

## 1.1 Introduction

### Required model answers

1. What is the product or system, and what problem does it solve?
2. Who are the intended users, operators, maintainers, or integrators?
3. What are the core capabilities and supported input or domain-specific element types?
4. What are the primary use cases and important non-use cases?
5. What dependencies, external systems, or services are required?
6. What are the known limitations, assumptions, and constraints?
7. Which documentation sections should a new reader visit next?

**Answer:**

## 1.2 Installation and Environment Setup

### Required model answers

1. What runtime, operating-system, platform, and tool prerequisites are required?
2. What hardware, network, permissions, credentials, or external services are required?
3. How should the project or product be installed for each supported environment?
4. How should the project workspace, input files, and output location be prepared?
5. Which dependencies, packages, plugins, drivers, or private artifacts are needed?
6. What configuration values or environment variables are required?
7. How can the installation be verified with a minimal smoke test?
8. What installation failures are common and how should they be resolved?
9. How should the system be uninstalled, upgraded, or reset?

**Answer:**

## 1.3 Quick Start

### Required model answers

1. What is the smallest valid example that demonstrates the main value of the system?
2. What command, API call, workflow, or user action starts the smallest useful operation?
3. Which workspace, input file, and operation values should the example use?
4. What output, status, log, notification, or observable result should the user expect?
5. How can the user confirm that the operation completed correctly?
6. What should the user check when the example fails or produces no visible result?
7. Which parts of the example must be changed for a real project or production environment?

**Answer:**

---

# 2. Architecture

## 2.1 System Overview

### Required model answers

1. What are the major components, subsystems, services, or layers?
2. What responsibility does each component own?
3. How do the components interact at a high level?
4. What are the main inputs, outputs, interfaces, and trust boundaries?
5. Which design patterns, architectural principles, or constraints guide the design?
6. Which components are replaceable, optional, external, or technology-specific?
7. What are the main scalability, availability, performance, and security considerations?
8. Which source files, diagrams, tests, or deployment definitions support this overview?

**Answer:**

## 2.2 Data Flow and Processing Flow

### Required model answers

1. What are the inputs, transformations, decisions, and outputs in order?
2. What are the exact processing phases and their entry and exit conditions?
3. How are requests routed to the components responsible for each operation or data type?
4. What data structures, messages, files, or events move between phases?
5. What invariants must remain true throughout processing?
6. Where are validation, parsing, transformation, persistence, and logging performed?
7. How are ordering, duplicates, retries, partial success, and idempotency handled?
8. What can fail in each phase, and what recovery behavior is guaranteed?
9. Which diagram or code references prove the described flow?

**Answer:**

## 2.3 Component and Module Reference

### Required model answers

1. Which modules, packages, services, or components make up the system?
2. What single responsibility does each module or component have?
3. What are the public interfaces, classes, functions, endpoints, messages, or data models?
4. How do modules or components call or depend on one another?
5. Which components handle external I/O, validation, business logic, persistence, and observability?
6. What inputs, outputs, side effects, and failure modes belong to each component?
7. Which interfaces are stable, internal, deprecated, experimental, or unsupported?
8. Which source locations, tests, and configuration files support every description?

**Answer:**

## 2.4 Class, Entity, or Relationship Diagrams

### Required model answers

1. Which entities, classes, services, or data models are central to the system?
2. What inheritance, composition, aggregation, ownership, and dependency relationships exist?
3. Which elements own validation, traversal, transformation, persistence, and orchestration?
4. Which external base types, services, or dependencies cannot be resolved locally?
5. How does the structure support extension, reuse, isolation, and testability?
6. Which relationships are verified from source code, and which are inferred?
7. What important relationships or lifecycle states are not shown in the diagram?

**Answer:**

---

# 3. Usage and Operations

## 3.1 Invoking the System

### Required model answers

1. What is the primary entry point, command, API, workflow, or user action used to run the system?
2. What arguments, parameters, headers, environment values, or permissions are required?
3. What inputs and types must callers provide?
4. Which options are optional, and what defaults apply?
5. What happens during a successful invocation?
6. What return values, statuses, events, logs, or exceptions can callers observe?
7. Provide a minimal example and a realistic integration example.
8. How should the system be invoked safely in development, staging, and production?

**Answer:**

## 3.2 Configuration Parameters

### Required model answers

1. What is the complete configuration schema, including top-level and nested fields?
2. What are the type, required status, default, valid values, and constraints of each field?
3. Which domain-specific element types, fields, formats, or operations are supported?
4. Which configuration values are environment-specific or deployment-specific?
5. How are inputs matched, selected, transformed, created, updated, or deleted?
6. What validation rules, access checks, and existence checks are enforced?
7. What precedence applies when configuration sources conflict?
8. Provide valid, invalid, minimal, and boundary-value examples.
9. Which source models, schemas, tests, and examples verify these rules?

**Answer:**

## 3.3 Handling Outputs and Side Effects

### Required model answers

1. Which files, records, events, responses, notifications, or artifacts are produced?
2. How do normal, dry-run, preview, in-place, and output-directory modes differ?
3. Which backups, temporary files, caches, or audit records are created?
4. How are directory structure, naming, encoding, formats, metadata, and permissions handled?
5. What result statistics, logs, statuses, and notifications are produced?
6. How can an operator validate, consume, restore, archive, or delete outputs?
7. Which side effects are guaranteed, conditional, irreversible, or externally controlled?
8. What data retention, privacy, and security rules apply to generated outputs?

**Answer:**

## 3.4 Error Handling and Recovery

### Required model answers

1. Which validation, input, network, dependency, runtime, and persistence errors can occur?
2. Which component detects, raises, translates, logs, or handles each error?
3. What message, status, log entry, or identifier identifies the failing operation?
4. Which failures stop processing and which allow partial success or continuation?
5. What retry, rollback, recovery, fallback, or backup behavior is available?
6. What information must be collected before escalating an issue?
7. Provide troubleshooting steps for the most likely and most severe failures.
8. Which failures are expected behavior rather than defects?

**Answer:**

## 3.5 Detailed Processing Phases

### Required model answers

1. What are the exact phases from input acceptance to final output?
2. What inputs, outputs, invariants, and side effects belong to each phase?
3. How are resources resolved, loaded, validated, transformed, persisted, and released?
4. How are ordering, duplicate requests, retries, skipped operations, and partial success handled?
5. Where are checkpoints, backups, transactions, and metadata created?
6. What logs, metrics, traces, and statistics allow each phase to be audited?
7. Which phase is responsible for each class of error?
8. What performance or resource constraints apply to each phase?

**Answer:**

---

# 4. Development and Contribution

## 4.1 Local Development Setup

### Required model answers

1. Which runtime, dependency manager, build tool, and repository tools are required?
2. What operating-system, hardware, network, or access prerequisites apply?
3. How should dependencies and development dependencies be installed?
4. Which environment variables, paths, services, or private artifacts must be configured?
5. How should linting, formatting, tests, builds, documentation, and hooks be run locally?
6. What IDE, editor, debugger, or container settings improve development?
7. How can a developer reset the environment and reproduce a clean setup?
8. What setup problems are known and how should they be diagnosed?

**Answer:**

## 4.2 Testing Strategy

### Required model answers

1. What test frameworks, directories, fixtures, and test categories exist?
2. How are unit, integration, error-path, fixture, contract, performance, and end-to-end tests executed?
3. Which commands run the complete suite, a module, a test, and coverage analysis?
4. Which behavior, risks, and edge cases are covered?
5. What remains uncovered, untested, mocked, or dependent on external systems?
6. What coverage targets, quality gates, and test-environment requirements apply?
7. How should a contributor add deterministic tests and expected outputs?
8. How are flaky, failing, skipped, or quarantined tests handled?
9. Which test results are required before review, merge, release, or deployment?

**Answer:**

## 4.3 Contribution and Extension Guide

### Required model answers

1. What contribution types and extension points are supported?
2. What coding, typing, documentation, security, and compatibility standards apply?
3. How should a contributor implement support for a new feature, data type, format, or integration?
4. Which tests, fixtures, diagrams, schemas, and documentation must change together?
5. What branch, commit, review, and pull-request workflow is required?
6. What checks must pass before a change can be merged?
7. Which changes are prohibited or require maintainer, security, or architecture approval?
8. How should contributors report defects, propose enhancements, and document breaking changes?

**Answer:**

## 4.4 API, Module, or Interface Reference

### Required model answers

1. What package, module, service, endpoint, command, or interface paths exist?
2. What public classes, functions, models, constants, events, schemas, and errors are exposed?
3. What are the signatures, types, responsibilities, and side effects of public interfaces?
4. What dependencies and call relationships connect the interfaces?
5. Which interfaces are stable, internal, deprecated, experimental, or unsupported?
6. What authentication, authorization, validation, rate, or lifecycle rules apply?
7. Which source lines, schemas, generated specifications, and tests verify the reference information?
8. How are interface changes versioned and communicated?

**Answer:**

## 4.5 Packaging and Release

### Required model answers

1. How is the project or product version defined and updated?
2. What build, installation, deployment, or distribution artifacts are produced?
3. Where are artifacts stored, published, signed, or promoted?
4. Which commands build, validate, inspect, and install a release artifact?
5. What release prerequisites, approvals, compatibility checks, and security checks apply?
6. How are dependencies, changelog entries, schemas, and documentation synchronized?
7. How are migrations, deprecations, and breaking changes communicated?
8. How can a failed, compromised, or incorrect release be rolled back or superseded?
9. Who owns release approval and post-release verification?

**Answer:**

## 4.6 CI/CD Workflow

### Required model answers

1. What events trigger validation, build, release, deployment, and scheduled workflows?
2. What are the pipeline stages and in what order do they run?
3. Which tools, environments, permissions, secrets, artifacts, and quality gates are used?
4. How are tests, coverage, linting, security, packaging, and documentation validated?
5. What happens when a stage fails, and how are logs and artifacts inspected?
6. Which branch protections, approvals, and change controls affect merging or releasing?
7. How are deployments promoted, verified, monitored, and rolled back?
8. How are pipeline configuration changes reviewed and tested?

**Answer:**

---

# 5. Appendix

## 5.1 Compliance and Governance

### Required model answers

1. Which domain, regulatory, security, privacy, licensing, accessibility, or quality requirements apply?
2. What implementation behavior demonstrates compliance with each requirement?
3. Which evidence, tests, reviews, controls, or tools verify compliance?
4. What constraints apply to data handling, logging, backups, generated files, and access?
5. Which requirements are not met, partially met, or outside project scope?
6. What risks, exceptions, waivers, or compensating controls exist?
7. Who owns compliance decisions and when must this page be reviewed?

**Answer:**

## 5.2 Glossary

### Required model answers

1. Which domain, technical, business, operational, and project-specific terms need definitions?
2. What is the precise definition, abbreviation, and context for each term?
3. Which terms are synonyms, deprecated names, or commonly confused concepts?
4. Which examples or source references clarify each definition?
5. Are all terms used consistently across the documentation?
6. Which terms require confirmation from a domain expert?

**Answer:**

## 5.3 Troubleshooting

### Required model answers

1. What symptoms, error messages, statuses, and log entries indicate each common problem?
2. What are the likely root causes and how can they be distinguished?
3. What diagnostic steps should the user perform, and in what order?
4. What corrective action, workaround, retry, rollback, or escalation resolves each problem?
5. When should the user restore a backup, rerun an operation, or stop processing?
6. What information should be included in a support request or defect report?
7. Which source, test, requirement, or known limitation supports each troubleshooting entry?

**Answer:**

## 5.4 Frequently Asked Questions

### Required model answers

1. What questions do new users ask about installation and first use?
2. What questions arise about configuration, supported data types, operations, and matching rules?
3. What questions arise about outputs, backups, logs, permissions, and partial success?
4. What questions arise about errors, performance, security, and limitations?
5. What concise, evidence-based answer should be given to each question?
6. Which FAQ entries are still unanswered or require product-owner confirmation?

**Answer:**

## 5.5 References

### Required model answers

1. Which standards, libraries, repositories, specifications, policies, and tools are referenced?
2. What claim or documentation topic does each reference support?
3. What are the title, version, author or owner, date, and stable link for each reference?
4. Which references are normative, informative, internal, or obsolete?
5. Are links accessible and are cited versions compatible with this project version?
6. Are all external licenses and attribution requirements recorded?

**Answer:**

## 5.6 Output and Artifact Structure

### Required model answers

1. What directory, namespace, record, or artifact structure is produced in each operating mode?
2. Which files, records, events, or artifacts are copied, transformed, backed up, generated, or left unchanged?
3. How are relative paths resolved below the project workspace and output root?
4. What naming, extension, encoding, format, metadata, and permission rules apply?
5. Which outputs are guaranteed after success, skip, cancellation, or failure?
6. Provide representative input-to-output structure examples and validation steps.
7. Which outputs contain sensitive, temporary, or retention-controlled information?

**Answer:**

## 5.7 Changelog

### Required model answers

1. What releases, dates, and changes are documented?
2. Which changes are breaking, behavioral, compatibility-related, security-related, or internal?
3. Which issue, pull request, requirement, or decision supports each change?
4. Are upgrade actions, migration notes, or deprecation notices required?
5. Are there unreleased changes that must be confirmed before publication?
6. Does the changelog follow the project's versioning and release policy?

**Answer:**

---

# Final Review Checklist

The model or reviewer must confirm:

- [ ] Every required question has an evidence-based answer.
- [ ] Unknown or unavailable information is explicitly marked.
- [ ] No credentials, secrets, private keys, or sensitive data are included.
- [ ] Commands, paths, APIs, configuration examples, and versions are verified.
- [ ] Architecture claims match the current implementation.
- [ ] Error-handling and recovery behavior is documented accurately.
- [ ] Tests and quality gates are documented and reproducible.
- [ ] Security, privacy, licensing, accessibility, and compliance concerns are addressed where applicable.
- [ ] Internal links and external references are valid.
- [ ] Terminology is consistent across all sections.
- [ ] The documentation has been reviewed for the intended audience.
- [ ] The documentation version and review date are recorded.

**Final review notes:**
