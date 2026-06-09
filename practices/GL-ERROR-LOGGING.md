# Error Handling & Logging Framework

_A comprehensive, proactive approach to error management for self-developing agent projects_

**Version**: 1.0
**Status**: Active Development Guidelines

---

## Philosophy

Error handling is a critical aspect of robust software development. This framework establishes a comprehensive, proactive approach to error management that integrates with README-Driven Development (GL-RDD.md) and Test-Driven Development (GL-TDD.md) principles.

## Core Principles

### The Four Pillars of Error Management

1. **Anticipate and Define Errors First**
   - Document potential error scenarios before implementation
   - Create comprehensive error taxonomies
   - Design error handling strategies during design phase

2. **Structured and Contextual Logging**
   - Every error must be traceable and actionable
   - Capture complete context at point of failure
   - Enable rapid debugging and system recovery

3. **Predictable Error Recovery**
   - Define clear recovery paths for each error type
   - Implement graceful degradation strategies
   - Minimize user-facing disruptions

4. **Continuous Error Intelligence**
   - Treat errors as first-class telemetry
   - Use error data to drive system improvements
   - Implement adaptive error handling mechanisms

## Error Classification Hierarchy

### Severity Levels

1. **DEBUG**: Detailed tracing information
   - Development and diagnostics only
   - Not visible in production
   - Used for deep system understanding

2. **INFO**: Noteworthy system events
   - Standard operational milestones
   - Non-critical path information
   - Useful for system behavior tracking

3. **WARNING**: Potential issues
   - Unexpected but non-blocking scenarios
   - Requires monitoring but no immediate action
   - Indicates potential future problems

4. **ERROR**: Functional disruptions
   - Operation cannot complete
   - Requires immediate investigation
   - Potential data integrity risks

5. **CRITICAL**: System-threatening events
   - Immediate intervention required
   - Potential complete system failure
   - Triggers emergency protocols

### Error Type Categories

1. **Domain Errors**
   - Business logic violations
   - Invalid state transitions
   - Domain-specific constraint breaches

2. **Infrastructure Errors**
   - External service failures (database APIs, messaging platforms, third-party services)
   - Database connection issues
   - Network communication problems

3. **Integration Errors**
   - API contract violations
   - Serialization/deserialization failures
   - Authentication and authorization issues

4. **Runtime Errors**
   - Memory constraints
   - Computational timeout
   - Resource exhaustion

5. **Security Errors**
   - Authentication failures
   - Unauthorized access attempts
   - Potential breach indicators

## Logging Strategy

### Recommended Logging Libraries

- **Primary**: `structlog` for structured logging
- **Fallback**: Python's native `logging` module

> **Note:** Native Python `logging` module is acceptable for straightforward use cases. structlog is recommended for modules with complex error flows requiring structured context.

### Configuration Requirements

```python
import structlog
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log"),
    ],
)

logger = structlog.get_logger()
```

### Logging Patterns

```python
def process_event(event_data: dict):
    try:
        logger.info(
            "Processing event",
            source_type=event_data.get("source_type"),
            event_id=event_data.get("id"),
            operation="event_pipeline",
        )
        # Processing logic
    except ValueError as e:
        logger.error(
            "Event validation failed",
            error=str(e),
            error_type="domain_error",
            context={
                "source_type": event_data.get("source_type"),
                "error_code": "INVALID_EVENT",
            },
        )
        raise
```

## External API Error Handling

### Connection and Request Patterns

- Implement exponential backoff for transient failures (429, 5xx)
- Handle authentication errors (401) by refreshing credentials
- Log request context (URL, method, relevant IDs) on all failures

```python
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

class ApiErrorHandler:
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def execute_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            response = httpx.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            logger.error(
                "API request error",
                url=url,
                status_code=e.response.status_code,
                error=str(e),
                error_type="infrastructure_error",
            )
            raise
        except httpx.ConnectError as e:
            logger.error(
                "API connection failed",
                url=url,
                error=str(e),
                error_type="infrastructure_error",
            )
            raise
```

## Script Exit Codes

Agent capability scripts communicate outcomes via exit codes. This convention enables the agent platform to distinguish success from different failure modes.

| Exit Code | Meaning | Agent Action |
|---|---|---|
| **0** | Success -- output on stdout | Use result |
| **1** | Recoverable error -- details on stderr | May retry or take alternative action |
| **2** | Fatal error -- details on stderr | Report to user, do not retry |
| **3** | Configuration error -- missing keys or misconfigured resources | Report to human operator |

### Script Pattern

```python
import sys
import json

def main():
    try:
        result = do_work()
        print(json.dumps(result))
        sys.exit(0)
    except ValueError as e:
        print(json.dumps({"error": str(e), "type": "validation"}), file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e), "type": "fatal"}), file=sys.stderr)
        sys.exit(2)
```

## Monitoring and Alerting

### Alert Thresholds

- **Error Rate**: > 5% of operations
- **Critical Error Rate**: > 1% of operations
- **Performance Degradation**: > 20% increase in error response time

### Required Metrics

- Total error count per severity
- Error distribution by type
- Average error resolution time
- System recovery rate

## Anti-Patterns to Avoid

### Error Handling Anti-Patterns

- Swallowing exceptions without logging
- Using generic exception handling (`except Exception` without specifics)
- Logging sensitive information (API keys, tokens, personal data)
- Inconsistent error message formats
- Blocking user interactions during errors
- Returning success exit code (0) when the operation actually failed
- Catching and re-raising without adding context

## Success Metrics

### Error Management Health Indicators

| Metric | Healthy | Warning | Critical | Action |
|--------|---------|---------|----------|--------|
| Error Rate | < 1% | 1-5% | > 5% | Investigate error sources |
| Critical Error Rate | < 0.1% | 0.1-1% | > 1% | Immediate system review |
| Error Resolution Time | < 1 min | 1-5 min | > 5 min | Optimize error handling |
| Logging Completeness | 100% | 90-99% | < 90% | Improve logging coverage |

## Known Issues Documentation

Projects should maintain a known issues section in this file (or a linked KNOWN_ISSUES.md) documenting platform-specific bugs and workarounds. Each entry follows this structure:

### Entry Template

```markdown
### [Short Description] ([Date Discovered])

**Severity:** [DEBUG | INFO | WARNING | ERROR | CRITICAL] -- [impact summary]
**Category:** [Domain | Infrastructure | Integration | Runtime | Security] Error -- [subcategory]
**Discovered:** [Date], [context of discovery]

#### Symptoms

1. [Observable symptom 1]
2. [Observable symptom 2]

#### Root Cause

[Technical explanation of why this happens. Reference specific code paths,
functions, and modules. Include evidence: log excerpts, session IDs,
variable states.]

#### Impact

| Affected Component | Impact | Severity |
|---|---|---|
| [Component] | [What breaks] | [Critical/High/Medium/Low] |

#### Fix Applied ([Sprint/PR reference])

1. [Change 1: what was done and where]
2. [Change 2: what was done and where]

#### Key Lesson

[One or two sentences capturing the generalizable insight. This is the most
valuable part -- it prevents the same class of bug from recurring.]
```

### Why Document Known Issues

1. **Prevents recurrence**: Future developers (human or AI) can search for symptoms and find existing analysis
2. **Captures root cause reasoning**: The "why" is often harder to rediscover than the fix itself
3. **Builds institutional knowledge**: Patterns emerge across incidents (e.g., "trust but verify" for server-side filters, "guards must be in the delivery path")
4. **Accelerates debugging**: Matching symptoms to documented issues shortcuts investigation

### What to Include

- Bugs that took significant debugging effort (the analysis is the value)
- Platform-specific behaviors that differ from documentation
- Architectural violations that bypassed safety mechanisms
- Issues where the obvious fix was wrong and the real fix was non-obvious

### What NOT to Include

- Simple typos or one-line fixes
- Issues fully covered by test regression
- Platform-specific incidents that do not generalize (move these to platform docs)

---

_This framework establishes a comprehensive, proactive approach to error management for self-developing agent projects._
