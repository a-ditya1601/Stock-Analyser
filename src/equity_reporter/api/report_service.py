from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from equity_reporter.pipeline import RunConfig, run_report
from equity_reporter.utils.errors import ReportError

PDF_MIME_TYPE = "application/pdf"
GeneratedReportPayload = tuple[str, bytes, str]


def generate_report_bytes(
    query: str,
    risk_profile: str = "balanced",
) -> GeneratedReportPayload:
    normalized_query = (query or "").strip()
    if not normalized_query:
        raise ReportError("Ticker or company name cannot be empty.")

    with TemporaryDirectory(prefix="equity_reporter_request_") as temp_dir:
        output_dir = Path(temp_dir)
        output_path = run_report(
            RunConfig(
                ticker=normalized_query,
                risk_profile=risk_profile,
                output_dir=output_dir,
                overwrite=True,
            )
        )

        try:
            report_bytes = output_path.read_bytes()
        except OSError as exc:
            raise ReportError(f"Generated report could not be read: {output_path}") from exc

        return output_path.name, report_bytes, PDF_MIME_TYPE
