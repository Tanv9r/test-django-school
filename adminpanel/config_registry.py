"""Configurable lookup tables managed from the admin panel with one set of generic views."""
from dataclasses import dataclass, field

from admissions.forms import RoomTypeForm
from admissions.models import RoomType
from billing.forms import PaymentMethodForm
from billing.models import PaymentMethod
from doctors.forms import DepartmentForm
from doctors.models import Department
from pharmacy.forms import MedicineCategoryForm
from pharmacy.models import MedicineCategory


@dataclass(frozen=True)
class ConfigSection:
    slug: str
    title: str
    singular: str
    icon: str
    model: type
    form: type
    columns: list = field(default_factory=list)  # (attribute, label)
    description: str = ""


SECTIONS = {
    s.slug: s
    for s in [
        ConfigSection("departments", "Departments", "department", "building", Department, DepartmentForm,
                      [("name", "Name"), ("location", "Location"), ("description", "Description")],
                      "Clinical departments that doctors, rooms and staff belong to."),
        ConfigSection("room-types", "Room types", "room type", "door-closed", RoomType, RoomTypeForm,
                      [("name", "Name"), ("daily_rate", "Daily rate"), ("description", "Description")],
                      "Ward and room categories with their daily charge."),
        ConfigSection("payment-methods", "Payment methods", "payment method", "credit-card", PaymentMethod, PaymentMethodForm,
                      [("name", "Name"), ("description", "Description")],
                      "Methods accepted when recording invoice payments."),
        ConfigSection("medicine-categories", "Medicine categories", "medicine category", "tags", MedicineCategory, MedicineCategoryForm,
                      [("name", "Name"), ("description", "Description")],
                      "Categories used to organise the pharmacy inventory."),
    ]
}
