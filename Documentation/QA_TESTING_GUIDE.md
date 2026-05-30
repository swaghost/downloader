# QA Regression Testing Guide

## Quick Start

**BEFORE EVERY COMMIT**, run the QA regression test suite:

```bash
python qa_regression_tests.py
```

Only commit if you see: `✅ ALL TESTS PASSED - OK TO COMMIT`

## Test Suite Commands

### Full Test Suite

```bash
python qa_regression_tests.py
```

Runs all 16 regression tests. Takes ~10 seconds.

### Quick Test Mode

```bash
python qa_regression_tests.py --quick
```

Skips slow integration tests. Use for rapid iteration.

### Verbose Mode

```bash
python qa_regression_tests.py --verbose
```

Shows detailed output for debugging test failures.

## What Tests Cover

The QA regression suite validates:

### 1. Import Tests (5 tests)

- All core modules import without errors
- Dependencies are properly resolved
- No circular import issues

### 2. Database Tests (2 tests)

- SQL Server connection works
- Accounts table exists and is accessible
- Database schema is valid

### 3. Main Content Extractor Tests (2 tests)

- Returns 5-element tuples: `(url, size, width, height, poster_hash)`
- Poster hash extraction logic exists
- Video/image extraction from DOM works

### 4. Downloader Tuple Unpacking Tests (2 tests)

- Handles both 2-element and 5-element tuples
- Format detection at all unpacking locations
- CDP poster hash validation exists

### 5. Scan Button Tests (3 tests)

- `scan_all_posts` method exists
- User feedback messages (QMessageBox) present
- Button properly connected to handler

### 6. Account Management Tests (2 tests)

- AccountManager initialization works
- Account switching sets `user_dir` correctly
- Directories created properly

## Test Coverage Summary

| Test Group         | Count  | Purpose                                    |
| ------------------ | ------ | ------------------------------------------ |
| Import Tests       | 5      | Verify modules load without errors         |
| Database Tests     | 2      | Validate SQL Server connectivity           |
| Content Extractor  | 2      | Verify DOM parsing and tuple format        |
| Tuple Unpacking    | 2      | Check format detection throughout codebase |
| Scan Button        | 3      | Validate UI functionality and feedback     |
| Account Management | 2      | Test account switching and persistence     |
| **TOTAL**          | **16** | **Comprehensive regression coverage**      |

## Interpreting Results

### ✅ All Tests Pass

```
======================================================================
TEST SUMMARY
======================================================================
Total:  16
Passed: 16 (100.0%)
Failed: 0
======================================================================

✅ ALL TESTS PASSED - OK TO COMMIT
```

**Action**: Safe to commit your changes.

### ❌ Tests Fail

```
======================================================================
TEST SUMMARY
======================================================================
Total:  16
Passed: 14 (87.5%)
Failed: 2
======================================================================

❌ FAILED TESTS:
  - Scan button user feedback
    Missing QMessageBox feedback in scan_all_posts

⚠️  DO NOT COMMIT - FIX FAILURES FIRST
```

**Action**: Fix the failures before committing. Use `--verbose` to see details.

## Adding New Tests

When adding new features, extend the test suite:

1. Add test function to appropriate group in `qa_regression_tests.py`
2. Follow naming convention: `test_<feature_name>`
3. Use `suite.run_test(name, func)` to register test
4. Document what the test validates

Example:

```python
def test_new_feature():
    """Test description."""
    suite.log("Testing new feature...")
    # Test logic here
    assert condition, "Error message if fails"
    suite.log("✓ Feature works")

suite.run_test("New feature test", test_new_feature)
```

## Common Failure Scenarios

### Import Errors

**Symptom**: Import tests fail  
**Cause**: Missing dependencies, syntax errors, circular imports  
**Fix**: Check the specific module for syntax errors or missing imports

### Database Connection Fails

**Symptom**: Database tests fail  
**Cause**: SQL Server not running, wrong connection string  
**Fix**: Verify SQL Server is running and accessible

### Tuple Unpacking Fails

**Symptom**: Downloader tuple format tests fail  
**Cause**: Missing format detection code after changes  
**Fix**: Ensure all tuple unpacking uses format detection:

```python
if len(item) == 2:
    url, size = item
elif len(item) >= 5:
    url, size, width, height, poster_hash = item
```

### Scan Button Tests Fail

**Symptom**: Scan button tests fail  
**Cause**: Modified `scan_all_posts` without preserving functionality  
**Fix**: Ensure:

- Method still exists
- User feedback messages present
- Button connection unchanged

## Integration with CI/CD

For automated testing in CI pipelines:

```bash
# Run tests and fail build if tests fail
python qa_regression_tests.py
if [ $? -ne 0 ]; then
    echo "Tests failed - blocking commit"
    exit 1
fi
```

## Manual Testing Checklist

After QA tests pass, manually verify:

- [ ] GUI launches without errors
- [ ] Can select/create account
- [ ] Scan button shows proper messages
- [ ] Download functionality works
- [ ] Database updates properly

## Troubleshooting

### "Module not found" errors

**Solution**: Ensure you're in the project root directory

### "Database connection failed"

**Solution**: Start SQL Server or check `config_constants.py` settings

### Tests pass but feature broken

**Solution**: Tests may be insufficient - add integration tests or extend coverage

## Best Practices

1. **Run tests before committing** - Catch regressions early
2. **Update tests when changing features** - Keep coverage current
3. **Use --verbose for debugging** - See detailed output
4. **Add tests for bug fixes** - Prevent regressions
5. **Document test intent** - Help future developers understand

## Support

If tests fail unexpectedly:

1. Run with `--verbose` to see details
2. Check if dependencies changed
3. Verify database connectivity
4. Check for module import issues
5. Review recent code changes

For questions, contact the development team or check project documentation.
