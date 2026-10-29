import sys
from pathlib import Path

from wika_pipeline.sampling import (
    SamplingError,
    conclude_sample,
    create_full_review,
    create_sample,
    load_policy,
)

POLICY = Path("config") / "audit_policy.yml"
REVIEWERS = Path("config") / "reviewers.yml"
REVIEW_DIR = Path("data") / "review"

USAGE = (
    "Usage:\n"
    "  python -m wika_pipeline.sampling_cli sample data\\staging\\DOC_ID.entries.jsonl [--seed N]\n"
    "  python -m wika_pipeline.sampling_cli conclude data\\review\\LANG\\audits\\DOC_ID.aud_XXXX.json --approver REVIEWER_ID [--dry-run]\n"
    "  python -m wika_pipeline.sampling_cli full-review data\\review\\LANG\\audits\\DOC_ID.aud_XXXX.json"
)


def take_option(argv, flag, needs_value):
    if flag not in argv:
        return argv, None
    position = argv.index(flag)
    if not needs_value:
        return argv[:position] + argv[position + 1:], True
    try:
        value = argv[position + 1]
    except IndexError:
        raise SystemExit(f"{flag} needs a value")
    return argv[:position] + argv[position + 2:], value


def sample_command(argv):
    argv, seed = take_option(argv, "--seed", True)
    if seed is not None:
        try:
            seed = int(seed)
        except ValueError:
            raise SystemExit("--seed must be a whole number")
    if len(argv) != 1:
        raise SystemExit(USAGE)
    try:
        result = create_sample(argv[0], REVIEW_DIR, load_policy(POLICY), seed=seed)
    except (ValueError, FileExistsError, FileNotFoundError) as error:
        raise SystemExit(str(error))
    manifest = result["manifest"]
    print(f"Unflagged entries still open: {manifest['population_size']}")
    print(f"Sample size required by the policy: {manifest['sample_size']} (seed {manifest['seed']})")
    print(f"Sample covers {len(manifest['sample_pages'])} different pages")
    print(f"Workbook for validators: {result['workbook']}")
    print(f"Sample record (keep this): {result['manifest_path']}")


def conclude_command(argv):
    argv, approver = take_option(argv, "--approver", True)
    argv, dry_run = take_option(argv, "--dry-run", False)
    if len(argv) != 1 or not approver:
        raise SystemExit(USAGE)
    try:
        result = conclude_sample(argv[0], approver, REVIEWERS, REVIEW_DIR, dry_run=bool(dry_run))
    except SamplingError as error:
        print("The sample is not complete yet:")
        for problem in error.problems[:50]:
            print(f"  {problem}")
        if len(error.problems) > 50:
            print(f"  ... and {len(error.problems) - 50} more")
        raise SystemExit(1)
    except (ValueError, FileNotFoundError) as error:
        raise SystemExit(str(error))
    label = "Dry run: " if result["dry_run"] else ""
    print(f"{label}{result['sample_size']} sampled entries checked, {result['errors_found']} with a problem")
    if result["outcome"] == "failed":
        print("The sample FAILED. Nothing was approved in bulk.")
        print("The unflagged entries need a full review. Create the workbook with:")
        print(f"  python -m wika_pipeline.sampling_cli full-review {argv[0]}")
        raise SystemExit(1)
    if result["dry_run"]:
        print(f"The sample passed. {result['to_approve']} unflagged entries would be approved in bulk.")
    else:
        print(f"The sample passed. {result['approved']} unflagged entries were approved in bulk by {approver}.")


def full_review_command(argv):
    if len(argv) != 1:
        raise SystemExit(USAGE)
    try:
        workbook, count = create_full_review(argv[0], REVIEW_DIR)
    except (ValueError, FileExistsError, FileNotFoundError) as error:
        raise SystemExit(str(error))
    print(f"{count} entries written to {workbook}")
    print("Reviewers fill it in, then run: python -m wika_pipeline.review_cli apply " + str(workbook))


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    commands = {"sample": sample_command, "conclude": conclude_command, "full-review": full_review_command}
    if not argv or argv[0] not in commands:
        raise SystemExit(USAGE)
    commands[argv[0]](argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
