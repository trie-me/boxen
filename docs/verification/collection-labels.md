# Collection names on labels

Date: 2026-10-03. Source follow-up after the authentication implementation.

All PDF outputs now include a box's current collection memberships: compact
62 × 29 mm, individual 4 × 2-inch, repeated A4, pinned Letter batches, and whole
collection Letter batches. Multiple names are NFC-normalized, sorted by casefolded
name and separated by a middle dot. Ungrouped boxes retain their existing content.

Collection text is regular Noto Sans beneath the bold box name and above the
unchanged monospaced code. Compact labels allow one 7.5 pt line; large/A4 labels
allow two lines at 9–8 pt. Titles shrink only within their established minimums
when required to preserve separation. Overflow ends in an ellipsis. QR dimensions,
quiet zone, stock geometry, page breaks and print alignment remain unchanged.

The application reads collection memberships in the same transaction as the
selected boxes, with a single parameterized lookup for a whole batch. Printing
one collection still shows every current membership of each box. No business
records are changed. Single and batch ETags incorporate full normalized collection
names, including portions hidden by overflow, so a rename cannot reuse a stale
tag merely because the visible prefix is unchanged.

Verification: **94 label tests passed**, including 37 new collection cases. The
new tests cover current memberships, deterministic ordering, per-box batch mapping,
rename/removal/deletion and ETags, Unicode normalization, long-name overflow and
physical bounds, plus actual QR decoding at 150 and 203 DPI. Existing individual
and Letter sheet geometry tests also pass. Four disposable sample PDFs were
rendered with Poppler; compact, A4 and mixed Letter layouts were visually inspected.
Ruff, mypy and whitespace checks passed.

Implementation: `backend/boxen/labeling/infrastructure/pdf.py` and the label
membership helper in `backend/boxen/platform/application.py`. Regression tests:
`backend/tests/test_label_collections.py`. No schema or wire-format change.

The running native installation was updated on 2026-10-03 alongside the
[authentication release](authentication-store.md#native-deployment-and-testing).
A PDF generated through its certificate-validated HTTPS endpoint contained the
selected box's code and all of its current collection names; business row hashes
were unchanged.
Already downloaded or printed PDFs do not update; generate fresh labels after
membership changes. Physical printer calibration was not repeated.
