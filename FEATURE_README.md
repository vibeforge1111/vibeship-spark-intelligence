# Enhanced Learning Insights Feature

This feature adds enhanced visualization and analysis capabilities to Spark's learning system, helping users better understand what Spark has learned and how it's evolving.

## Overview

The Enhanced Learning Insights feature provides multiple perspectives on Spark's accumulated knowledge:

- **Detailed View**: Comprehensive information about individual learnings
- **Summary View**: Aggregate statistics and trends
- **Timeline View**: Chronological progression of learning capture
- **Export Capability**: Save learning data for external analysis

## Installation

This feature extends the existing Spark CLI. After merging, simply use the extended options with the `spark learnings` command.

## Usage

### Detailed View (Default)

Shows comprehensive information about recent learnings:

```bash
spark learnings --view detailed --limit 10
```

### Summary View

Provides aggregate statistics about all learnings:

```bash
spark learnings --view summary
```

### Timeline View

Shows learning capture over time:

```bash
spark learnings --view timeline --days 14
```

### Export Data

Save learning insights to a JSON file:

```bash
spark learnings --view detailed --export ./my_learnings.json
spark learnings --view summary --export ./learning_summary.json
```

## Options

- `--view`: Type of view to display (detailed, summary, timeline)
- `--limit`: Number of items to display (for detailed view)
- `--days`: Number of days to show (for timeline view)
- `--export`: File path to export results as JSON

## Benefits

1. **Better Visibility**: Understand what Spark has learned from your coding sessions
2. **Performance Tracking**: Monitor the growth and effectiveness of Spark's insights
3. **Actionable Intelligence**: Get practical advice based on Spark's observations
4. **Data Portability**: Export learning data for external analysis or reporting

## Safety & Privacy

- All data remains local to your machine
- No changes to Spark's core learning algorithms
- All functionality is opt-in via command-line options
- Maintains existing privacy and security standards

## Examples

See what Spark has learned in detail:

```bash
spark learnings --view detailed --limit 5
```

Get a quick summary of learning patterns:

```bash
spark learnings --view summary
```

Track learning activity over the past week:

```bash
spark learnings --view timeline --days 7
```

Export detailed learnings for analysis:

```bash
spark learnings --view detailed --limit 20 --export ./detailed_learnings.json
```
