from django.conf import settings
from django.db import models, transaction


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SequentialCodeMixin:
    """Assigns a human-readable, unique code (e.g. ``PT-000042``) after the first save.

    The code is derived from the primary key, so it is unique without any extra
    counter table and is never reused.
    """

    code_field = "code"
    code_prefix = ""
    code_width = 6

    def build_code(self) -> str:
        return f"{self.code_prefix}{self.pk:0{self.code_width}d}"

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if not getattr(self, self.code_field):
                code = self.build_code()
                setattr(self, self.code_field, code)
                type(self)._default_manager.filter(pk=self.pk).update(**{self.code_field: code})


class HospitalSettings(models.Model):
    """Singleton holding hospital-wide configuration editable from the admin panel."""

    name = models.CharField(max_length=150, default="CityCare General Hospital")
    tagline = models.CharField(max_length=200, blank=True, default="Compassionate care, every day")
    address = models.TextField(blank=True, default="")
    phone = models.CharField(max_length=30, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    currency_symbol = models.CharField(max_length=5, default="$")
    expiry_warning_days = models.PositiveSmallIntegerField(
        default=60, help_text="Medicines expiring within this many days are flagged."
    )
    invoice_footer = models.CharField(
        max_length=255, blank=True, default="Thank you for choosing our hospital. Get well soon!"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "hospital settings"
        verbose_name_plural = "hospital settings"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "HospitalSettings":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class AuditLog(models.Model):
    class Action(models.TextChoices):
        CREATE = "create", "Created"
        UPDATE = "update", "Updated"
        ARCHIVE = "archive", "Archived"
        RESTORE = "restore", "Restored"
        STATUS = "status", "Status changed"
        PAYMENT = "payment", "Payment"
        STOCK = "stock", "Stock movement"
        LOGIN = "login", "Logged in"
        LOGOUT = "logout", "Logged out"
        LOGIN_FAILED = "login_failed", "Failed login"
        ACCESS = "access", "Access change"
        OTHER = "other", "Other"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_logs"
    )
    action = models.CharField(max_length=20, choices=Action.choices, db_index=True)
    model_label = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    object_repr = models.CharField(max_length=255, blank=True)
    message = models.CharField(max_length=255, blank=True)
    changes = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["model_label", "object_id"])]

    def __str__(self):
        return f"{self.get_action_display()} {self.object_repr}".strip()
