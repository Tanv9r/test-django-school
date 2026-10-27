from django.urls import path

from . import views

app_name = "doctors"

urlpatterns = [
    path("", views.DoctorListView.as_view(), name="list"),
    path("new/", views.doctor_form, name="create"),
    path("<int:pk>/", views.DoctorDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", views.doctor_form, name="edit"),
    path("<int:pk>/toggle-active/", views.doctor_toggle_active, name="toggle_active"),
    path("departments/", views.DepartmentListView.as_view(), name="department_list"),
    path("departments/<int:pk>/", views.DepartmentDetailView.as_view(), name="department_detail"),
]
