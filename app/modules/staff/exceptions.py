from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError


class StaffAssignmentNotFoundError(NotFoundError):
    error_code = "staff_assignment_not_found"


class StaffAssignmentHistoryNotFoundError(NotFoundError):
    error_code = "staff_assignment_history_not_found"


class InvalidStaffAssignmentStateError(ValidationError):
    error_code = "invalid_staff_assignment_state"


class StaffAssignmentConflictError(ConflictError):
    error_code = "staff_assignment_conflict"


class StaffPermissionDeniedError(PermissionDeniedError):
    error_code = "staff_permission_denied"


class InvalidStaffRoleNameError(ValidationError):
    error_code = "invalid_staff_role_name"