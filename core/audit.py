"""Helpers for writing entries to the audit log."""
import logging

from .models import AuditLog

logger = logging.getLogger("hms")


def client_ip(request):
    # REMOTE_ADDR only: X-Forwarded-For is client-controlled unless a trusted proxy sets it.
    return request.META.get("REMOTE_ADDR") if request is not None else None


def _stringify(value):
    if value is None:
        return ""
    if hasattr(value, "all") and callable(value.all):  # querysets / m2m
        return ", ".join(str(v) for v in value.all())
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value)
    return str(value)


def form_changes(form, exclude=("password", "password1", "password2")):
    """Return ``{field: [old, new]}`` for the fields a bound ModelForm changed."""
    changes = {}
    for name in form.changed_data:
        if name in exclude or name not in form.fields:
            continue
        old = form.initial.get(name)
        field = form.fields[name]
        if hasattr(field, "queryset") and old not in (None, "") and not isinstance(old, (list, tuple)):
            old = field.queryset.model._default_manager.filter(pk=old).first()
        changes[name] = [_stringify(old), _stringify(form.cleaned_data.get(name))]
    return changes


def log_action(user, action, obj=None, message="", changes=None, request=None):
    """Record an auditable action. Never raises: auditing must not break the workflow."""
    try:
        entry = AuditLog(
            user=user if (user is not None and getattr(user, "is_authenticated", False)) else None,
            action=action,
            message=message[:255],
            changes=changes or {},
            ip_address=client_ip(request),
        )
        if obj is not None:
            entry.model_label = obj._meta.label
            entry.object_id = str(obj.pk)
            entry.object_repr = str(obj)[:255]
        entry.save()
        return entry
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to write audit log entry")
        return None


def history_for(obj, limit=20):
    return (
        AuditLog.objects.filter(model_label=obj._meta.label, object_id=str(obj.pk))
        .select_related("user")
        .order_by("-created_at")[:limit]
    )
