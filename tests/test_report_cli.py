from wika_pipeline.report_cli import format_skip_report, group_skips


def make_report(skipped, issues=None):
    return {
        "source_file": "a.pdf",
        "pages_parsed": 5,
        "pages_total": 5 + len(skipped),
        "pages_skipped": skipped,
        "page_issues": issues or [],
    }


def test_groups_by_reason_and_ignores_the_percentage_value():
    skipped = [
        {"page": 1, "reason": "no running footer found"},
        {"page": 3, "reason": "only 12% of lines are in the gloss column"},
        {"page": 5, "reason": "only 30% of lines are in the gloss column"},
    ]
    groups = group_skips(skipped)
    assert len(groups) == 2
    gloss = groups["only N% of lines are in the gloss column"]
    assert gloss["pages"] == [3, 5]
    assert gloss["percents"] == [12, 30]


def test_report_shows_counts_ranges_and_percent_span():
    skipped = [{"page": n, "reason": "no running footer found"} for n in (1, 2, 3, 7)]
    skipped.append({"page": 9, "reason": "only 5% of lines are headwords"})
    text = format_skip_report(make_report(skipped))
    assert "parsed 5 of 10 pages, 5 skipped" in text
    assert "[no running footer found]  4 pages" in text
    assert "pages: 1-3, 7" in text
    assert "ranged from 5% to 5%" in text


def test_report_lists_page_issues():
    text = format_skip_report(make_report([], [{"page": 4, "issue": "something odd"}]))
    assert "page 4: something odd" in text