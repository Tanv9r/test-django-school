from django.db import migrations

DEFAULT_METHODS = [
    ("Cash", "Cash paid at the billing counter."),
    ("Card", "Debit or credit card."),
    ("Bank Transfer", "Direct bank or wire transfer."),
]


def create_methods(apps, schema_editor):
    PaymentMethod = apps.get_model("billing", "PaymentMethod")
    for name, description in DEFAULT_METHODS:
        PaymentMethod.objects.get_or_create(name=name, defaults={"description": description})


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]

    operations = [migrations.RunPython(create_methods, migrations.RunPython.noop)]
