from django.urls import path

from . import views

app_name = "appointments"

urlpatterns = [
    path("", views.AppointmentListView.as_view(), name="list"),
    path("calendar/", views.appointment_calendar, name="calendar"),
    path("new/", views.appointment_create, name="create"),
    path("slots/", views.available_slots_api, name="slots"),
    path("<int:pk>/", views.appointment_detail, name="detail"),
    path("<int:pk>/edit/", views.appointment_edit, name="edit"),
    path("<int:pk>/status/", views.appointment_change_status, name="change_status"),
]
