from django.urls import path

from . import views

app_name = "pharmacy"

urlpatterns = [
    path("", views.MedicineListView.as_view(), name="list"),
    path("new/", views.medicine_form, name="create"),
    path("transactions/", views.TransactionListView.as_view(), name="transactions"),
    path("<int:pk>/", views.medicine_detail, name="detail"),
    path("<int:pk>/edit/", views.medicine_form, name="edit"),
    path("<int:pk>/adjust/", views.stock_adjust, name="adjust"),
]
