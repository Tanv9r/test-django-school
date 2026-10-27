from django.urls import path

from . import views

app_name = "records"

urlpatterns = [
    path("", views.RecordListView.as_view(), name="list"),
    path("new/", views.record_create, name="create"),
    path("<int:pk>/", views.record_detail, name="detail"),
    path("<int:pk>/edit/", views.record_edit, name="edit"),
    path("prescriptions/", views.PrescriptionListView.as_view(), name="prescription_list"),
    path("prescriptions/new/", views.prescription_create, name="prescription_create"),
    path("prescriptions/<int:pk>/", views.prescription_detail, name="prescription_detail"),
    path("prescriptions/<int:pk>/print/", views.prescription_print, name="prescription_print"),
    path("prescriptions/<int:pk>/dispense/", views.prescription_dispense, name="prescription_dispense"),
    path("prescriptions/<int:pk>/cancel/", views.prescription_cancel, name="prescription_cancel"),
]
