"""Role-based access control.

Every protected view declares the *capability* it needs; this module is the
single source of truth mapping capabilities to roles. Templates receive the
same map (``can.patients_manage``) purely for display — the server-side checks
in the mixin/decorator below are what actually enforce access.
"""
from functools import wraps

from django.contrib.auth.mixins import AccessMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ImproperlyConfigured, PermissionDenied

from .models import Role

A, D, N, R, P, C = (Role.ADMIN, Role.DOCTOR, Role.NURSE, Role.RECEPTIONIST, Role.PHARMACIST, Role.ACCOUNTANT)
ALL = {A, D, N, R, P, C}

CAPABILITIES: dict[str, set[str]] = {
    # Patients
    "patients_view": {A, D, N, R, C},
    "patients_view_all": {A, R, C},  # doctors/nurses only see patients assigned to them
    "patients_manage": {A, R},
    "patients_view_clinical": {A, D, N, R},  # blood group, allergies, conditions
    # Doctors & departments
    "doctors_view": {A, D, N, R},
    "doctors_manage": {A},
    "departments_view": {A, D, N, R},
    # Appointments
    "appointments_view": {A, D, R},
    "appointments_manage": {A, R},
    "appointments_change_status": {A, D, R},
    # Medical records & prescriptions
    "records_view": {A, D, N},
    "records_manage": {D},
    "prescriptions_view": {A, D, N, P},
    "prescriptions_manage": {D},
    "prescriptions_dispense": {P},
    # Admissions, beds, nursing
    "admissions_view": {A, D, N, R},
    "admissions_manage": {A, R},
    "admissions_discharge": {A, D, R},
    "beds_view": {A, D, N, R},
    "beds_manage": {A},
    "nursing_view": {A, D, N},
    "nursing_manage": {A, D, N},
    # Pharmacy
    "pharmacy_view": {A, D, P},
    "pharmacy_manage": {A, P},
    # Billing
    "billing_view": {A, C},
    "billing_manage": {A, C},
    # Staff
    "staff_view": ALL,
    "staff_manage": {A},
    # Reports
    "reports_operational": {A, D, R},
    "reports_clinical": {A, D},
    "reports_pharmacy": {A, P},
    "reports_financial": {A, C},
    # Administration
    "adminpanel_access": {A},
}


def has_capability(user, capability: str) -> bool:
    if capability not in CAPABILITIES:
        raise ImproperlyConfigured(f"Unknown capability: {capability!r}")
    if user is None or not user.is_authenticated or not user.is_active:
        return False
    return user.effective_role in CAPABILITIES[capability]


def has_any_capability(user, capabilities) -> bool:
    return any(has_capability(user, cap) for cap in capabilities)


def capabilities_for(user) -> dict[str, bool]:
    return {cap: has_capability(user, cap) for cap in CAPABILITIES}


def require_capability(user, *capabilities):
    if not has_any_capability(user, capabilities):
        raise PermissionDenied


class CapabilityRequiredMixin(AccessMixin):
    """Class-based view guard. ``required_capability`` may be a string or a tuple (any-of)."""

    required_capability: str | tuple[str, ...] | None = None

    def get_required_capabilities(self) -> tuple[str, ...]:
        if self.required_capability is None:
            raise ImproperlyConfigured(f"{type(self).__name__} must define required_capability.")
        if isinstance(self.required_capability, str):
            return (self.required_capability,)
        return tuple(self.required_capability)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        require_capability(request.user, *self.get_required_capabilities())
        return super().dispatch(request, *args, **kwargs)


def capability_required(*capabilities):
    """Function-based view guard (any-of)."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            require_capability(request.user, *capabilities)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def doctor_profile_for(user):
    """Return the Doctor linked to this login, or ``None``."""
    return getattr(user, "doctor_profile", None) if user.is_authenticated else None
