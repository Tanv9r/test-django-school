from django.urls import include, path

from dashboard import views as dashboard_views

urlpatterns = [
    path("", dashboard_views.home, name="home"),
    path("accounts/", include("accounts.urls")),
    path("dashboard/", include("dashboard.urls")),
    path("patients/", include("patients.urls")),
    path("doctors/", include("doctors.urls")),
    path("appointments/", include("appointments.urls")),
    path("records/", include("medical_records.urls")),
    path("admissions/", include("admissions.urls")),
    path("pharmacy/", include("pharmacy.urls")),
    path("billing/", include("billing.urls")),
    path("staff/", include("staff.urls")),
    path("admin-panel/", include("adminpanel.urls")),
]

handler403 = "core.views.permission_denied"
handler404 = "core.views.page_not_found"
handler500 = "core.views.server_error"
