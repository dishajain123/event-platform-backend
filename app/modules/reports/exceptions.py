from app.exceptions import NotFoundError


class ReportEventNotFoundError(NotFoundError):
    error_code = "report_event_not_found"