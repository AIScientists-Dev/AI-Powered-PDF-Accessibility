"""
Validator - Wrapper for veraPDF validation.

Uses the MCP veraPDF tools to validate PDF/UA compliance and
provides structured results for iterative fixing.

Includes MorphMind Accessibility Score - a weighted scoring system
based on PDF/UA compliance checks.
"""

import subprocess
import json
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from enum import Enum
import re


class ValidationProfile(Enum):
    """PDF validation profiles."""
    PDFUA1 = "ua1"  # PDF/UA-1
    PDFUA2 = "ua2"  # PDF/UA-2
    PDFA1B = "1b"   # PDF/A-1b
    PDFA2B = "2b"   # PDF/A-2b


@dataclass
class ValidationIssue:
    """A single validation issue."""
    rule_id: str
    severity: str  # ERROR, WARNING
    message: str
    location: Optional[str] = None
    clause: Optional[str] = None
    fixable: bool = False
    fix_suggestion: Optional[str] = None


@dataclass
class ValidationResult:
    """Result of PDF validation."""
    is_valid: bool
    profile: str
    total_issues: int
    errors: List[ValidationIssue]
    warnings: List[ValidationIssue]
    summary: str


# Known fixable issues and their solutions
FIXABLE_ISSUES = {
    # Structure issues
    "missing-lang": {
        "patterns": ["lang", "language", "natural language"],
        "fix": "Add /Lang attribute to document root",
        "auto_fix": True,
    },
    "missing-title": {
        "patterns": ["title", "document title"],
        "fix": "Add Title to document metadata",
        "auto_fix": True,
    },
    "missing-marked": {
        "patterns": ["marked", "markinfo"],
        "fix": "Set MarkInfo/Marked to true",
        "auto_fix": True,
    },
    # Figure issues
    "missing-alt-text": {
        "patterns": ["alt", "alternative", "figure", "image"],
        "fix": "Add Alt attribute to Figure elements",
        "auto_fix": True,
    },
    "missing-bounding-box": {
        "patterns": ["bounding box", "bbox"],
        "fix": "Add BBox to figure elements",
        "auto_fix": True,
    },
}


def categorize_issue(message: str, rule_id: str = "") -> tuple[bool, Optional[str]]:
    """
    Categorize a validation issue as fixable or not.

    Returns (is_fixable, fix_suggestion)
    """
    message_lower = message.lower()

    for issue_type, info in FIXABLE_ISSUES.items():
        for pattern in info["patterns"]:
            if pattern in message_lower:
                return info["auto_fix"], info["fix"]

    return False, None


def parse_verapdf_result(result: dict) -> ValidationResult:
    """Parse veraPDF MCP tool result into structured ValidationResult."""
    errors = []
    warnings = []

    # Extract issues from the result
    if "issues" in result:
        for issue in result["issues"]:
            fixable, fix_suggestion = categorize_issue(
                issue.get("message", ""),
                issue.get("rule_id", "")
            )

            validation_issue = ValidationIssue(
                rule_id=issue.get("rule_id", "unknown"),
                severity=issue.get("severity", "ERROR"),
                message=issue.get("message", ""),
                location=issue.get("location"),
                clause=issue.get("clause"),
                fixable=fixable,
                fix_suggestion=fix_suggestion,
            )

            if validation_issue.severity == "ERROR":
                errors.append(validation_issue)
            else:
                warnings.append(validation_issue)

    is_valid = result.get("valid", False) or len(errors) == 0
    profile = result.get("profile", "unknown")

    # Generate summary
    summary_parts = []
    if is_valid:
        summary_parts.append("PDF is valid")
    else:
        summary_parts.append(f"PDF has {len(errors)} errors")

    if warnings:
        summary_parts.append(f"{len(warnings)} warnings")

    fixable_count = sum(1 for e in errors if e.fixable)
    if fixable_count > 0:
        summary_parts.append(f"{fixable_count} auto-fixable")

    return ValidationResult(
        is_valid=is_valid,
        profile=profile,
        total_issues=len(errors) + len(warnings),
        errors=errors,
        warnings=warnings,
        summary=", ".join(summary_parts),
    )


def get_fix_recommendations(result: ValidationResult) -> List[Dict]:
    """
    Get ordered list of fix recommendations based on validation result.

    Returns list of fix actions in recommended order.
    """
    recommendations = []

    # Priority 1: Structure issues (needed for everything else)
    structure_fixes = []
    for error in result.errors:
        if error.fixable and any(
            kw in error.message.lower()
            for kw in ["lang", "title", "marked", "structure"]
        ):
            structure_fixes.append({
                "priority": 1,
                "type": "structure",
                "issue": error.message,
                "fix": error.fix_suggestion,
                "rule_id": error.rule_id,
            })

    # Priority 2: Alt-text issues
    alt_text_fixes = []
    for error in result.errors:
        if error.fixable and any(
            kw in error.message.lower()
            for kw in ["alt", "alternative", "figure", "image"]
        ):
            alt_text_fixes.append({
                "priority": 2,
                "type": "alt_text",
                "issue": error.message,
                "fix": error.fix_suggestion,
                "rule_id": error.rule_id,
            })

    # Combine and deduplicate
    seen = set()
    for fix in structure_fixes + alt_text_fixes:
        key = (fix["type"], fix.get("rule_id", ""))
        if key not in seen:
            recommendations.append(fix)
            seen.add(key)

    return recommendations


def format_validation_report(result: ValidationResult) -> str:
    """Format validation result as a human-readable report."""
    lines = [
        "=" * 60,
        f"PDF/UA Validation Report",
        f"Profile: {result.profile}",
        "=" * 60,
        "",
        f"Status: {'VALID' if result.is_valid else 'INVALID'}",
        f"Total issues: {result.total_issues}",
        f"Errors: {len(result.errors)}",
        f"Warnings: {len(result.warnings)}",
        "",
    ]

    if result.errors:
        lines.append("ERRORS:")
        lines.append("-" * 40)
        for i, error in enumerate(result.errors, 1):
            lines.append(f"{i}. [{error.rule_id}] {error.message}")
            if error.fixable:
                lines.append(f"   FIX: {error.fix_suggestion}")
            lines.append("")

    if result.warnings:
        lines.append("WARNINGS:")
        lines.append("-" * 40)
        for i, warning in enumerate(result.warnings, 1):
            lines.append(f"{i}. [{warning.rule_id}] {warning.message}")
            lines.append("")

    recommendations = get_fix_recommendations(result)
    if recommendations:
        lines.append("RECOMMENDED FIXES (in order):")
        lines.append("-" * 40)
        for rec in recommendations:
            lines.append(f"- [{rec['type']}] {rec['fix']}")
        lines.append("")

    return "\n".join(lines)


# Simple validation without MCP (for testing/standalone use)
def quick_accessibility_check(pdf_path: str) -> Dict:
    """
    Quick accessibility check without full veraPDF.

    Checks basic requirements:
    - Tagged PDF
    - Language set
    - Title present
    - Figures have alt-text
    """
    import pikepdf
    from pikepdf import Name

    issues = []
    checks_passed = []

    with pikepdf.open(pdf_path) as pdf:
        # Check MarkInfo/Marked
        if Name.MarkInfo in pdf.Root:
            if Name.Marked in pdf.Root.MarkInfo and pdf.Root.MarkInfo.Marked:
                checks_passed.append("Document is marked as tagged")
            else:
                issues.append("Document MarkInfo exists but Marked is not True")
        else:
            issues.append("Document is not marked as tagged (missing MarkInfo)")

        # Check language
        if Name.Lang in pdf.Root:
            checks_passed.append(f"Language set: {pdf.Root.Lang}")
        else:
            issues.append("Document language not set")

        # Check title
        has_title = False
        if pdf.docinfo and Name.Title in pdf.docinfo:
            title = str(pdf.docinfo.Title)
            if title and len(title) > 0:
                has_title = True
                checks_passed.append(f"Title present: {title[:50]}...")

        if not has_title:
            issues.append("Document title not set")

        # Check structure tree
        if Name.StructTreeRoot in pdf.Root:
            checks_passed.append("Structure tree present")

            # Check for Figure elements with Alt
            from .tag_injector import get_existing_alt_texts
            try:
                existing_alts = get_existing_alt_texts(pdf_path)
                if existing_alts:
                    with_alt = sum(1 for f in existing_alts if f.get("alt_text"))
                    checks_passed.append(f"Found {len(existing_alts)} figures, {with_alt} with alt-text")
                    if with_alt < len(existing_alts):
                        issues.append(f"{len(existing_alts) - with_alt} figures missing alt-text")
            except Exception:
                pass
        else:
            issues.append("No structure tree (document not properly tagged)")

    return {
        "pdf_path": pdf_path,
        "issues_count": len(issues),
        "passed_count": len(checks_passed),
        "issues": issues,
        "passed": checks_passed,
        "likely_valid": len(issues) == 0,
    }


# =============================================================================
# MorphMind Accessibility Score
# =============================================================================
# A weighted scoring system based on PDF/UA compliance, inspired by:
# - UDOIT (Canvas LMS) - severity-based impact scoring
# - Cypress Accessibility - weighted pass/fail formula
# - W3C metrics - success criteria weighting
# =============================================================================

# Severity weights (based on Cypress model)
SEVERITY_WEIGHTS = {
    "critical": 10,  # Blocks accessibility completely
    "serious": 7,    # Major barriers for users
    "moderate": 3,   # Significant but workable issues
    "minor": 1,      # Minor inconveniences
}

# PDF/UA clause to severity mapping
# Based on ISO 14289-1 clauses and their impact on accessibility
CLAUSE_SEVERITY = {
    # Critical - Document structure (blocks screen readers)
    "6.1": "critical",   # Conformance
    "6.2": "critical",   # MarkInfo
    "7.1": "serious",    # General structure (varies by test)
    "7.2": "serious",    # Language specification

    # Serious - Content accessibility
    "7.3": "serious",    # Embedded files
    "7.4": "moderate",   # Headings
    "7.5": "moderate",   # Tables
    "7.6": "moderate",   # Lists
    "7.7": "moderate",   # Math
    "7.8": "moderate",   # Page layout
    "7.9": "moderate",   # Notes
    "7.10": "moderate",  # References
    "7.11": "moderate",  # Bibliographic entries
    "7.12": "moderate",  # Quotes
    "7.13": "moderate",  # Optional content
    "7.14": "moderate",  # Ruby
    "7.15": "moderate",  # Warichu
    "7.16": "moderate",  # TOC
    "7.17": "moderate",  # Indices

    # Figures and annotations - high impact
    "7.18": "serious",   # Annotations (figures, links)
    "7.18.1": "serious", # General annotation
    "7.18.4": "moderate", # Widget annotations
    "7.18.5": "serious", # Link annotations
    "7.18.6": "critical", # Figure alt-text
    "7.18.7": "serious", # Form fields

    # Text and fonts
    "7.19": "moderate",  # Actions
    "7.20": "moderate",  # XObjects
    "7.21": "serious",   # Fonts
    "7.21.7": "serious", # Font Unicode mapping

    # Default
    "default": "moderate",
}

# More specific test-level severity overrides
TEST_SEVERITY_OVERRIDES = {
    # Clause 7.1 tests with different severities
    ("7.1", 1): "critical",   # Artifact/tagged content mixing
    ("7.1", 2): "critical",   # Tagged inside artifact
    ("7.1", 3): "critical",   # Content tagged or artifact
    ("7.1", 8): "serious",    # XMP metadata
    ("7.1", 10): "moderate",  # DisplayDocTitle
    ("7.1", 11): "critical",  # StructTreeRoot

    # Clause 7.2 language tests
    ("7.2", 2): "moderate",   # Outline language
    ("7.2", 34): "serious",   # Page content language

    # Clause 7.18 annotation tests
    ("7.18.3", 1): "moderate", # Tabs key
    ("7.18.5", 1): "serious",  # Link tagging
    ("7.18.5", 2): "serious",  # Link alt-text
}


@dataclass
class MorphMindScore:
    """MorphMind Accessibility Score result."""
    score: int  # 0-100
    grade: str  # A, B, C, D, F
    passed_rules: int
    failed_rules: int
    passed_checks: int
    failed_checks: int
    weighted_pass: float
    weighted_fail: float
    category_scores: Dict[str, int] = field(default_factory=dict)
    issues_by_severity: Dict[str, int] = field(default_factory=dict)
    top_issues: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "score": self.score,
            "grade": self.grade,
            "passed_rules": self.passed_rules,
            "failed_rules": self.failed_rules,
            "passed_checks": self.passed_checks,
            "failed_checks": self.failed_checks,
            "category_scores": self.category_scores,
            "issues_by_severity": self.issues_by_severity,
            "top_issues": self.top_issues[:5],  # Top 5 issues
            "provider": "MorphMind",
            "disclaimer": "Score methodology may differ from other accessibility tools. Use as a guide alongside manual review.",
        }


def extract_clause_from_context(context: str) -> Tuple[Optional[str], Optional[int]]:
    """Extract clause number and test number from veraPDF context."""
    # Context format varies, try to extract clause info
    # Example patterns in failure messages
    clause_match = re.search(r'Clause\s+(\d+(?:\.\d+)*)', context, re.IGNORECASE)
    test_match = re.search(r'Test\s+(\d+)', context, re.IGNORECASE)

    clause = clause_match.group(1) if clause_match else None
    test = int(test_match.group(1)) if test_match else None

    return clause, test


def get_severity_for_failure(clause: str, test: Optional[int] = None) -> str:
    """Get severity level for a PDF/UA failure."""
    # Check test-specific override first
    if test is not None:
        key = (clause, test)
        if key in TEST_SEVERITY_OVERRIDES:
            return TEST_SEVERITY_OVERRIDES[key]

    # Check clause-level severity
    if clause in CLAUSE_SEVERITY:
        return CLAUSE_SEVERITY[clause]

    # Try parent clause (e.g., "7.18.5" -> "7.18")
    parts = clause.split(".")
    while len(parts) > 1:
        parts.pop()
        parent = ".".join(parts)
        if parent in CLAUSE_SEVERITY:
            return CLAUSE_SEVERITY[parent]

    return CLAUSE_SEVERITY["default"]


def get_severity_weight(severity: str) -> int:
    """Get weight for a severity level."""
    return SEVERITY_WEIGHTS.get(severity, SEVERITY_WEIGHTS["moderate"])


def calculate_morphmind_score(
    passed_rules: int,
    failed_rules: int,
    passed_checks: int,
    failed_checks: int,
    failures: List[Dict] = None,
) -> MorphMindScore:
    """
    Calculate MorphMind Accessibility Score.

    Formula: Score = (Passed_Weighted / (Passed_Weighted + Failed_Weighted)) × 100

    Where weights are based on severity:
    - Critical: 10
    - Serious: 7
    - Moderate: 3
    - Minor: 1

    Args:
        passed_rules: Number of passed PDF/UA rules
        failed_rules: Number of failed PDF/UA rules
        passed_checks: Total passed individual checks
        failed_checks: Total failed individual checks
        failures: List of failure details with clause info

    Returns:
        MorphMindScore with score, grade, and breakdown
    """
    failures = failures or []

    # Categorize failures by severity
    issues_by_severity = {
        "critical": 0,
        "serious": 0,
        "moderate": 0,
        "minor": 0,
    }

    category_scores = {
        "structure": 100,
        "language": 100,
        "figures": 100,
        "links": 100,
        "fonts": 100,
        "metadata": 100,
    }

    top_issues = []
    weighted_fail = 0.0

    # Process each failure
    for failure in failures:
        clause = failure.get("clause", "")
        test = failure.get("test")
        message = failure.get("message", "")
        context_count = failure.get("count", 1)

        # Determine severity
        severity = get_severity_for_failure(clause, test)
        weight = get_severity_weight(severity)

        issues_by_severity[severity] += 1
        weighted_fail += weight * context_count

        # Update category scores
        clause_prefix = clause.split(".")[0] if clause else ""
        if clause_prefix in ["6", "7.1"]:
            if "structure" in message.lower() or "marked" in message.lower():
                category_scores["structure"] = max(0, category_scores["structure"] - weight * 5)
            elif "metadata" in message.lower() or "xmp" in message.lower():
                category_scores["metadata"] = max(0, category_scores["metadata"] - weight * 5)
        elif clause_prefix == "7.2" or "language" in message.lower():
            category_scores["language"] = max(0, category_scores["language"] - weight * 5)
        elif "7.18" in clause:
            if "figure" in message.lower() or "alt" in message.lower():
                category_scores["figures"] = max(0, category_scores["figures"] - weight * 5)
            elif "link" in message.lower():
                category_scores["links"] = max(0, category_scores["links"] - weight * 5)
        elif "7.21" in clause or "font" in message.lower():
            category_scores["fonts"] = max(0, category_scores["fonts"] - weight * 5)

        # Track top issues
        top_issues.append({
            "clause": clause,
            "test": test,
            "severity": severity,
            "weight": weight,
            "message": message[:100],
            "count": context_count,
        })

    # Sort top issues by weight
    top_issues.sort(key=lambda x: x["weight"], reverse=True)

    # Calculate weighted pass score
    # Use the actual pass rate as a base, then penalize for severity
    # This gives a more intuitive score that starts from the pass rate
    total_rules = passed_rules + failed_rules
    if total_rules > 0:
        base_score = (passed_rules / total_rules) * 100
    else:
        base_score = 100

    # Apply severity penalties (max 50 points of penalty)
    severity_penalty = 0
    severity_penalty += issues_by_severity["critical"] * 8   # Heavy penalty
    severity_penalty += issues_by_severity["serious"] * 4    # Moderate penalty
    severity_penalty += issues_by_severity["moderate"] * 1.5 # Light penalty
    severity_penalty += issues_by_severity["minor"] * 0.5    # Minimal penalty

    # Cap penalty at 50 points
    severity_penalty = min(severity_penalty, 50)

    # Calculate final score
    score = int(base_score - severity_penalty)

    # Ensure score is in range
    score = max(0, min(100, score))

    # Store weighted values for reference
    avg_pass_weight = 5
    weighted_pass = passed_rules * avg_pass_weight

    # Determine grade
    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 70:
        grade = "C"
    elif score >= 60:
        grade = "D"
    else:
        grade = "F"

    return MorphMindScore(
        score=score,
        grade=grade,
        passed_rules=passed_rules,
        failed_rules=failed_rules,
        passed_checks=passed_checks,
        failed_checks=failed_checks,
        weighted_pass=weighted_pass,
        weighted_fail=weighted_fail,
        category_scores=category_scores,
        issues_by_severity=issues_by_severity,
        top_issues=top_issues,
    )


def parse_verapdf_for_score(verapdf_result: str) -> MorphMindScore:
    """
    Parse veraPDF validation result and calculate MorphMind score.

    Args:
        verapdf_result: Raw text output from validate_pdfua MCP tool

    Returns:
        MorphMindScore
    """
    # Parse the text result
    passed_rules = 0
    failed_rules = 0
    passed_checks = 0
    failed_checks = 0
    failures = []

    lines = verapdf_result.split("\n")

    for line in lines:
        line = line.strip()

        # Extract summary stats
        if "Passed Rules:" in line:
            match = re.search(r'Passed Rules:\s*(\d+)', line)
            if match:
                passed_rules = int(match.group(1))
        elif "Failed Rules:" in line:
            match = re.search(r'Failed Rules:\s*(\d+)', line)
            if match:
                failed_rules = int(match.group(1))
        elif "Passed Checks:" in line:
            match = re.search(r'Passed Checks:\s*(\d+)', line)
            if match:
                passed_checks = int(match.group(1))
        elif "Failed Checks:" in line:
            match = re.search(r'Failed Checks:\s*(\d+)', line)
            if match:
                failed_checks = int(match.group(1))

        # Extract failure details
        elif line.startswith("**Clause"):
            # Parse: **Clause 7.1** (Test 10)
            clause_match = re.search(r'\*\*Clause\s+([\d.]+)\*\*', line)
            test_match = re.search(r'\(Test\s+(\d+)\)', line)

            if clause_match:
                failure = {
                    "clause": clause_match.group(1),
                    "test": int(test_match.group(1)) if test_match else None,
                    "message": "",
                    "count": 1,
                }
                failures.append(failure)

        elif failures and line and not line.startswith("-") and not line.startswith("*"):
            # Add message to last failure
            if failures[-1]["message"]:
                failures[-1]["message"] += " " + line
            else:
                failures[-1]["message"] = line

        elif line.startswith("- Context:"):
            # Count contexts for weighting
            if failures:
                failures[-1]["count"] = failures[-1].get("count", 0) + 1

    return calculate_morphmind_score(
        passed_rules=passed_rules,
        failed_rules=failed_rules,
        passed_checks=passed_checks,
        failed_checks=failed_checks,
        failures=failures,
    )


def format_morphmind_report(score: MorphMindScore) -> str:
    """Format MorphMind score as a report string."""
    lines = [
        "",
        "=" * 60,
        "  MorphMind Accessibility Score",
        "  Powered by MorphMind",
        "=" * 60,
        "",
        f"  SCORE: {score.score}/100  |  GRADE: {score.grade}",
        "",
        "-" * 60,
        "  Summary",
        "-" * 60,
        f"  Passed Rules: {score.passed_rules}",
        f"  Failed Rules: {score.failed_rules}",
        f"  Passed Checks: {score.passed_checks:,}",
        f"  Failed Checks: {score.failed_checks:,}",
        "",
        "-" * 60,
        "  Issues by Severity",
        "-" * 60,
    ]

    severity_icons = {
        "critical": "!!!",
        "serious": "!! ",
        "moderate": "!  ",
        "minor": ".  ",
    }

    for sev, count in score.issues_by_severity.items():
        if count > 0:
            icon = severity_icons.get(sev, "   ")
            lines.append(f"  {icon} {sev.capitalize()}: {count}")

    if score.category_scores:
        lines.extend([
            "",
            "-" * 60,
            "  Category Breakdown",
            "-" * 60,
        ])
        for cat, cat_score in score.category_scores.items():
            bar_len = cat_score // 5  # 20 chars max
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(f"  {cat.capitalize():12} [{bar}] {cat_score}%")

    if score.top_issues:
        lines.extend([
            "",
            "-" * 60,
            "  Top Issues to Fix",
            "-" * 60,
        ])
        for i, issue in enumerate(score.top_issues[:5], 1):
            lines.append(f"  {i}. [{issue['severity'].upper()}] Clause {issue['clause']}")
            lines.append(f"     {issue['message'][:60]}...")

    lines.extend([
        "",
        "-" * 60,
        "  Note: This score is provided by MorphMind and uses a weighted",
        "  methodology based on PDF/UA compliance. Scores may differ from",
        "  other accessibility tools. Always combine with manual review.",
        "=" * 60,
        "",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        pdf_path = sys.argv[1]
        print(f"Quick accessibility check: {pdf_path}")
        result = quick_accessibility_check(pdf_path)
        print(f"\nPassed ({result['passed_count']}):")
        for p in result['passed']:
            print(f"  ✓ {p}")
        print(f"\nIssues ({result['issues_count']}):")
        for i in result['issues']:
            print(f"  ✗ {i}")
