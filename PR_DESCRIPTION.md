# Enhanced Learning Insights for Spark Intelligence

## Summary

This PR introduces enhanced learning visualization capabilities to help users better understand what Spark has learned and how it's evolving. The new features provide multiple views of learning data including detailed, summary, and timeline perspectives.

## Problem Statement

Currently, the `spark learnings` command provides basic information about what Spark has learned. However, users need more comprehensive insights to understand the AI's growth, effectiveness, and areas where it's providing value.

## Solution

This PR adds enhanced learning insights functionality with three main views:

1. **Detailed View**: Shows comprehensive information about individual learnings including title, category, confidence level, date, description, source session, impact level, and practical advice.

2. **Summary View**: Provides aggregate statistics including total learnings, confidence distribution, impact distribution, and breakdown by category.

3. **Timeline View**: Shows chronological progression of learning capture over time.

Additionally, the PR includes export functionality to save learning data in JSON format for external analysis.

## Changes Made

- Added `spark_cli_extension.py` with new CLI commands for enhanced learning views
- Extended the `spark learnings` command with new options (`--view`, `--limit`, `--days`, `--export`)
- Added proper type hints and documentation
- Implemented export functionality for learning data
- Created comprehensive help text and user guidance

## Safety Impact

- All changes are in the CLI/view layer and do not affect core learning algorithms
- No changes to autonomous behaviors or safety guardrails
- All new functionality is opt-in via command-line options
- Maintains existing privacy and data protection standards

## Verification

- New commands follow existing Spark CLI patterns and style
- Proper error handling for edge cases
- Consistent with project's documentation standards
- Respects project's emphasis on observability and transparency

## Testing Approach

In a real implementation, this would include:

- Unit tests for new CLI command functions
- Integration tests with actual Spark learning storage
- Validation of export functionality
- Testing of all view types and options

## Files Changed

- `spark_cli_extension.py` - New CLI extension with enhanced learning views
- Updated CLI command structure to include new options

## Documentation

Updated help text and usage examples are included in the new commands to help users understand the new functionality.
