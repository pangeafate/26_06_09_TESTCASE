# Test-Driven Development Framework

_A comprehensive, prescriptive framework for implementing Test-Driven Development in AI agent projects_

**Version**: 1.0
**Status**: Active Development Guidelines

---

## Core Philosophy

Test-Driven Development (TDD) ensures code correctness through a disciplined cycle of writing tests before implementation. When combined with README-Driven Development (GL-RDD.md), tests become the executable specification of documented behavior.

## Integration with README-Driven Development

```
README (Contract) -> Test (Specification) -> Code (Implementation)
```

1. **README defines WHAT** - The contract and expected behavior
2. **Tests define HOW** - The executable specification
3. **Code delivers IT** - The minimal implementation

## Fundamental Laws of TDD -- STRICTLY FOLLOW

### The Five Commandments

1. **Never write production code without a failing test**
   - Test must exist and fail before implementation
   - **Exception: Infrastructure setup and configuration**
2. **Never write more test than sufficient to fail**
   - Including compilation/interpretation failures
   - One assertion at a time when starting
3. **Never write more production code than sufficient to pass**
   - Minimal implementation only
   - Resist the urge to add "obvious" features
4. **Never refactor with failing tests**
   - All tests must be green before refactoring
   - Run tests after every refactoring step
5. **Never commit with failing tests**
   - All tests must pass before version control commit
   - Broken tests = broken build

## Prescribed Technology Stack

### Python Projects

**RECOMMENDED TOOLS** *(alternatives acceptable with justification):*

- **Unit/Integration Testing**: pytest (preferred -- superior to unittest)
- **API Testing**: pytest + httpx
- **Mocking**: pytest-mock
- **Test Data**: Faker or equivalent
- **Coverage**: pytest-cov
- **Structured assertions**: assertpy or plain assert

## Project Test Structure Requirements

### Mandatory Directory Structure

```
project-root/
├── test/
│   ├── unit/                       # Unit tests mirror src structure
│   ├── integration/                # Integration tests by feature
│   ├── fixtures/                   # Shared test data
│   └── conftest.py                 # Shared pytest fixtures
```

### File Naming Conventions

| Test Type | Required Pattern | Example |
|---|---|---|
| Unit Test | `test_[module].py` | `test_user_service.py` |
| Integration | `test_[feature]_integration.py` | `test_intake_pipeline_integration.py` |
| Fixtures | `[name]_fixtures.py` | `event_fixtures.py` |

## TDD Workflow Requirements

### RED Phase Guidelines

1. **Test Must Fail First**
   - Run test immediately after writing
   - Verify failure message is meaningful
   - If test passes without implementation, test is wrong
2. **One Test at a Time**
   - Write single test case
   - No additional tests until current one passes
   - Focus on smallest possible behavior
3. **Use AAA Pattern**
   - Arrange: Set up test data
   - Act: Execute function under test
   - Assert: Verify outcome

### GREEN Phase Guidelines

1. **Minimal Implementation Only**
   - Write just enough code to pass the current test
   - No optimization at this stage
   - No edge case handling (unless currently tested)
   - No "future-proofing"
   - *Note: Coverage may temporarily decrease; addressed in REFACTOR phase*
2. **Run All Tests**
   - Ensure no regression
   - All tests must remain green
   - If other tests fail, fix immediately

### REFACTOR Phase Guidelines

1. **Only When Green**
   - Never refactor with failing tests
   - Run tests after each change
   - Keep changes small
2. **Maintain Test Coverage**
   - Overall coverage must not decrease below project minimums
   - Add tests if uncovered code emerges during refactoring
   - Remove dead code and corresponding tests

## Test Data Management

### Factory Requirements

**Every entity must have:**

1. Factory function or class with `create()` method
2. Support for overrides
3. Batch creation method
4. Realistic fake data (using Faker)

### Mock Strategy

| Scenario | Unit Tests | Integration Tests | Why |
|---|---|---|---|
| External API calls | httpx mock | Test instance or sandbox | Unit: fast; Integration: real API |
| Email sending | Mock transport | Mock transport | Never send real emails in tests |
| File system | Memory FS / tmp | Memory FS / tmp | No side effects |
| Time-dependent | Fake timers | Fake timers | Deterministic results |
| Random values | Seeded random | Seeded random | Reproducible results |
| Database calls | Mock client | Test database | Unit: isolated; Integration: real queries |

## Coverage Requirements

### Base Coverage Thresholds (Build Fails If Not Met)

| Metric | Minimum | Target | Build Fails If | Machine-enforced? |
|---|---|---|---|---|
| Line Coverage | 80% | 85% | < 80% | Yes — `validate_tdd.py` |
| Branch Coverage | 75% | 80% | < 75% | Yes — `validate_tdd.py` |
| Function Coverage | 80% | 85% | < 80% | No — review checklist (see below) |

### How the coverage gate is enforced

`validate_tdd.py` enforces the line and branch thresholds from a **Cobertura
coverage report** — it does not run your tests, it reads the artifact they
produce. Wire it into your test step:

```bash
pytest --cov=src --cov-report=xml      # writes coverage.xml
python validators/validate_tdd.py <project-root>   # parses it, fails if below threshold
```

- **Report present** → line/branch coverage below threshold fails the build.
- **No report** → the gate is **advisory** (does not fail), so a project that
  has not yet wired up `pytest-cov` is not blocked. Make a missing report a hard
  failure with `--require-coverage-report` or `coverage.require_report: true`.
- Thresholds and the report path are configurable in `.validators.yml`:

  ```yaml
  coverage:
    line: 80          # percent
    branch: 75        # percent
    report: coverage.xml
    require_report: false
  ```

**Function coverage** has no standard machine-readable artifact (Cobertura
reports line and branch rates only), so the 80% function-coverage target is a
**review-checklist item**, not an automated gate — reviewers confirm every
public function has at least one exercising test during Stage 5.

### Module-Specific Targets

| Module Type | Target Coverage | Critical Focus | Minimum |
|---|---|---|---|
| Shared library | 95% | All business logic | 90% |
| Capability scripts | 85% | All execution paths | 80% |
| Models / domain | 90% | Validation, enums | 85% |
| Config | 75% | Validation logic | 60% |
| Infrastructure scripts | 60% | Setup logic | 50% |

## CI/CD Integration Requirements

### Pre-Commit Hooks (MANDATORY)

```
1. Lint check (must pass)
2. Type check (must pass)
3. Unit tests (must pass)
4. Coverage check (must meet thresholds)
```

### Pull Request Gates (MANDATORY)

```
1. All tests pass (100% pass rate)
2. Coverage doesn't decrease
3. No skipped tests
4. Performance benchmarks met
```

## Performance Standards

### Test Execution Time Limits

#### Individual Test Limits

| Test Type | Maximum Time | Action if Exceeded |
|---|---|---|
| Unit Test | 50ms | Investigate, optimize, or mock |
| Integration Test | 500ms | Check external calls |

#### Test Suite Limits

| Suite Type | Maximum Time | Health Status |
|---|---|---|
| Unit Suite | 2 minutes | Healthy < 2min, Warning 2-5min |
| Integration Suite | 3 minutes | Healthy < 3min, Warning 3-8min |
| **Total Test Runtime** | **5 minutes** | **Healthy < 3min, Critical > 8min** |

### Optimization Requirements

**Mandatory optimizations:**

1. Parallel test execution (except where impossible)
2. Shared setup between related tests
3. Mock all external services in unit tests
4. Reuse test data factories

## Anti-Patterns to Avoid

### Testing Anti-Patterns

**NEVER DO:**

- Test private methods directly
- Use production database in tests
- Share state between tests
- Test multiple behaviors in one test
- Use random/non-deterministic data
- Skip error scenarios
- Test implementation instead of behavior
- Use sleep/wait with fixed timeouts
- Ignore flaky tests
- Disable failing tests

### Code Smells in Tests

**RED FLAGS:**

- Unit tests > 50 lines
- Complex setup/teardown that obscures test intent
- Conditional logic in tests
- Loops in test assertions
- Tests dependent on execution order
- Hardcoded values instead of factories
- Missing error scenarios
- No negative test cases
- Mocking everything (balance with integration testing)

## Success Metrics

### TDD Health Indicators

| Metric | Healthy | Warning | Critical | Action Required |
|---|---|---|---|---|
| Coverage | >= 85% | 70-84% | < 70% | Review uncovered critical paths |
| Test Execution Time | < 3 min | 3-5 min | > 8 min | Optimize or parallelize |
| Flaky Test Rate | < 1% | 1-5% | > 5% | Fix or rewrite flaky tests |
| Test/Code Ratio | >= 1.2:1 | 0.8-1.2:1 | < 0.8:1 | Add missing test coverage |
| Bug Escape Rate | < 5% | 5-10% | > 10% | Review test strategy |

## Quick Reference

### TDD Cycle Checklist

```
[ ] Documentation exists (README / capability spec)
[ ] Test file created
[ ] Test written and failing (RED)
[ ] Minimal code written (GREEN)
[ ] All tests still passing
[ ] Code refactored if needed (REFACTOR)
[ ] Coverage meets requirements
[ ] Documentation updated
[ ] Ready to commit
```

### Essential Commands

| Action | Command | When |
|---|---|---|
| Run unit tests | `pytest test/unit/` | After every change |
| Run integration tests | `pytest test/integration/` | Before commit |
| Check coverage | `pytest --cov=src --cov-report=html` | Before PR |
| Run specific test | `pytest test/unit/test_module.py` | During development |
| Run with verbose | `pytest -v` | When debugging failures |

---

_This framework establishes TDD as the quality backbone of self-developing agent projects, with prescriptive tool choices and strict guidelines for implementation._
